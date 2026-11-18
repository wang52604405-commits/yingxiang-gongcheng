# -*- coding: utf-8 -*-
# 自动部署脚本（GitHub Actions 自托管 runner 调用）
#
# 流程：独立构建 -> 验签 -> 在线版本核查和程序快照 -> 替换 -> 健康检查；失败时恢复旧程序
# 安全设计：
#   - 私钥路径由环境变量 ALBUM_SIGN_KEY 注入（本机路径，绝不进仓库 / Secrets）
#   - 先构建成功再动生产，构建失败整个流程提前退出，5088 不受影响
#   - 数据目录 D:\工程影像资料 全程不触碰
#   - 只停止目标安装目录中的正式进程，或经本产品接口签名确认的旧源码实例

$ErrorActionPreference = "Stop"

$repoRoot   = $PSScriptRoot
$distDir    = Join-Path $repoRoot "dist\工程影像管理平台"
$signKey    = $env:ALBUM_SIGN_KEY
$installDir = $env:ALBUM_INSTALL_DIR
$dataDir    = $env:ALBUM_DATA_DIR
$port       = $env:ALBUM_PORT

if (-not $signKey)   { throw "缺少 ALBUM_SIGN_KEY 环境变量" }
if (-not $installDir){ throw "缺少 ALBUM_INSTALL_DIR 环境变量" }
if (-not $dataDir)   { throw "缺少 ALBUM_DATA_DIR 环境变量" }
if (-not $port)      { $port = "5088" }
$installDir = [IO.Path]::GetFullPath($installDir).TrimEnd([char[]]'\/')
$allowedAppNames = @("album_server.exe", "工程影像管理平台.exe")

function Test-IsInstalledAppProcess($process) {
    try {
        $executable = [string]$process.ExecutablePath
        if (-not $executable) { return $false }
        $full = [IO.Path]::GetFullPath($executable)
        $directory = [IO.Path]::GetDirectoryName($full).TrimEnd([char[]]'\/')
        return (($allowedAppNames -contains [IO.Path]::GetFileName($full)) -and
            [string]::Equals($directory, $installDir, [StringComparison]::OrdinalIgnoreCase))
    } catch {
        return $false
    }
}

function Stop-InstalledAppProcesses {
    # The tray launcher may remain alive even after its listener exited.
    # Revalidate each PID, creation time and exact install path before stop.
    $installed = @(Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object { Test-IsInstalledAppProcess $_ })
    foreach ($candidate in $installed) {
        $live = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$candidate.ProcessId) -ErrorAction Stop
        if (-not $live) { continue }
        if (-not $candidate.CreationDate -or -not $live.CreationDate -or
            -not (Test-IsInstalledAppProcess $live) -or $live.CreationDate -ne $candidate.CreationDate) {
            throw "Application process identity changed; update stopped without touching it."
        }
        Write-Host "    Closing verified installed process PID=$($live.ProcessId) Name=$($live.Name)"
        Stop-Process -Id ([int]$live.ProcessId) -Force -ErrorAction Stop
    }
}

function Get-SafeProcessCommandLine($process) {
    try {
        $commandLine = [string]$process.CommandLine
    } catch {
        return ""
    }
    if (-not $commandLine) { return "" }
    return [regex]::Replace(
        $commandLine,
        '(?i)(--?[A-Za-z0-9_-]*(?:pass|password|token|secret|key)[A-Za-z0-9_-]*)(=|\s+)(?:"[^"]*"|\S+)',
        '$1$2***'
    )
}

function Test-IsLegacySourceLauncherText($value) {
    if (-not $value) { return $false }
    return ([string]$value -match '(?i)(?:^|[\s"''\\/])(?:autostart_album\.ps1|start_album\.bat)(?:[\s"'']|$)')
}

function Get-LegacySourceAutostartEnvironmentValue($target) {
    return [Environment]::GetEnvironmentVariable("ALBUM_ENABLE_SOURCE_AUTOSTART", $target)
}

