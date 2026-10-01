param(
    [Parameter(Mandatory=$true)][string]$Backup,
    [Parameter(Mandatory=$true)][ValidateSet("RESTORE-DEIDENTIFIED-EVALUATION-DATABASE")][string]$Confirmation
)
$ErrorActionPreference = "Stop"
$resolved = (Resolve-Path -LiteralPath $Backup).Path
$hashFile = "$resolved.sha256"
if (-not (Test-Path -LiteralPath $hashFile -PathType Leaf)) { throw "Missing checksum file: $hashFile" }
$expected = ((Get-Content -LiteralPath $hashFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expected -ne $actual) { throw "Backup checksum mismatch" }

$containerDump = "/tmp/voxura-restore-$([guid]::NewGuid().ToString('N')).dump"
try {
    docker compose --env-file ops/.env -f ops/compose.yaml cp $resolved "database:$containerDump"
    if ($LASTEXITCODE -ne 0) { throw "Copying the restore input failed with exit code $LASTEXITCODE" }

    docker compose --env-file ops/.env -f ops/compose.yaml exec -T database sh -c "pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --username=`"`$POSTGRES_USER`" --dbname=`"`$POSTGRES_DB`" '$containerDump'"
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }
}
finally {
    docker compose --env-file ops/.env -f ops/compose.yaml exec -T database rm -f $containerDump | Out-Null
}
Write-Host "Restore completed. Run readiness and evaluation smoke tests before reopening access."
