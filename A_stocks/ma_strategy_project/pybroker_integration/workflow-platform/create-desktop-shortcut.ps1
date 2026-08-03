$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $projectDir 'start-dev.bat'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnkName = [string]::Concat([char]0x6D41, [char]0x63A7, [char]0x5236, [char]0x53F0, ' Vue ', [char]0x5E73, [char]0x53F0, '.lnk')
$lnkPath = Join-Path $desktop $lnkName

if (-not (Test-Path -LiteralPath $batPath)) {
  throw "start-dev.bat not found: $batPath"
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($lnkPath)
$shortcut.TargetPath = $batPath
$shortcut.WorkingDirectory = $projectDir
$shortcut.WindowStyle = 1
$shortcut.Description = 'Start workflow-platform Vue Vite dev server'
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$shortcut.Save()

Write-Output "Desktop shortcut created:"
Write-Output $lnkPath
Write-Output "Target:"
Write-Output $batPath