function Assert-NoLegacySourceLauncherProcess {
    # 这里只核查，绝不按脚本名批量停止进程。旧启动器仍在运行时先停止发布。
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach ($process in $processes) {
        if (Test-IsLegacySourceLauncherText ([string]$process.CommandLine)) {
            throw "旧源码启动器仍在运行，发布已停止；未修改或停止该进程。"
        }
    }
}

function Assert-LegacySourceAutostartDisabled {
    # 只读确认当前进程及当前用户持久化开关均已关闭，不修改任何环境变量。
    foreach ($target in @("Process", "User")) {
        $value = Get-LegacySourceAutostartEnvironmentValue $target
        if ($value -cne "0") {
            throw "旧源码自启动开关 $target 尚未明确关闭，发布已停止；未修改配置。"
        }
    }

    # 两处 Run 只读核查；正式安装版自启动项原样保留。无法读取时终止发布。
    foreach ($runPath in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
    )) {
        if (-not (Test-Path -LiteralPath $runPath -ErrorAction Stop)) { continue }
        $item = Get-ItemProperty -LiteralPath $runPath -ErrorAction Stop
        if ($null -eq $item) { throw "无法读取 Run 启动项，发布已停止。" }
        foreach ($property in @($item.PSObject.Properties)) {
            if (Test-IsLegacySourceLauncherText ([string]$property.Value)) {
                throw "检测到旧源码 Run 启动项，发布已停止；未修改注册表。"
            }
        }
    }

    # 包括已禁用的历史任务；存在或无法读取均需人工处理，不在发布中修复。
    $tasks = @(Get-ScheduledTask -ErrorAction Stop)
    foreach ($task in $tasks) {
        $actionText = (@($task.Actions) | ForEach-Object {
            ([string]$_.Execute) + ' ' + ([string]$_.Arguments) + ' ' + ([string]$_.WorkingDirectory)
        }) -join ' '
        if (Test-IsLegacySourceLauncherText $actionText) {
            throw "检测到旧源码计划任务，发布已停止；未停止或禁用任务。"
        }
    }
    Assert-NoLegacySourceLauncherProcess
    Write-Host "    旧源码自启动只读核查通过，正式安装版自启动保持原样"
}

