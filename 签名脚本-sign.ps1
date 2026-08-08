<#
    代码签名脚本（拿到签名证书后执行）

    用法：
      .\签名脚本-sign.ps1 -CertFile C:\cert\你的证书.pfx -CertPassword 证书密码
      或（证书已装进本机证书库）：
      .\签名脚本-sign.ps1

    说明：
      - 同时给安装包和两个主程序签名，附 SHA-256 时间戳；
      - 签名后 SmartScreen"未知发布者"警告消失，杀软误报率大幅下降；
      - 证书未购买前不要运行本脚本。
#>

param(
    [string]$CertFile = "",
    [string]$CertPassword = "",
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    Write-Error "未找到 signtool。请安装 Windows SDK（含 Signing Tools）：" +
        "https://developer.microsoft.com/windows/downloads/windows-sdk/，或使用 Azure Trusted Signing 的官方工具。"
}

$targets = @(
    "E:\use\dist\工程影像管理平台\工程影像管理平台.exe",
    "E:\use\dist\工程影像管理平台\album_server.exe",
    "E:\use\客户可发送安装包-Win10\发给客户\安装程序.exe",
)

foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target)) {
        Write-Warning "跳过（文件不存在）: $target"
        continue
    }
    Write-Host "[*] 签名: $target"
    if ($CertFile -ne "") {
        & signtool sign /f $CertFile /p $CertPassword /fd SHA256 `
            /tr $TimestampServer /td SHA256 /v $target
    } else {
        & signtool sign /a /fd SHA256 /tr $TimestampServer /td SHA256 /v $target
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "签名失败: $target"
    }
}

Write-Host "[*] 重新生成防篡改清单（签名后 exe 哈希已变化，必须重新生成再编译安装包）"
python "E:\use\tamper_guard.py" build "E:\use\dist\工程影像管理平台" --key "E:\use\keys\private_key.pem"
if ($LASTEXITCODE -ne 0) {
    Write-Error "防篡改清单生成失败"
}

Write-Host "[OK] 全部签名完成。可在文件属性 -> 数字签名 里查看。"
