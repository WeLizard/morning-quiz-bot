. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$stopPath = Join-Path $workspacePath '.local\telegram-test.stop'
New-Item -ItemType File -Path $stopPath -Force | Out-Null
Write-Host 'Stop requested for the local Telegram test runner. It will finish polling and save dev state.'