function Test-IsVerifiedLegacySourceAppProcess($process, $pythonExecutable, $expectedVersion, $listenPort) {
    try {
        if (-not $process -or -not $pythonExecutable) { return $false }
        $executable = [string]$process.ExecutablePath
        if (-not $executable) { return $false }
        $fullExecutable = [IO.Path]::GetFullPath($executable)
        $expectedPython = [IO.Path]::GetFullPath([string]$pythonExecutable)
        if (-not [string]::Equals($fullExecutable, $expectedPython, [StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
        $commandLine = [string]$process.CommandLine
        if ($commandLine -notmatch '(?i)(?:^|[\s"\\/])run\.py(?:"|\s|$)') { return $false }

        # 旧源码实例可能早于 app_version 字段，因此不能只靠版本号识别。
        # 必须同时命中本项目独有的 bootstrap 结构签名；若存在 app_version，则记录版本供审计。
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$listenPort/api/bootstrap" -UseBasicParsing -TimeoutSec 5
        if (-not $response -or $response.StatusCode -ne 200) { return $false }
        $bootstrap = $response.Content | ConvertFrom-Json
        if (-not $bootstrap -or $bootstrap.ok -ne $true) { return $false }
        $propertyNames = @($bootstrap.PSObject.Properties.Name)
        $hasProductSignature = (
            ($propertyNames -contains "revision") -and
            ($propertyNames -contains "dashboard") -and
            ($propertyNames -contains "hierarchy") -and
            ($propertyNames -contains "optimization_status")
        )
        if (-not $hasProductSignature) { return $false }
        $runningVersion = [string]$bootstrap.app_version
        if ($runningVersion) {
            Write-Host "    旧源码实例产品签名已确认，版本=$runningVersion，目标版本=$expectedVersion"
        } else {
            Write-Host "    旧源码实例产品签名已确认（旧接口无 app_version）"
        }
        return $true
    } catch {
        Write-Host "    旧源码实例产品签名校验失败：$($_.Exception.Message)"
        return $false
    }
}

function Prepare-IsolatedBuildPython($basePythonExecutable, $temporaryRoot) {
    if (-not $basePythonExecutable -or -not (Test-Path -LiteralPath $basePythonExecutable -PathType Leaf)) {
        throw "构建用基础 Python 不存在，生产程序未改动。"
    }
    $temporaryRoot = [IO.Path]::GetFullPath($temporaryRoot)
    if (-not (Test-Path -LiteralPath $temporaryRoot -PathType Container)) {
        throw "独立构建临时目录不存在，生产程序未改动。"
    }
    # Lexical containment alone cannot detect a junction into an application
    # or data directory. Reject reparse points in every relevant ancestry.
    foreach ($candidatePath in @($temporaryRoot, $basePythonExecutable, $installDir, $dataDir)) {
        if (-not $candidatePath) { continue }
        $ancestorPath = [IO.Path]::GetFullPath($candidatePath)
        while ($ancestorPath) {
            if (Test-Path -LiteralPath $ancestorPath) {
                $ancestor = Get-Item -LiteralPath $ancestorPath -Force -ErrorAction Stop
                if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw "构建路径涉及链接或目录联接，发布已停止；生产文件未改动。"
                }
            }
            $parentPath = [IO.Path]::GetDirectoryName($ancestorPath)
            if ($parentPath -eq $ancestorPath) { break }
            $ancestorPath = $parentPath
        }
    }
    try {
        $buildDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($temporaryRoot))
        if (-not $buildDrive.IsReady -or $buildDrive.AvailableFreeSpace -lt 3GB) {
            throw "构建临时盘可用空间不足 3 GB，发布已停止。"
        }
    } catch {
        throw "无法确认构建临时盘至少有 3 GB 可用空间，生产程序未改动。"
    }
    $buildRoot = Join-Path $temporaryRoot ("album-build-" + [Guid]::NewGuid().ToString("N"))
    foreach ($protectedRoot in @($installDir, $dataDir)) {
        if (-not $protectedRoot) { continue }
        $protected = [IO.Path]::GetFullPath($protectedRoot).TrimEnd([char[]]'\/')
        if ($buildRoot.StartsWith($protected + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "构建临时目录位于程序或业务数据目录内，发布已停止。"
        }
    }
    if (Test-Path -LiteralPath $buildRoot) { throw "独立构建目录已存在，拒绝复用。" }
    # Retain this run's scratch environment for diagnosis. Future runs check
    # the same volume first and stop rather than fill it or prune old backups.
    Write-Host "    独立构建临时环境保留供核查：$buildRoot"
    # Default venv isolation excludes base/user site-packages; never use
    # --system-site-packages or install anything through the base interpreter.
    & $basePythonExecutable -I -m venv --copies $buildRoot
    if ($LASTEXITCODE -ne 0) { throw "创建独立构建环境失败，生产程序未改动。" }
    $buildPython = Join-Path $buildRoot "Scripts\python.exe"
    $configuration = Join-Path $buildRoot "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $configuration -PathType Leaf)) {
        throw "独立构建环境不完整，发布已停止。"
    }
    $configurationText = Get-Content -LiteralPath $configuration -Raw -Encoding UTF8
    if ($configurationText -notmatch '(?im)^include-system-site-packages\s*=\s*false\s*$') {
        throw "构建环境未隔离原有依赖，发布已停止。"
    }
    & $buildPython -I -c "import pathlib,site,sys; expected=pathlib.Path(sys.argv[1]).resolve(); assert pathlib.Path(sys.prefix).resolve()==expected; assert sys.prefix!=sys.base_prefix; assert site.ENABLE_USER_SITE is False" $buildRoot
    if ($LASTEXITCODE -ne 0) { throw "独立构建解释器校验失败，发布已停止。" }
    return $buildPython
}

function Get-DeploymentListenerPids {
    # An empty port is a valid result; inventory errors still stop deployment.
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { [int]$_.LocalPort -eq [int]$port } |
        ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
}

function Get-InstalledServiceVersion($requiredVersion = "") {
    $listenerPids = @(Get-DeploymentListenerPids)
    if ($listenerPids.Count -ne 1) { throw "无法唯一确认正式服务监听进程。" }
    $owner = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listenerPids[0]) -ErrorAction Stop
    if (-not $owner -or -not $owner.CreationDate -or -not (Test-IsInstalledAppProcess $owner)) {
        throw "监听进程不属于目标安装目录中的正式程序。"
    }
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/bootstrap" -UseBasicParsing -TimeoutSec 5
    if (-not $response -or $response.StatusCode -ne 200) { throw "正式服务健康接口不可用。" }
    $bootstrap = $response.Content | ConvertFrom-Json
    $version = [string]$bootstrap.app_version
    if ($bootstrap.ok -ne $true -or [string]::IsNullOrWhiteSpace($version)) { throw "正式服务没有返回可核实的版本。" }
    if ($requiredVersion -and $version -cne [string]$requiredVersion) { throw "正式服务版本与要求的版本不一致。" }
    # Bind the HTTP response to the unchanged, still-owned listening process.
    $confirmedPids = @(Get-DeploymentListenerPids)
    $live = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$owner.ProcessId) -ErrorAction Stop
    if ($confirmedPids.Count -ne 1 -or [int]$confirmedPids[0] -ne [int]$owner.ProcessId -or
        -not $live -or $live.CreationDate -ne $owner.CreationDate -or -not (Test-IsInstalledAppProcess $live)) {
        throw "健康核查期间正式服务进程身份发生变化。"
    }
    return $version
}

