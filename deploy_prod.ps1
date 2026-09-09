# -*- coding: utf-8 -*-
# 自动部署脚本（GitHub Actions 自托管 runner 调用）
#
# 流程：构建 -> 防篡改签名 -> 停 5088 -> 备份 -> 替换 -> 重启 -> 健康检查
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

function Disable-LegacySourceAutostart {
    # 新版源码启动脚本读取此变量；同时写入当前进程和当前用户环境，防止后续新进程再次拉起源码版。
    $env:ALBUM_ENABLE_SOURCE_AUTOSTART = "0"
    try {
        [Environment]::SetEnvironmentVariable("ALBUM_ENABLE_SOURCE_AUTOSTART", "0", "User")
        Write-Host "    已关闭旧源码自启动环境开关"
    } catch {
        Write-Host "    [WARN] 无法写入旧源码自启动环境开关：$($_.Exception.Message)"
    }

    # 只删除明确指向两个历史启动器文件的 Run 注册表值；正式安装版工程影像管理平台.exe 启动项不受影响。
    foreach ($runPath in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
    )) {
        try {
            $item = Get-ItemProperty -Path $runPath -ErrorAction SilentlyContinue
            if (-not $item) { continue }
            foreach ($property in @($item.PSObject.Properties)) {
                if ($property.Name -like 'PS*') { continue }
                $value = [string]$property.Value
                if (Test-IsLegacySourceLauncherText $value) {
                    Remove-ItemProperty -Path $runPath -Name $property.Name -Force -ErrorAction Stop
                    Write-Host "    已移除旧源码 Run 启动项：$($property.Name)"
                }
            }
        } catch {
            Write-Host "    [WARN] 检查 Run 启动项失败：$runPath $($_.Exception.Message)"
        }
    }

    # 只停止并禁用 Action 明确引用两个历史启动器文件的计划任务。
    try {
        $tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue)
        foreach ($task in $tasks) {
            $actionText = (@($task.Actions) | ForEach-Object {
                ([string]$_.Execute) + ' ' + ([string]$_.Arguments) + ' ' + ([string]$_.WorkingDirectory)
            }) -join ' '
            if (Test-IsLegacySourceLauncherText $actionText) {
                Stop-ScheduledTask -InputObject $task -ErrorAction SilentlyContinue
                Disable-ScheduledTask -InputObject $task -ErrorAction SilentlyContinue | Out-Null
                Write-Host "    已停用旧源码计划任务：$($task.TaskPath)$($task.TaskName)"
            }
        }
    } catch {
        Write-Host "    [WARN] 检查旧源码计划任务失败：$($_.Exception.Message)"
    }

    # 当前仍在运行的 powershell/cmd 等启动器，只在命令行明确命中历史脚本名时停止。
    $launchers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        Test-IsLegacySourceLauncherText ([string]$_.CommandLine)
    })
    foreach ($launcher in $launchers) {
        if ([int]$launcher.ProcessId -eq $PID) { continue }
        Write-Host "    停止旧源码启动器 PID $($launcher.ProcessId) $($launcher.Name)"
        Stop-Process -Id ([int]$launcher.ProcessId) -Force -ErrorAction SilentlyContinue
    }
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

# 找到 Python（服务账户 PATH 可能不含 python.exe）
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
Write-Host "[*] Python: $pythonPath"

