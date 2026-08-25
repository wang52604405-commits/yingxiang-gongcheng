param(
  [string]$ProjectPath = 'D:\Desktop\工程影像微信发布版',
  [string]$Repository = 'https://github.com/wang52604405-commits/yingxiang-gongcheng.git',
  [string]$Branch = 'codex/wechat-mp-release'
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
  param([string[]]$Arguments)
  & git @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Git 命令失败：git $($Arguments -join ' ')"
  }
}

function Find-WechatCli {
  $candidates = @(
    'C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat',
    'C:\Program Files\Tencent\微信web开发者工具\cli.bat',
    'C:\Program Files (x86)\Tencent\微信开发者工具\cli.bat',
    'C:\Program Files\Tencent\微信开发者工具\cli.bat'
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  throw '找不到微信开发者工具 cli.bat，请先安装开发者工具，或用 -ProjectPath 指定项目目录后手动打开。'
}

if (-not (Test-Path -LiteralPath $ProjectPath)) {
  Write-Host "首次准备微信发布目录：$ProjectPath"
  git clone --branch $Branch --single-branch $Repository $ProjectPath
  if ($LASTEXITCODE -ne 0) { throw '克隆微信发布分支失败。' }
} elseif (-not (Test-Path -LiteralPath (Join-Path $ProjectPath '.git'))) {
  throw "目录不是 Git 仓库：$ProjectPath；请不要在此目录手动初始化 master，请换一个空目录。"
}

$origin = (& git -C $ProjectPath remote get-url origin 2>$null)
if (-not $origin) {
  Invoke-Git @('-C', $ProjectPath, 'remote', 'add', 'origin', $Repository)
} elseif ($origin.TrimEnd('/') -ne $Repository.TrimEnd('/')) {
  throw "该目录的 Git 远程地址不是工程影像仓库：$origin"
}

$dirty = @(& git -C $ProjectPath status --porcelain)
if ($dirty.Count -gt 0) {
  throw "发布目录有未提交修改，为防止覆盖微信开发者工具里的改动，已停止同步：$ProjectPath"
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
Write-Host "已同步到 $Branch，正在打开微信开发者工具：$ProjectPath"
& $cli -o $ProjectPath
if ($LASTEXITCODE -ne 0) {
  throw '微信开发者工具打开失败；可直接在工具中导入这个目录。'
}
