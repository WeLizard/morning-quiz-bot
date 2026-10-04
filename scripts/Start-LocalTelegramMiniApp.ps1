param(
    [Parameter(Mandatory)][long]$UserId,
    [Parameter(Mandatory)][long]$ExpectedBotId,
    [Parameter(Mandatory)][string]$PublicOrigin,
    [ValidateSet('.env', '.env.telegram-test')][string]$TokenFile = '.env.telegram-test',
    [string]$Python = ''
)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$Python = Resolve-LocalPython $Python
Assert-LocalDocker
Assert-PreviewStopped -Ports @(4187)
$lease = Open-LocalDevLease
Push-Location -LiteralPath $workspacePath
try {
    Write-Host "Test Mini App: only Telegram user $UserId, upstream 127.0.0.1:4187."
    Write-Host 'This script does not publish a tunnel. The separately approved HTTPS ingress must target only port 4187.'
    Invoke-LocalChecked $Python @('scripts/run_telegram_mini_app.py', '--user-id', "$UserId", '--expected-bot-id', "$ExpectedBotId", '--token-file', $TokenFile, '--public-origin', $PublicOrigin)
}
finally { $lease.Dispose(); Pop-Location }