$cloudClientSource = Get-Content (Join-Path $repoRoot "cloud_client.py") -Raw -Encoding UTF8
$versionMatch = [regex]::Match($cloudClientSource, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { throw "无法读取当前 APP_VERSION" }
$expectedVersion = $versionMatch.Groups[1].Value
Write-Host "[*] Expected app version: $expectedVersion"

# ---------- 1. 构建依赖 ----------
Write-Host ""
Write-Host "[1/7] 安装构建依赖"
& $pythonPath -m pip install --quiet pyinstaller cryptography
& $pythonPath -m pip install --quiet -r (Join-Path $repoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "[1/7] pip install 失败" }

# ---------- 2. PyInstaller 构建 ----------
Write-Host ""
Write-Host "[2/7] PyInstaller 构建"
Push-Location $repoRoot
try {
    & $pythonPath -m PyInstaller --noconfirm --clean 正式版.spec
    if ($LASTEXITCODE -ne 0) { throw "[2/7] PyInstaller 失败（退出码 $LASTEXITCODE）" }
} finally {
    Pop-Location
}
if (-not (Test-Path $distDir)) { throw "构建产物目录不存在: $distDir" }

# ---------- 3. 防篡改签名 ----------
Write-Host ""
Write-Host "[3/7] 防篡改签名"
& $pythonPath "tamper_guard.py" build "$distDir" --key "$signKey"
if ($LASTEXITCODE -ne 0) { throw "[3/7] 签名失败（退出码 $LASTEXITCODE）" }

# ---------- 4. 完整性校验 ----------
Write-Host ""
Write-Host "[4/7] 完整性校验"
& $pythonPath "tamper_guard.py" verify "$distDir"
if ($LASTEXITCODE -ne 0) { throw "[4/7] 校验失败（退出码 $LASTEXITCODE）" }

# ---------- 5. 精确停止本项目正式进程，以及经严格验证的旧源码实例 ----------
Write-Host ""
Write-Host "[5/7] 停止 $port 与桌面启动器"

Disable-LegacySourceAutostart

# 把 5088 收口到“空闲”状态。每次只允许两类进程被关闭：
# 1) 目标安装目录中的正式程序；2) 经 /api/bootstrap 产品签名验证的旧 python run.py。
# 其它任何监听者均 fail-closed，不会按 Python 名称或端口做全局杀进程。
$sourceStopDeadline = (Get-Date).AddSeconds(15)
do {
    $listenerPids = @(Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    if (-not $listenerPids) { break }

    foreach ($listenerPid in $listenerPids) {
        $owner = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listenerPid) -ErrorAction SilentlyContinue
        if (-not $owner) {
            Write-Host "    [BLOCK] PID $listenerPid：无法读取进程信息"
            throw "端口 $port 被目标安装目录之外的程序占用；为避免误杀，部署已停止。"
        }

        if (Test-IsInstalledAppProcess $owner) {
            Write-Host "    停止本应用监听 PID $listenerPid"
            Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
            continue
        }

        if (Test-IsVerifiedLegacySourceAppProcess $owner $pythonPath $expectedVersion $port) {
            $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$owner.ParentProcessId) -ErrorAction SilentlyContinue
            if ($parent) {
                $parentCommandLine = Get-SafeProcessCommandLine $parent
                Write-Host "    旧源码父进程 PID $($parent.ProcessId) Name=$($parent.Name)"
                if ($parentCommandLine) { Write-Host "    旧源码父进程 CommandLine=$parentCommandLine" }
                if (Test-IsLegacySourceLauncherText ([string]$parent.CommandLine)) {
                    Write-Host "    停止明确命中旧启动器的父进程 PID $($parent.ProcessId)"
                    Stop-Process -Id ([int]$parent.ProcessId) -Force -ErrorAction SilentlyContinue
                }
            }
            Write-Host "    识别并停止本项目旧源码实例 PID $listenerPid ($($owner.Name) run.py)"
            Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
            continue
        }

        $ownerPath = [string]$owner.ExecutablePath
        $ownerCommandLine = Get-SafeProcessCommandLine $owner
        Write-Host "    [BLOCK] PID $listenerPid Name=$($owner.Name) ParentPID=$($owner.ParentProcessId)"
        Write-Host "    [BLOCK] ExecutablePath=$ownerPath"
        if ($ownerCommandLine) { Write-Host "    [BLOCK] CommandLine=$ownerCommandLine" }
        throw "端口 $port 被目标安装目录之外的程序占用；为避免误杀，部署已停止。"
    }
    Start-Sleep -Milliseconds 350
} while ((Get-Date) -lt $sourceStopDeadline)

$remainingListenerPids = @(Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
if ($remainingListenerPids) {
    throw "旧源码实例在 15 秒内持续复活，部署已停止；请检查旧启动器注册。"
}

# 端口清空后由当前部署进程临时占位，防止历史自启动器在备份/复制的几秒空窗重新抢占 5088。
# 占位器只监听本机端口，不处理业务请求；正式服务启动前立即释放。
$portGuard = $null
try {
    $portGuard = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, [int]$port)
    $portGuard.Start()
    Write-Host "    已建立 5088 临时部署占位，阻止旧源码回抢端口"
} catch {
    throw "无法建立 $port 临时部署占位：$($_.Exception.Message)"
}

# 等待目标安装目录中的旧进程完全退出并释放 DLL 句柄（最多 30 秒）。
$alive = @()
for ($i = 0; $i -lt 30; $i++) {
    $alive = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { Test-IsInstalledAppProcess $_ })
    if (-not $alive) { break }
    Start-Sleep -Seconds 1
}
if ($alive) {
    if ($portGuard) { $portGuard.Stop() }
    throw "目标安装目录中的旧版本未能退出，部署已停止。"
}

