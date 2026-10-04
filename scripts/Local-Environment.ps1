# Shared guards for the non-production local milestone.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-LocalWorkspace {
    $workspacePath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    if ($workspacePath.StartsWith('\\') -or ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($workspacePath))).DriveType -eq 'Network') {
        throw 'Run from a local disk copy, never from the production share.'
    }
    return $workspacePath
}

function Assert-LocalDocker {
    $endpoint = & docker context inspect --format '{{.Endpoints.docker.Host}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is unavailable.' }
    foreach ($candidate in @($endpoint, $env:DOCKER_HOST)) {
        if ($candidate -and $candidate -notmatch '^(npipe:////\./pipe/|unix:///var/run/docker.sock$)') {
            throw 'This workflow allows only local Docker, never SSH/TCP remote engines.'
        }
    }
}

function Resolve-LocalPython([string]$Python) {
    if ($Python) { return $Python }
    $localPython = Join-Path (Get-LocalWorkspace) '.venv-local\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $localPython -PathType Leaf)) {
        throw 'Local Python environment is missing. Run .\scripts\Initialize-LocalEnvironment.ps1 first.'
    }
    return $localPython
}

function Assert-PreviewStopped {
    param([int[]]$Ports = @(4184, 4185, 4186, 4187))
    foreach ($port in $Ports) {
        if ([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object Port -eq $port) {
            throw "Port $port is in use. Stop the local preview with Ctrl+C before running this command."
        }
    }
}

function Invoke-LocalChecked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE)." }
}

function Start-LocalPostgres {
    $workspacePath = Get-LocalWorkspace
    $composeFile = Join-Path $workspacePath 'compose.dev.yml'
    Assert-LocalDocker
    Invoke-LocalChecked docker @(
        'compose', '-p', 'mqb-local-dev', '-f', $composeFile,
        'up', '-d', '--wait', 'postgres'
    )
}

function Reset-LocalTestDatabase {
    Start-LocalPostgres
    $container = 'mqb-local-dev-postgres-1'
    Invoke-LocalChecked docker @(
        'exec', '-i', $container, 'dropdb', '-U', 'mqb_dev',
        '--maintenance-db=postgres', '--force', '--if-exists', 'morning_quiz_test'
    )
    Invoke-LocalChecked docker @(
        'exec', '-i', $container, 'createdb', '-U', 'mqb_dev',
        '--maintenance-db=postgres', 'morning_quiz_test'
    )
}

function Set-LocalTestEnvironment {
    $settings = @{
        DATABASE_URL = 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_test'
        TEST_DATABASE_URL = 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_test'
        STORAGE_BACKEND = 'postgres'; BOT_TOKEN = ''; OPENROUTER_API_KEY = ''; SENTRY_DSN = ''
        MODE = 'testing'; MQB_TEST_DUMP_RESTORE = '1'; PYTHONIOENCODING = 'utf-8'; PTB_TIMEDELTA = '1'
        PYTHON_DOTENV_DISABLED = '1'
        ADMIN_ALLOWED_HOSTS = 'localhost,127.0.0.1,::1'
    }
    $previous = @{}
    foreach ($key in $settings.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
    }
    return $previous
}

function Restore-LocalEnvironment([hashtable]$Previous) {
    foreach ($key in $Previous.Keys) { [Environment]::SetEnvironmentVariable($key, $Previous[$key], 'Process') }
}

function Set-LocalDevEnvironment {
    $previous = Set-LocalTestEnvironment
    $env:DATABASE_URL = 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_dev'
    # Regression fixtures must never accidentally receive the persistent dev DB.
    $env:TEST_DATABASE_URL = ''
    $env:MQB_TEST_DUMP_RESTORE = '0'
    return $previous
}

function Open-LocalDevLease {
    param([switch]$Exclusive)
    $directory = Join-Path (Get-LocalWorkspace) '.local'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $path = Join-Path $directory 'dev-services.lock'
    $share = if ($Exclusive) { [IO.FileShare]::None } else { [IO.FileShare]::ReadWrite }
    return [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, $share)
}