function Wait-InstalledServiceVersion($requiredVersion, $attempts = 60) {
    for ($attempt = 0; $attempt -lt $attempts; $attempt++) {
        try { return Get-InstalledServiceVersion $requiredVersion } catch {
            if ($attempt -eq ($attempts - 1)) { throw "未能确认正式服务版本 ${requiredVersion}：$($_.Exception.Message)" }
        }
        Start-Sleep -Seconds 1
    }
}

function Invoke-ProgramSnapshotAction($action, $snapshotPath, $version) {
    $snapshotArguments = @(
        (Join-Path $repoRoot "desktop_program_snapshot.py"), $action,
        "--install-root", $installDir, "--data-root", $dataDir, "--snapshot", $snapshotPath
    )
    if ($action -eq "create") { $snapshotArguments += @("--version", $version, "--replacement-root", $distDir) }
    $output = & $basePythonPath -I @snapshotArguments
    if ($LASTEXITCODE -ne 0) { throw "程序恢复快照 $action 失败；证据保留于 $snapshotPath。" }
    $result = ($output -join "`n") | ConvertFrom-Json
    if ($result.ok -ne $true -or [string]$result.version -cne [string]$version) {
        throw "程序恢复快照版本或校验结果不一致；证据保留于 $snapshotPath。"
    }
}

function Stop-InstalledAppProcessesAndWait {
    for ($i = 0; $i -lt 30; $i++) {
        Assert-NoLegacySourceLauncherProcess
        $alive = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { Test-IsInstalledAppProcess $_ })
        if (-not $alive) { return }
        Stop-InstalledAppProcesses
        Start-Sleep -Seconds 1
    }
    throw "目标安装目录中的正式程序未能退出；未替换程序文件。"
}

