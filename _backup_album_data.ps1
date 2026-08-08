$ErrorActionPreference = "Continue"

# 数据目录：优先读注册表（安装器写入的 DataDir），其次环境变量，最后回退到旧路径。
# 旧脚本写死 E:\use\data，但真实照片数据默认在 D:\工程影像资料，备份会备空目录。
$sourceDir = $env:ALBUM_DATA_DIR
if (-not $sourceDir) {
    try {
        $reg = Get-ItemProperty -Path "HKCU:\Software\工程影像管理平台" -ErrorAction SilentlyContinue
        if ($reg -and $reg.DataDir) { $sourceDir = $reg.DataDir }
    } catch { }
}
if (-not $sourceDir) { $sourceDir = "D:\工程影像资料" }
$backupRoot = "E:\use\_data_backups"
$dateStamp = Get-Date -Format "yyyyMMdd"
$timeStamp = Get-Date -Format "HHmmss"
$backupDir = Join-Path $backupRoot ("album_data_" + $dateStamp + "_" + $timeStamp)

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Write-Host ("[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] Starting backup...")
try {
    Copy-Item -Path $sourceDir -Destination $backupDir -Recurse -Force -ErrorAction Stop
    Write-Host ("[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] Backup completed")
} catch {
    Write-Host ("[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] Backup failed: " + $_)
    exit 1
}

$cutoff = (Get-Date).AddDays(-30)
Get-ChildItem -Path $backupRoot -Directory | Where-Object { $_.CreationTime -lt $cutoff } | ForEach-Object {
    Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
}
