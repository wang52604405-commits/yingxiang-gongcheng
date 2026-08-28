param(
  [string]$ProjectPath = 'D:\Desktop\工程影像微信发布版',
  [string]$Repository = 'https://github.com/wang52604405-commits/yingxiang-gongcheng.git',
  [string]$Branch = 'codex/wechat-mp-release',
  [switch]$Upload,
  [string]$Version = '1.2.20260828',
  [string]$Description = '备案域名接入、桌面同步与原图中转闭环'
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
  param([string[]]$Arguments)
  & git @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Git command failed: git $($Arguments -join ' ')"
  }
}

function Find-WechatCli {
  $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
  foreach ($root in $roots) {
    $tencent = Join-Path $root 'Tencent'
    if (-not (Test-Path -LiteralPath $tencent)) { continue }
    $candidate = Get-ChildItem -LiteralPath $tencent -Filter 'cli.bat' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
  }
  throw 'Wechat DevTools cli.bat was not found. Install WeChat DevTools first.'
}

function Start-WechatDevTools {
  param([string]$CliPath)
  $installRoot = Split-Path -Parent $CliPath
  $candidate = Get-ChildItem -LiteralPath $installRoot -Filter '*.exe' -File | Where-Object { $_.Length -gt 100MB } | Select-Object -First 1
  if (-not $candidate) { throw 'Wechat DevTools executable was not found.' }
  Start-Process -FilePath $candidate.FullName -ArgumentList @($ProjectPath) | Out-Null
}

function Test-WechatCliProfile {
  $profileRoots = Join-Path $env:LOCALAPPDATA '*\User Data'
  $profile = Get-ChildItem -Path $profileRoots -Filter '.cli' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  return [bool]$profile
}

if (-not (Test-Path -LiteralPath $ProjectPath)) {
  Write-Host "Preparing release directory: $ProjectPath"
  git clone --branch $Branch --single-branch $Repository $ProjectPath
  if ($LASTEXITCODE -ne 0) { throw 'Failed to clone the release branch.' }
} elseif (-not (Test-Path -LiteralPath (Join-Path $ProjectPath '.git'))) {
  throw "The target directory is not a Git repository: $ProjectPath"
}

$origin = (& git -C $ProjectPath remote get-url origin 2>$null)
if (-not $origin) {
  Invoke-Git @('-C', $ProjectPath, 'remote', 'add', 'origin', $Repository)
} elseif ($origin.TrimEnd('/') -ne $Repository.TrimEnd('/')) {
  throw "The Git remote is not the Engineering Image repository: $origin"
}

$dirty = @(& git -C $ProjectPath status --porcelain)
if ($dirty.Count -gt 0) {
  throw "The release directory has uncommitted changes; sync stopped: $ProjectPath"
}

Invoke-Git @('-C', $ProjectPath, 'fetch', 'origin', $Branch)
$localBranch = @(& git -C $ProjectPath branch --list $Branch)
if ($localBranch.Count -eq 0) {
  Invoke-Git @('-C', $ProjectPath, 'switch', '--track', '-c', $Branch, "origin/$Branch")
} else {
  Invoke-Git @('-C', $ProjectPath, 'switch', $Branch)
  Invoke-Git @('-C', $ProjectPath, 'pull', '--ff-only', 'origin', $Branch)
}

$cli = Find-WechatCli
Write-Host "Synced $Branch. Opening WeChat DevTools: $ProjectPath"
if (-not (Test-WechatCliProfile)) {
  Write-Host 'Starting WeChat DevTools to initialize its CLI profile.'
  Start-WechatDevTools $cli
  Start-Sleep -Seconds 5
}
& $cli -o $ProjectPath
if ($LASTEXITCODE -ne 0) {
  Write-Warning 'WeChat DevTools CLI is not ready. Open DevTools -> Settings -> Security Settings -> Service Port, enable it once, then run this script again.'
  exit 0
}

if ($Upload) {
  Write-Host "Uploading WeChat development version: $Version"
  & $cli upload --project $ProjectPath --version $Version --desc $Description --lang zh
  if ($LASTEXITCODE -ne 0) {
    throw 'WeChat development version upload failed.'
  }
}