function Stop-DeploymentApplication {
    $sourceStopDeadline = (Get-Date).AddSeconds(15)
    do {
        Assert-NoLegacySourceLauncherProcess
        $listenerPids = @(Get-DeploymentListenerPids)
        if (-not $listenerPids) { break }
        foreach ($listenerPid in $listenerPids) {
            $owner = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listenerPid) -ErrorAction Stop
            if (-not $owner) {
                Write-Host "    PID $listenerPid 正在退出，等待端口表刷新"
                continue
            }
            if (Test-IsInstalledAppProcess $owner) { Stop-InstalledAppProcesses; continue }
            if (Test-IsVerifiedLegacySourceAppProcess $owner $pythonPath $expectedVersion $port) {
                $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$owner.ParentProcessId) -ErrorAction Stop
                if ($parent -and (Test-IsLegacySourceLauncherText ([string]$parent.CommandLine))) {
                    throw "旧源码启动器在核查后出现，发布已停止；未停止启动器或其源码实例。"
                }
                $live = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listenerPid) -ErrorAction Stop
                if (-not $live) { continue }
                if (-not $owner.CreationDate -or -not $live.CreationDate -or $live.CreationDate -ne $owner.CreationDate -or
                    [string]$live.ExecutablePath -cne [string]$owner.ExecutablePath -or
                    [string]$live.CommandLine -cne [string]$owner.CommandLine) {
                    throw "旧源码实例进程身份发生变化，发布已停止；未停止该进程。"
                }
                Stop-Process -Id ([int]$live.ProcessId) -Force -ErrorAction Stop
                continue
            }
            throw "端口 $port 被目标安装目录之外的程序占用；为避免误杀，部署已停止。"
        }
        Start-Sleep -Milliseconds 350
    } while ((Get-Date) -lt $sourceStopDeadline)
    if (@(Get-DeploymentListenerPids).Count) { throw "端口 $port 仍被占用，发布已停止。" }
    Stop-InstalledAppProcessesAndWait
}

function New-DeploymentPortGuard {
    $guard = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, [int]$port)
    try { $guard.Start() } catch { $guard.Stop(); throw }
    return $guard
}

function Assert-ProgramIntegrity($programRoot) {
    & $buildPythonPath -I -X utf8 (Join-Path $repoRoot "tamper_guard.py") verify $programRoot
    if ($LASTEXITCODE -ne 0) { throw "程序完整性核查失败：$programRoot。" }
}

function Lock-ProgramPublisher($snapshotPath) {
    # The snapshot helper has already validated this directory and its ancestry.
    # OpenOrCreate never truncates an existing lock file; retain it as evidence.
    $lockPath = Join-Path (Split-Path $snapshotPath -Parent) "publisher.lock"
    if (Test-Path -LiteralPath $lockPath -ErrorAction Stop) {
        $item = Get-Item -LiteralPath $lockPath -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.LinkType) {
            throw "程序发布锁涉及链接，发布已停止。"
        }
    }
    return [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}

function Install-NewProgramFiles($snapshotPath) {
    # Preserve displaced program bytes; never remove live program trees.
    $displaced = Join-Path $snapshotPath ("displaced-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $displaced -ErrorAction Stop | Out-Null
    foreach ($name in @("album_server.exe", "工程影像管理平台.exe", "guard_manifest.dat", "_internal")) {
        $target = Join-Path $installDir $name
        if (Test-Path -LiteralPath $target -ErrorAction Stop) {
            Move-Item -LiteralPath $target -Destination (Join-Path $displaced $name) -ErrorAction Stop
        }
        Copy-Item -LiteralPath (Join-Path $distDir $name) -Destination $target -Recurse -ErrorAction Stop
    }
    Assert-ProgramIntegrity $installDir
}

function Start-InstalledProgram {
    # WMI detaches from the runner Job Object. Paths and credentials stay JSON
    # data inside an encoded command, rather than cmd.exe command fragments.
    $launchData = @{
        executable = (Join-Path $installDir "album_server.exe")
        dataDir = $dataDir; port = [string]$port
        licenseFile = (Join-Path $installDir "license.dat")
        outLog = (Join-Path $installDir "server.out.log")
        errLog = (Join-Path $installDir "server.err.log")
        cloudUser = [string]$env:ALBUM_CLOUD_AUTO_USER
        cloudPass = [string]$env:ALBUM_CLOUD_AUTO_PASS
    }
    $launchJson = ConvertTo-Json -Compress -InputObject $launchData
    $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($launchJson))
    $launcher = @'
$ErrorActionPreference = 'Stop'
$launch = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
$env:ALBUM_HOST = '0.0.0.0'
$env:ALBUM_PORT = [string]$launch.port
$env:ALBUM_DATA_DIR = [string]$launch.dataDir
$env:ALBUM_LICENSE_FILE = [string]$launch.licenseFile
if ($launch.cloudUser) {
    $env:ALBUM_CLOUD_AUTO_USER = [string]$launch.cloudUser
    $env:ALBUM_CLOUD_AUTO_PASS = [string]$launch.cloudPass
}
& ([string]$launch.executable) >> ([string]$launch.outLog) 2>> ([string]$launch.errLog)
'@
    $launcher = $launcher.Replace('__PAYLOAD__', $payload)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($launcher))
    $powershellExecutable = Join-Path $PSHOME "powershell.exe"
    if ($PSVersionTable.PSEdition -eq "Core") { $powershellExecutable = Join-Path $PSHOME "pwsh.exe" }
    $commandLine = '"' + $powershellExecutable + '" -NoProfile -NonInteractive -EncodedCommand ' + $encoded
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine; CurrentDirectory = $installDir
    }
    if (-not $created -or $created.ReturnValue -ne 0) { throw "WMI 启动正式程序失败。" }
}

