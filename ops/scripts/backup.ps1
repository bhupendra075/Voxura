param(
    [Parameter(Mandatory=$true)][string]$Destination
)
$ErrorActionPreference = "Stop"
$resolved = [System.IO.Path]::GetFullPath($Destination)
$parent = Split-Path -Parent $resolved
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Destination directory does not exist: $parent" }
if (Test-Path -LiteralPath $resolved) { throw "Refusing to overwrite existing backup: $resolved" }

$containerDump = "/tmp/voxura-backup-$([guid]::NewGuid().ToString('N')).dump"
$partial = "$resolved.partial"
try {
    docker compose --env-file ops/.env -f ops/compose.yaml exec -T database sh -c "pg_dump --format=custom --no-owner --no-acl --username=`"`$POSTGRES_USER`" --file='$containerDump' `"`$POSTGRES_DB`""
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }

    docker compose --env-file ops/.env -f ops/compose.yaml cp "database:$containerDump" $partial
    if ($LASTEXITCODE -ne 0) { throw "Copying the database dump failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $partial -PathType Leaf) -or (Get-Item -LiteralPath $partial).Length -eq 0) {
        throw "Backup is empty"
    }
    Move-Item -LiteralPath $partial -Destination $resolved
}
finally {
    docker compose --env-file ops/.env -f ops/compose.yaml exec -T database rm -f $containerDump | Out-Null
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
}
$hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$resolved.sha256" -Value "$hash  $([System.IO.Path]::GetFileName($resolved))"
Write-Host "Backup created: $resolved"
Write-Host "SHA-256: $hash"
