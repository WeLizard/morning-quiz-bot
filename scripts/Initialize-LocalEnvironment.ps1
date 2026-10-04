param([string]$BasePython = 'python')
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
Assert-PreviewStopped
$venvPath = Join-Path $workspacePath '.venv-local'
$localPython = Join-Path $venvPath 'Scripts\python.exe'
Push-Location -LiteralPath $workspacePath
try {
    if (-not (Test-Path -LiteralPath $venvPath)) {
        Invoke-LocalChecked $BasePython @('-c', 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"')
        Invoke-LocalChecked $BasePython @('-m', 'venv', $venvPath)
    }
    if (-not (Test-Path -LiteralPath $localPython -PathType Leaf)) {
        throw 'Incomplete .venv-local. Inspect it before recreating; nothing was deleted.'
    }
    Invoke-LocalChecked $localPython @('-m', 'pip', 'install', '-r', 'requirements-local-lock.txt')
    Invoke-LocalChecked $localPython @('-m', 'pip', 'check')
    Invoke-LocalChecked $localPython @('-c', 'import telegram; assert telegram.__version__ == "22.8"; print("Local PTB", telegram.__version__)')
    Write-Host 'Ready. Global Python, databases and Telegram were not modified.'
}
finally { Pop-Location }
