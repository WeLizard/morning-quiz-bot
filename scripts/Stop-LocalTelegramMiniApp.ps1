# Stops only this workspace's temporary Mini App exposure. Does not stop the bot or PG.
[CmdletBinding(SupportsShouldProcess)]
param()
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$workspacePath = Get-LocalWorkspace
$tunnelBinary = Join-Path $workspacePath '.local\tools\cloudflared-2026.8.2\cloudflared.exe'
$miniScript = Join-Path $workspacePath 'scripts\run_telegram_mini_app.py'
$pythonPath = Resolve-LocalPython ''
$basePythonPath = (& $pythonPath -I -c 'import sys; print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify the local Python runtime.' }

# Resolve and verify all targets before stopping any. Never stop a process merely
# because it holds a port; another application may legitimately own that port.
$targets = @()
foreach ($port in @(4190, 4187)) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    foreach ($processId in @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        if (-not $processId) { continue }
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
        if (-not $candidate) { continue }
        if ($port -eq 4190) {
            $identityMatches = ($candidate.ExecutablePath -eq $tunnelBinary -and
                $candidate.CommandLine -match '--url\s+http://127\.0\.0\.1:4187(?:\s|$)' -and
                $candidate.CommandLine -match '--metrics\s+127\.0\.0\.1:4190(?:\s|$)')
        } else {
            $identityMatches = ($candidate.ExecutablePath -in @($pythonPath, $basePythonPath) -and
                $candidate.CommandLine -match ('^"?' + [regex]::Escape($pythonPath) + '"?\s') -and
                ($candidate.CommandLine.Contains($miniScript) -or
                 $candidate.CommandLine -match '(?:^|\s)scripts[/\\]run_telegram_mini_app\.py(?:\s|$)'))
        }
        if (-not $identityMatches) { throw "Port $port belongs to an unrecognized process; nothing stopped." }
        $targets += $candidate
    }
}
foreach ($target in $targets) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($target.ProcessId)"
    if (-not $current) { continue }
    if ($current.CreationDate -ne $target.CreationDate -or $current.CommandLine -ne $target.CommandLine) {
        throw 'Process identity changed; refusing to stop it.'
    }
    if ($PSCmdlet.ShouldProcess("Mini App process $($target.ProcessId)", 'Stop')) {
        Stop-Process -Id $target.ProcessId -ErrorAction Stop
    }
}
if ($WhatIfPreference) { Write-Host 'Validation only: no processes stopped.'; return }
Write-Host 'Temporary Mini App exposure stopped. Bot, local preview, admin and database were not stopped.'
Write-Host 'To remove the expired Telegram menu, gracefully restart the test bot without -MiniAppUrl.'
