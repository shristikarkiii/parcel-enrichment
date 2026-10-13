# Bring up a PostGIS container and load the schema, indexes, seed and views.
#
#     .\scripts\reset-db.ps1
#
# Safe to re-run: 01_schema.sql drops and recreates the county schema.
$ErrorActionPreference = 'Stop'

Set-Location (Join-Path $PSScriptRoot '..')

docker compose up -d db

Write-Host -NoNewline 'waiting for postgres'
$ready = $false
foreach ($attempt in 1..60) {
    docker compose exec -T db pg_isready -U postgres -d parcels *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; Write-Host ' ready'; break }
    Write-Host -NoNewline '.'
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'postgres did not become ready within 60s' }

foreach ($file in @('sql/01_schema.sql', 'sql/02_indexes.sql', 'sql/03_seed.sql', 'sql/04_views.sql')) {
    Write-Host "==> $file"
    Get-Content $file -Raw | docker compose exec -T db psql -v ON_ERROR_STOP=1 -q -U postgres -d parcels
    if ($LASTEXITCODE -ne 0) { throw "failed loading $file" }
}

Write-Host ''
Write-Host 'Loaded. Try:'
Write-Host "  psql postgresql://postgres:postgres@localhost:5432/parcels -c 'SELECT * FROM county.parcel_profile'"
