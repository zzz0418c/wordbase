param(
    [Parameter(Mandatory = $true)][string]$RepoUrl,
    [string]$Branch = "main"
)

# 一键把 vocabcurve 推上 GitHub，并把 workflow 放到 .github/workflows/
# 用法： .\setup-cloud.ps1 -RepoUrl "https://github.com/你/vocabcurve.git"

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "没有找到 git，先装一个：https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

# workflow 模板放在 deploy/ 里，推到仓库时放到标准位置
$workflowDir = Join-Path $PSScriptRoot ".github\workflows"
New-Item -ItemType Directory -Force -Path $workflowDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "deploy\daily-vocab.yml") (Join-Path $workflowDir "daily.yml") -Force

if (-not (Test-Path (Join-Path $PSScriptRoot ".git"))) {
    git init | Out-Null
    git checkout -b $Branch 2>$null
}

# 仓库级身份，不动你的全局 git 配置
git config user.name "vocabcurve"
git config user.email "vocabcurve@local"

git add -A
git commit -m "vocabcurve: 单词记忆曲线排程 + 每日微信提醒" 2>$null

$existing = git remote 2>$null
if ($existing -contains "origin") {
    git remote set-url origin $RepoUrl
} else {
    git remote add origin $RepoUrl
}

git push -u origin $Branch

Write-Host ""
Write-Host "✓ 已推送。最后一步（只能你来做）：" -ForegroundColor Green
$settings = $RepoUrl -replace "\.git$", "" -replace "^https://github\.com/", "https://github.com/"
Write-Host "  1) 打开 $settings/settings/secrets/actions/new"
Write-Host "  2) Name 填 VOCAB_PUSH_URL，Secret 填你的微信推送地址"
Write-Host "  3) 到 Actions 页手动 Run workflow 试一次"
Write-Host ""
Write-Host "（详细步骤见 deploy/README-cloud.md）"
