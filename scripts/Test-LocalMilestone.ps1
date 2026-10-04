param([switch]$KeepDatabase)

. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$composeFile = Join-Path $workspacePath 'compose.dev.yml'
Assert-LocalDocker

Push-Location -LiteralPath $workspacePath
try {
    Write-Host 'Building the shared dev image and resetting only morning_quiz_test.'
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'test', 'build', 'migrate')
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'test', 'run', '--rm', 'test-db-reset')
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'test', 'run', '--rm', '--no-deps', 'tests')
    Write-Host 'PASS: containerized migrations, regression, dump/restore and JavaScript syntax checks.'
    Write-Host 'morning_quiz_dev and the persistent PostgreSQL volume were not reset.'
}
finally {
    Pop-Location
}
