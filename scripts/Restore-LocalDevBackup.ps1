param(
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{32}$')][string]$BackupId,
    [Parameter(Mandatory)][ValidateSet('morning_quiz_dev')][string]$ConfirmOverwrite
)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$composeFile = Join-Path $workspacePath 'compose.dev.yml'
Assert-LocalDocker
Assert-PreviewStopped
$lease = Open-LocalDevLease -Exclusive
Push-Location -LiteralPath $workspacePath
try {
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, 'up', '-d', '--wait', 'postgres')
    Invoke-LocalChecked docker @('compose', '-p', 'mqb-local-dev', '-f', $composeFile, 'build', 'migrate')
    Invoke-LocalChecked docker @(
        'compose', '-p', 'mqb-local-dev', '-f', $composeFile,
        'run', '--rm', '--no-deps', '-e', "MQB_DEV_RESTORE_ID=$BackupId", 'migrate',
        'python', '-m', 'storage.dev_backups', 'restore', $BackupId, '--confirm', $ConfirmOverwrite
    )
}
finally {
    $lease.Dispose()
    Pop-Location
}
