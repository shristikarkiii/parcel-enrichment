#!/usr/bin/env bash
# Bring up a PostGIS container and load the schema, indexes, seed and views.
#
#     scripts/reset-db.sh
#
# Safe to re-run: 01_schema.sql drops and recreates the county schema.
set -euo pipefail

cd "$(dirname "$0")/.."

docker compose up -d db

printf 'waiting for postgres'
for _ in $(seq 1 60); do
    if docker compose exec -T db pg_isready -U postgres -d parcels >/dev/null 2>&1; then
        printf ' ready\n'
        break
    fi
    printf '.'
    sleep 1
done

for file in sql/01_schema.sql sql/02_indexes.sql sql/03_seed.sql sql/04_views.sql; do
    echo "==> $file"
    docker compose exec -T db psql -v ON_ERROR_STOP=1 -q -U postgres -d parcels < "$file"
done

echo
echo "Loaded. Try:"
echo "  psql postgresql://postgres:postgres@localhost:5432/parcels -c 'SELECT * FROM county.parcel_profile'"
