param(
    [ValidateSet('all', 'admin', 'mini-app', 'telegram', 'postgres')][string]$Service = 'all',
    [int]$Tail = 150,
    [switch]$Follow
)

. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$composeFile = Join-Path $workspacePath 'compose.dev.yml'
Assert-LocalDocker
$arguments = @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'telegram', 'logs', '--tail', "$Tail")
if ($Follow) { $arguments += '--follow' }
if ($Service -ne 'all') { $arguments += $Service }
Invoke-LocalChecked docker $arguments