# ---------- 6. 备份旧版（首次安装时旧文件不存在则跳过） ----------
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Write-Host "[6/7] 备份旧版 -> $stamp"
foreach ($f in @("album_server.exe", "工程影像管理平台.exe", "guard_manifest.dat")) {
    if (Test-Path (Join-Path $installDir $f)) {
        Copy-Item (Join-Path $installDir $f) (Join-Path $installDir "$f.bak-$stamp") -Force
    }
}
if (Test-Path (Join-Path $installDir "_internal")) {
    Copy-Item (Join-Path $installDir "_internal") (Join-Path $installDir "_internal.bak-$stamp") -Recurse -Force
}

# ---------- 7. 替换 + 重启 + 健康检查 ----------
Write-Host "[7/7] 替换并重启"
# 删除 _internal（含 DLL 占用重试，最多 30 秒）
for ($i = 0; $i -lt 30; $i++) {
    try {
        if (Test-Path (Join-Path $installDir "_internal")) {
            Remove-Item (Join-Path $installDir "_internal") -Recurse -Force -ErrorAction Stop
        }
        break
    } catch {
        if ($i -ge 29) {
            if ($portGuard) { $portGuard.Stop() }
            throw "无法删除 _internal（文件被占用）: $_"
        }
        Start-Sleep -Seconds 1
    }
}
Copy-Item (Join-Path $distDir "_internal")          (Join-Path $installDir "_internal")          -Recurse
Copy-Item (Join-Path $distDir "album_server.exe")   (Join-Path $installDir "album_server.exe")   -Force
Copy-Item (Join-Path $distDir "工程影像管理平台.exe") (Join-Path $installDir "工程影像管理平台.exe") -Force
Copy-Item (Join-Path $distDir "guard_manifest.dat") (Join-Path $installDir "guard_manifest.dat") -Force

$env:ALBUM_HOST = "0.0.0.0"
$env:ALBUM_PORT = $port
$env:ALBUM_DATA_DIR = $dataDir
$env:ALBUM_LICENSE_FILE = Join-Path $installDir "license.dat"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

Write-Host "    启动 album_server.exe (port $port, data $dataDir)"
$outLog = Join-Path $installDir "server.out.log"
$errLog = Join-Path $installDir "server.err.log"
$exePath = Join-Path $installDir "album_server.exe"
$licPath = Join-Path $installDir "license.dat"
# 用 WMI 启动：脱离 runner 的 Job Object。若用 Start-Process，job 结束时
# 5088 会随 runner 进程树被一并杀掉（部署“成功”但服务静默下线）。
# 云预览自动同步账号（由 GitHub Secrets 注入，可能为空；空则不传）
if ($env:ALBUM_CLOUD_AUTO_USER) {
    $cloudEnv = '&& set ALBUM_CLOUD_AUTO_USER=' + $env:ALBUM_CLOUD_AUTO_USER + '&& set ALBUM_CLOUD_AUTO_PASS=' + $env:ALBUM_CLOUD_AUTO_PASS
} else {
    $cloudEnv = ""
}
$cmdLine = 'cmd /d /c set ALBUM_HOST=0.0.0.0&& set ALBUM_PORT=' + $port + '&& set ALBUM_DATA_DIR=' + $dataDir + '&& set ALBUM_LICENSE_FILE=' + $licPath + $cloudEnv + '&& ' + $exePath + ' >> ' + $outLog + ' 2>> ' + $errLog

# 文件替换完成后立即释放占位并启动正式服务，把无监听窗口压缩到最小。
if ($portGuard) {
    $portGuard.Stop()
    $portGuard = $null
    Write-Host "    已释放 5088 临时部署占位"
}
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $installDir }
if ($created.ReturnValue -ne 0) {
    throw "[7/7] WMI 启动失败（返回值 $($created.ReturnValue)）"
}

# OCR 等大模块首次加载较慢（可能 20 秒+）。健康检查不仅要求 HTTP 200，
# 还要求版本号等于本次发布版本，且 5088 的实际监听进程来自目标安装目录。
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$port/api/bootstrap" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) {
            $bootstrap = $resp.Content | ConvertFrom-Json
            if ([string]$bootstrap.app_version -eq [string]$expectedVersion) {
                $healthPids = @(Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
                if ($healthPids.Count -eq 1) {
                    $healthOwner = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$healthPids[0]) -ErrorAction SilentlyContinue
                    if ($healthOwner -and (Test-IsInstalledAppProcess $healthOwner)) {
                        $healthy = $true
                        break
                    }
                }
            }
        }
    } catch {
        # 服务未就绪，继续等
    }
    Start-Sleep -Seconds 1
}
if (-not $healthy) { throw "[7/7] 健康检查失败：60 秒内未确认新版本正式服务" }
Write-Host ""
Write-Host "[OK] 部署完成，$port 新版本 $expectedVersion 健康检查通过"
