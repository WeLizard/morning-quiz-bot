[CmdletBinding()]
param(
    [string]$DestinationDirectory = "backups/postgres-cutover"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$dataPath = Join-Path $projectRoot "data"
$configPath = Join-Path $projectRoot "config"

if (-not (Test-Path -LiteralPath $dataPath -PathType Container)) {
    throw "Data directory does not exist: $dataPath"
}

$destinationPath = if ([System.IO.Path]::IsPathRooted($DestinationDirectory)) {
    [System.IO.Path]::GetFullPath($DestinationDirectory)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $projectRoot $DestinationDirectory))
}
New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archivePath = Join-Path $destinationPath "morning-quiz-json-$timestamp.zip"
$items = @($dataPath)
if (Test-Path -LiteralPath $configPath -PathType Container) {
    $items += $configPath
}

Compress-Archive -LiteralPath $items -DestinationPath $archivePath -CompressionLevel Optimal

$archive = Get-Item -LiteralPath $archivePath
if ($archive.Length -le 0) {
    throw "Snapshot archive is empty: $archivePath"
}

$hash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
Write-Output "Snapshot: $($archive.FullName)"
Write-Output "Size: $($archive.Length) bytes"
Write-Output "SHA256: $($hash.Hash)"