function Invoke-ProgramReplacement($snapshotPath, $previousVersion) {
    $portGuard = $null
    try {
        # Every failure after the first attempted stop enters program-only recovery.
        Stop-DeploymentApplication
        $portGuard = New-DeploymentPortGuard
        Install-NewProgramFiles $snapshotPath
        $portGuard.Stop()
        $portGuard = $null
        Start-InstalledProgram
        $null = Wait-InstalledServiceVersion $expectedVersion
    } catch {
        $releaseFailure = $_.Exception.Message
        try {
            if ($portGuard) { $portGuard.Stop(); $portGuard = $null }
            Assert-NoLegacySourceLauncherProcess
            Stop-InstalledAppProcessesAndWait
            if (@(Get-DeploymentListenerPids).Count) { throw "恢复时端口被其他程序占用；未停止其他程序。" }
            $portGuard = New-DeploymentPortGuard
            Invoke-ProgramSnapshotAction "verify" $snapshotPath $previousVersion
            Assert-ProgramIntegrity (Join-Path $snapshotPath "program")
            Invoke-ProgramSnapshotAction "restore" $snapshotPath $previousVersion
            Assert-ProgramIntegrity $installDir
            $portGuard.Stop()
            $portGuard = $null
            Start-InstalledProgram
            $null = Wait-InstalledServiceVersion $previousVersion
        } catch {
            throw "发布失败且旧程序恢复未确认：$releaseFailure；恢复错误：$($_.Exception.Message)；保留快照和失败程序：$snapshotPath。未恢复或覆盖工程数据。"
        }
        throw "发布失败，已恢复并核实旧正式程序版本 ${previousVersion}：$releaseFailure；保留证据：$snapshotPath。未恢复或覆盖工程数据。"
    } finally {
        if ($portGuard) { $portGuard.Stop() }
    }
}

# 找到基础 Python（仅用于创建构建环境和核实旧源码实例身份）
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pythonPath = $python.Source
} else {
    $pythonPath = $null
    foreach ($c in @(
        "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe",
        "C:\Python312\python.exe",
        "C:\Python39\python.exe"
    )) {
        if (Test-Path $c) { $pythonPath = $c; break }
    }
    if (-not $pythonPath) { throw "找不到 python.exe" }
}
$basePythonPath = $pythonPath
Write-Host "[*] Base Python: $basePythonPath"

