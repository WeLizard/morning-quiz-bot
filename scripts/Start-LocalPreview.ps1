param([string]$Python = '', [switch]$SkipBootstrap)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$Python = Resolve-LocalPython $Python
Assert-LocalDocker
Assert-PreviewStopped -Ports @(4184)
$devLease = Open-LocalDevLease
$previousEnvironment = Set-LocalDevEnvironment
$previousEnvironment['ADMIN_ACCESS_TOKEN'] = $env:ADMIN_ACCESS_TOKEN
$previousEnvironment['ADMIN_QUESTIONS_DIR'] = $env:ADMIN_QUESTIONS_DIR
# Synthetic preview only; this value is intentionally public, never a real key.
$env:ADMIN_ACCESS_TOKEN = 'local-tests-only-admin-key-0000012345'
Push-Location -LiteralPath $workspacePath
try {
    if (-not $SkipBootstrap) {
        Start-LocalPostgres
        Invoke-LocalChecked $Python @('-m', 'alembic', 'upgrade', 'head')
    }
    Write-Host 'Open http://127.0.0.1:4184'
    Write-Host "Synthetic preview key: $env:ADMIN_ACCESS_TOKEN"
    Write-Host 'Ctrl+C stops the panel. Dev data lives in its own persistent Docker volume; tests do not reset it.'
    Invoke-LocalChecked $Python @('scripts/run_admin_preview.py')
}
finally {
    $devLease.Dispose()
    Restore-LocalEnvironment $previousEnvironment
    Pop-Location
}
