#requires -Version 5.1

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LauncherPath = Join-Path $PSScriptRoot "Start-iMPS-FaultDetection.ps1"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "iMPS Fault Detection.lnk"
$PowerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$EdgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if (-not (Test-Path -LiteralPath $LauncherPath -PathType Leaf)) {
    throw "Launcher not found: $LauncherPath"
}
if (-not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw "Desktop folder not found: $DesktopPath"
}
if (-not (Test-Path -LiteralPath $PowerShellPath -PathType Leaf)) {
    throw "Windows PowerShell not found: $PowerShellPath"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $PowerShellPath
$shortcut.Arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $LauncherPath
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = "iMPS AI Charger Fault Detection"
$shortcut.WindowStyle = 7
if (Test-Path -LiteralPath $EdgePath -PathType Leaf) {
    $shortcut.IconLocation = "$EdgePath,0"
}
$shortcut.Save()

if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
    throw "Shortcut could not be created: $ShortcutPath"
}

Write-Output $ShortcutPath
