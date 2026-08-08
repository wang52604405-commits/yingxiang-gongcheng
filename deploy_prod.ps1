# -*- coding: utf-8 -*-
# 自动部署脚本（GitHub Actions 自托管 runner 调用）
#
# 流程：构建 -> 防篡改签名 -> 停 5088 -> 备份 -> 替换 -> 重启 -> 健康检查
# 安全设计：
#   - 私钥路径由环境变量 ALBUM_SIGN_KEY 注入（本机路径，绝不进仓库 / Secrets）
#   - 先构建成功再动生产，构建失败整个流程提前退出，5088 不受影响
#   - 数据目录 D:\工程影像资料 全程不触碰

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

# ---------- 5. 停 5088 + 桌面启动器（占用 DLL 的全部进程） ----------
Write-Host ""
Write-Host "[5/7] 停止 $port 与桌面启动器"
# 停所有 album_server.exe / 工程影像管理平台.exe 进程（不只看监听端口，
# 桌面启动器也会占用 _internal 的 DLL，不停会导致替换失败）
$procs = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -in @("album_server.exe", "工程影像管理平台.exe") })
foreach ($proc in $procs) {
    Write-Host "    停止 PID $($proc.ProcessId) $($proc.Name)"
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}
# 额外兜底：停监听端口的进程（防止进程名不同但占用端口）
$conn = Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Host "    停止监听 PID $($conn.OwningProcess)"
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
}
# 等待进程退出并释放 DLL 句柄（最多 30 秒）
for ($i = 0; $i -lt 30; $i++) {
    $alive = Get-Process album_server, "工程影像管理平台" -ErrorAction SilentlyContinue
    if (-not $alive) { break }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 1

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
        if ($i -ge 29) { throw "无法删除 _internal（文件被占用）: $_" }
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
$cmdLine = 'cmd /d /c set ALBUM_HOST=0.0.0.0&& set ALBUM_PORT=' + $port + '&& set ALBUM_DATA_DIR=' + $dataDir + '&& set ALBUM_LICENSE_FILE=' + $licPath + '&& ' + $exePath + ' >> ' + $outLog + ' 2>> ' + $errLog
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $installDir }
if ($created.ReturnValue -ne 0) {
    throw "[7/7] WMI 启动失败（返回值 $($created.ReturnValue)）"
}

# OCR 等大模块首次加载较慢（可能 20 秒+），轮询等待健康（最多 60 秒）
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest "http://127.0.0.1:$port/api/projects" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        # 服务未就绪，继续等
    }
    Start-Sleep -Seconds 1
}
if (-not $healthy) { throw "[7/7] 健康检查失败：60 秒内未就绪" }
Write-Host ""
Write-Host "[OK] 部署完成，$port 健康检查通过"
