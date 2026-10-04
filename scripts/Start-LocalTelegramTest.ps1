param(
    [Parameter(Mandatory)][ValidateRange(1, [long]::MaxValue)][long]$ChatId,
    [Parameter(Mandatory)][ValidateRange(1, [long]::MaxValue)][long]$ExpectedBotId,
    [ValidateSet('.env', '.env.telegram-test')][string]$TokenFile = '.env.telegram-test',
    [string]$MiniAppUrl = '',
    [switch]$ShowMenu,
    [string]$Python = ''
)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$Python = Resolve-LocalPython $Python
Assert-LocalDocker
Assert-PreviewStopped -Ports @(4186)
$lease = Open-LocalDevLease
Push-Location -LiteralPath $workspacePath
try {
    Write-Host "Live TEST bot: only private chat $ChatId; local dev database; no automatic schedules."
    Write-Host 'Stop gracefully: .\scripts\Stop-LocalTelegramTest.ps1'
    $runnerArguments = @('scripts/run_telegram_test.py', '--chat-id', "$ChatId", '--expected-bot-id', "$ExpectedBotId", '--token-file', $TokenFile)
    if ($MiniAppUrl) { $runnerArguments += @('--mini-app-url', $MiniAppUrl) }
    if ($ShowMenu) { $runnerArguments += '--show-menu' }
    Invoke-LocalChecked $Python $runnerArguments
}
finally {
    $lease.Dispose()
    Pop-Location
}
