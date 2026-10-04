param(
    [long]$PlayerId = 900000000091,
    [switch]$WithTelegram,
    [ValidateRange(1, [long]::MaxValue)][long]$ChatId = 621817842,
    [ValidateRange(1, [long]::MaxValue)][long]$ExpectedBotId = 7558542939,
    [ValidateSet('.env', '.env.telegram-test')][string]$TokenFile = '.env'
)

. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$composeFile = Join-Path $workspacePath 'compose.dev.yml'
Assert-LocalDocker

$previous = @{}
foreach ($name in @('MQB_DEV_PLAYER_ID', 'MQB_TELEGRAM_CHAT_ID', 'MQB_TELEGRAM_BOT_ID', 'MQB_TELEGRAM_ENV_FILE')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$env:MQB_DEV_PLAYER_ID = "$PlayerId"
$env:MQB_TELEGRAM_CHAT_ID = "$ChatId"
$env:MQB_TELEGRAM_BOT_ID = "$ExpectedBotId"
$env:MQB_TELEGRAM_ENV_FILE = $TokenFile

Push-Location -LiteralPath $workspacePath
try {
    $arguments = @('compose', '-p', 'mqb-local-dev', '-f', $composeFile)
    if ($WithTelegram) { $arguments += @('--profile', 'telegram') }
    $arguments += @('up', '--build', '-d', '--wait')
    if (-not $WithTelegram) { $arguments += @('postgres', 'migrate', 'seed', 'admin', 'mini-app') }
    Invoke-LocalChecked docker $arguments
    if (-not $WithTelegram) {
        & docker compose -p mqb-local-dev -f $composeFile --profile telegram stop telegram 2>$null | Out-Null
    }

    Write-Host ''
    Write-Host 'Containerized local development is ready:'
    Write-Host '  Admin:     http://127.0.0.1:4184'
    Write-Host '  Admin key: local-tests-only-admin-key-0000012345'
    Write-Host '  Mini App:  http://127.0.0.1:4185/app'
    if ($WithTelegram) { Write-Host "  Telegram:  private test chat $ChatId" }
    Write-Host '  PostgreSQL: one container, 127.0.0.1:55433'
    Write-Host 'Logs: .\scripts\Show-LocalDevelopmentLogs.ps1'
    Write-Host 'Stop: .\scripts\Stop-LocalDevelopment.ps1'
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    Pop-Location
}