$cloudClientSource = Get-Content (Join-Path $repoRoot "cloud_client.py") -Raw -Encoding UTF8
$versionMatch = [regex]::Match($cloudClientSource, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { throw "无法读取当前 APP_VERSION" }
$expectedVersion = $versionMatch.Groups[1].Value
Write-Host "[*] Expected app version: $expectedVersion"

# ---------- 1. 构建依赖 ----------
Write-Host ""
Write-Host "[1/7] 在独立环境安装构建依赖"
$buildTemporaryRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$buildPythonPath = Prepare-IsolatedBuildPython $basePythonPath $buildTemporaryRoot
$buildEnvironmentRoot = Split-Path (Split-Path $buildPythonPath -Parent) -Parent
Write-Host "[*] Isolated build Python: $buildPythonPath"
# Explicit prefix/no-user also prevents a machine-level pip setting from
# redirecting installation into the original interpreter or a user site.
& $buildPythonPath -I -m pip --isolated install --no-user --prefix $buildEnvironmentRoot --quiet pyinstaller cryptography
if ($LASTEXITCODE -ne 0) { throw "[1/7] 独立环境构建工具安装失败" }
& $buildPythonPath -I -m pip --isolated install --no-user --prefix $buildEnvironmentRoot --quiet -r (Join-Path $repoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "[1/7] 独立环境依赖安装失败" }

# ---------- 2. PyInstaller 构建 ----------
Write-Host ""
Write-Host "[2/7] PyInstaller 构建"
Push-Location $repoRoot
try {
    & $buildPythonPath -I -m PyInstaller --noconfirm --clean 正式版.spec
    if ($LASTEXITCODE -ne 0) { throw "[2/7] PyInstaller 失败（退出码 $LASTEXITCODE）" }
} finally {
    Pop-Location
}
if (-not (Test-Path $distDir)) { throw "构建产物目录不存在: $distDir" }

# ---------- 3. 防篡改签名 ----------
Write-Host ""
Write-Host "[3/7] 防篡改签名"
& $buildPythonPath -I (Join-Path $repoRoot "tamper_guard.py") build "$distDir" --key "$signKey"
if ($LASTEXITCODE -ne 0) { throw "[3/7] 签名失败（退出码 $LASTEXITCODE）" }

# ---------- 4. 完整性校验 ----------
Write-Host ""
Write-Host "[4/7] 完整性校验"
& $buildPythonPath -I (Join-Path $repoRoot "tamper_guard.py") verify "$distDir"
if ($LASTEXITCODE -ne 0) { throw "[4/7] 校验失败（退出码 $LASTEXITCODE）" }

# ---------- 5. 只读核查当前正式版本，并在任何停机前准备程序恢复快照 ----------
Write-Host ""
Write-Host "[5/7] 核实当前正式服务与恢复条件"
Assert-LegacySourceAutostartDisabled
Assert-ProgramIntegrity $installDir
$previousVersion = Get-InstalledServiceVersion
$snapshotPath = Join-Path (Join-Path $installDir ".deployment-snapshots") ([guid]::NewGuid().ToString("N"))
Invoke-ProgramSnapshotAction "create" $snapshotPath $previousVersion
Invoke-ProgramSnapshotAction "verify" $snapshotPath $previousVersion
Assert-ProgramIntegrity (Join-Path $snapshotPath "program")
$publisherLock = $null
try {
    $publisherLock = Lock-ProgramPublisher $snapshotPath
    Assert-LegacySourceAutostartDisabled
    $null = Get-InstalledServiceVersion $previousVersion
    Write-Host "    已核实旧版本 $previousVersion；程序快照保留于 $snapshotPath"

    # ---------- 6. 仅替换程序；任一停机、复制、启动或健康检查失败均进入程序恢复 ----------
    # 快照和恢复只含三个程序文件与 _internal，不含工程数据、同步状态或授权文件。
    Write-Host "[6/7] 替换程序并准备失败恢复"
    Invoke-ProgramReplacement $snapshotPath $previousVersion
} finally {
    if ($publisherLock) { $publisherLock.Dispose() }
}

# ---------- 7. 仅在新版本和实际安装进程身份均已核实后报告成功 ----------
Write-Host ""
Write-Host "[OK] 部署完成，$port 新版本 $expectedVersion 健康检查通过；旧程序快照保留于 $snapshotPath"
