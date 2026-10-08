param([switch]$StopDatabase)

. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$composeFile = Join-Path $workspacePath 'compose.dev.yml'
Assert-LocalDocker

$telegramId = (& docker compose -p mqb-local-dev -f $composeFile --profile telegram ps -q telegram 2>$null)
if ($telegramId) {
    $stopPath = Join-Path $workspacePath '.local\telegram-test.stop'
    New-Item -ItemType File -Path $stopPath -Force | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $running = (& docker inspect --format '{{.State.Running}}' $telegramId 2>$null)
        if ($running -ne 'true') { break }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
}

$services = @('admin', 'mini-app', 'telegram', 'game-worker')
if ($StopDatabase) { $services += @('postgres') }
Push-Location -LiteralPath $workspacePath
try {
    & docker compose -p mqb-local-dev -f $composeFile --profile telegram stop --timeout 25 @services
    if ($LASTEXITCODE -ne 0) { throw "docker compose stop failed (exit $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

if ($StopDatabase) {
    Write-Host 'Dev applications and PostgreSQL are stopped. The database volume is preserved.'
}
else {
    Write-Host 'Admin, Mini App and Telegram adapter are stopped. PostgreSQL remains available.'
}
