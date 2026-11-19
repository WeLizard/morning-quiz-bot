param([switch]$KeepDatabase)

. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$composeFile = Join-Path $workspacePath 'compose.dev.yml'
$nightCityDocsPath = (Join-Path $workspacePath 'docs/tasks/night_city').Replace('\', '/')
Assert-LocalDocker

Push-Location -LiteralPath $workspacePath
try {
    Write-Host 'Building the shared dev image and resetting only morning_quiz_test.'
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'test', 'build', 'migrate')
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'test', 'run', '--rm', 'test-db-reset')
    # Existing Night City tests need source-tree schemas that Dockerignore excludes.
    # Scope both additions to pytest so runtime services keep their existing mounts.
    Invoke-LocalChecked docker @(
        'compose', '-p', 'mqb-local-dev', '-f', $composeFile, '--profile', 'test',
        'run', '--rm', '--no-deps',
        '--env', 'PYTHONPATH=/app:/app/tests',
        '--volume', "${nightCityDocsPath}:/app/docs/tasks/night_city:ro",
        'tests'
    )
    Write-Host 'PASS: containerized migrations, regression, dump/restore and JavaScript syntax checks.'
    Write-Host 'morning_quiz_dev and the persistent PostgreSQL volume were not reset.'
}
finally {
    Pop-Location
}
