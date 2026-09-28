# One-click: pull origin/main on HK ECS and restart workflow-api.
# Does not commit or push. Code must already be on origin/main.
#
# Usage (from pybroker_integration):
#   powershell -ExecutionPolicy Bypass -File .\scripts\deploy_hk_workflow_api.ps1
#   .\scripts\deploy_hk_workflow_api.ps1
#   .\scripts\deploy_hk_workflow_api.ps1 -HostName 47.76.54.42 -Branch main

[CmdletBinding()]
param(
    [string]$HostName = "47.76.54.42",
    [string]$User = "root",
    [string]$IdentityFile = "",
    [string]$RepoDir = "/root/pybroker_trade-vue",
    [string]$Branch = "main",
    [string]$ServiceName = "workflow-api",
    [int]$ConnectTimeout = 20
)

$ErrorActionPreference = "Stop"

if (-not $IdentityFile) {
    $IdentityFile = Join-Path $env:USERPROFILE ".ssh\workflow_ecs_deploy"
}
if (-not (Test-Path -LiteralPath $IdentityFile)) {
    Write-Error "SSH key not found: $IdentityFile"
    exit 1
}

$sshTarget = $User + "@" + $HostName
$syncScript = $RepoDir + "/A_stocks/ma_strategy_project/pybroker_integration/scripts/sync_workflow_api_on_server.sh"
$sshArgs = @(
    "-i", $IdentityFile,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", ("ConnectTimeout=" + $ConnectTimeout),
    $sshTarget
)

$beforeCmd = 'cd "' + $RepoDir + '" && git log -1 --format=''%h %ci %s'' && systemctl is-active "' + $ServiceName + '"'
$deployCmd = 'export REPO_DIR="' + $RepoDir + '" DEPLOY_BRANCH="' + $Branch + '" SERVICE_NAME="' + $ServiceName + '" && bash "' + $syncScript + '"'
$afterCmd = 'cd "' + $RepoDir + '" && echo COMMIT:$(git log -1 --format=''%h %ci %s'') && echo SERVICE:$(systemctl is-active "' + $ServiceName + '")'

Write-Host "=== before ===" -ForegroundColor Cyan
& ssh @sshArgs $beforeCmd
if ($LASTEXITCODE -ne 0) {
    Write-Error ("SSH precheck failed, exit=" + $LASTEXITCODE)
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host ("=== sync " + $Branch + " and restart " + $ServiceName + " ===") -ForegroundColor Cyan
& ssh @sshArgs $deployCmd
if ($LASTEXITCODE -ne 0) {
    Write-Error ("deploy script failed, exit=" + $LASTEXITCODE)
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "=== after ===" -ForegroundColor Cyan
$after = & ssh @sshArgs $afterCmd
if ($LASTEXITCODE -ne 0) {
    Write-Error ("post-check failed, exit=" + $LASTEXITCODE)
    exit $LASTEXITCODE
}
$afterText = ($after | Out-String)
Write-Host $afterText.TrimEnd()

if ($afterText -notmatch "SERVICE:active") {
    Write-Error ($ServiceName + " is not active")
    exit 2
}

Write-Host ""
Write-Host "deploy ok" -ForegroundColor Green
exit 0
