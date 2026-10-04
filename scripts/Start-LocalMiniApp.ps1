param([string]$Python = '', [long]$PlayerId = 900000000091, [switch]$SkipBootstrap)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$Python = Resolve-LocalPython $Python
Assert-LocalDocker
Assert-PreviewStopped -Ports @(4185)
$devLease = Open-LocalDevLease
$previousEnvironment = Set-LocalDevEnvironment
foreach ($key in @('MINI_APP_DATABASE_URL', 'MINI_APP_BOT_TOKEN', 'MINI_APP_ORIGIN', 'MINI_APP_OFFLINE', 'MINI_APP_DEV_USER_ID', 'PHOTO_IMAGES_DIR')) {
    $previousEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$env:MINI_APP_DATABASE_URL = $env:DATABASE_URL
# Synthetic signing key; the dedicated dev factory has explicit fixed-user login.
$env:MINI_APP_BOT_TOKEN = '123456:LOCAL_TEST_ONLY_012345678901234567890'
$env:MINI_APP_ORIGIN = 'http://127.0.0.1:4185'
$env:MINI_APP_OFFLINE = '1'
$env:MINI_APP_DEV_USER_ID = "$PlayerId"
# Photo rounds are read-only for the player.  The previous empty preview folder
# made every local photo quiz start without a usable image.
$env:PHOTO_IMAGES_DIR = Join-Path $workspacePath 'data\images'
Push-Location -LiteralPath $workspacePath
try {
    if (-not $SkipBootstrap) {
        Start-LocalPostgres
        Invoke-LocalChecked $Python @('-m', 'alembic', 'upgrade', 'head')
    }
    Invoke-LocalChecked $Python @('-c', 'import asyncio; from scripts.run_admin_preview import seed; asyncio.run(seed())')
    Write-Host 'Mini App: http://127.0.0.1:4185/app (explicit synthetic dev login).'
    Write-Host 'Offline only: no Telegram delivery. Synthetic membership applies only to the fixed demo player/chat.'
    Write-Host 'Database and preview progress are reused, not recreated. Ctrl+C stops this API only.'
    Invoke-LocalChecked $Python @('-m', 'uvicorn', 'web.dev_mini_app:create_dev_app', '--factory', '--host', '127.0.0.1', '--port', '4185', '--no-proxy-headers', '--no-access-log')
}
finally {
    $devLease.Dispose()
    Restore-LocalEnvironment $previousEnvironment
    Pop-Location
}
