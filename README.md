# parcel-enrichment

[![ci](https://github.com/shristikarkiii/parcel-enrichment/actions/workflows/ci.yml/badge.svg)](https://github.com/shristikarkiii/parcel-enrichment/actions/workflows/ci.yml)

Replacing a 601-line Python enrichment pipeline with a 57-line SQL view — and a
test suite that proves the two produce identical output, row for row and field
for field.

```
python/legacy_enrichment.py     601 lines   (459 non-blank)
sql/04_views.sql                 57 lines   county.parcel_profile
```

## The problem

County property data arrives as a polygon table plus seven satellite tables.
Getting a usable parcel record out of it means resolving, per polygon:

| Attribute | Source | The rule that makes it non-trivial |
| --- | --- | --- |
| Owner names | `parcel_owners` × `owners` | Many-to-many **and** historical; only rows with `end_date IS NULL` are current, and multiple owners concatenate in a stable order |
| Assessed value | `assessments` | One row per tax year; take the latest, then net land + improvements − exemptions |
| Last sale | `sales` | Most recent sale that is *arms-length* **and** *priced*; ties on the same day break by recording order |
| Permit activity | `permits` | Rolling five-year window; `NULL` valuations still count as permits but add nothing to the total |
| Flood hazard | `flood_zones` | No join key at all — it is a spatial predicate |
| Zoning label | `zoning_districts` | Parcels reference codes that are not in the lookup table |
| Display strings | everywhere | Currency, addresses and dates formatted for a downstream consumer that matches on exact strings |

The original implementation pulled all seven tables into Python, rebuilt the
relationships in dictionaries, and looped. That file is still here, unchanged,
as `python/legacy_enrichment.py`.

## The replacement

One view. Every rule above, declared once:

```sql
CREATE OR REPLACE VIEW county.parcel_profile AS
SELECT p.parcel_id,
       p.apn,
       concat_ws(', ', concat_ws(' ', p.house_number, p.street_name, 'Unit ' || p.unit),
                       p.city,
                       concat_ws(' ', p.state, p.postal_code))          AS situs_address,
       coalesce(own.owner_names, 'UNKNOWN')                             AS owner_names,
       ...
  FROM county.parcels p
  LEFT JOIN county.zoning_districts z ON z.zoning_code = p.zoning_code
  LEFT JOIN LATERAL (
       SELECT string_agg(o.full_name, ' & ' ORDER BY o.full_name COLLATE "C") AS owner_names,
              count(*)                                                        AS owner_count
         FROM county.parcel_owners po
         JOIN county.owners o USING (owner_id)
        WHERE po.parcel_id = p.parcel_id AND po.end_date IS NULL) own ON true
  ...
```

See [`sql/04_views.sql`](sql/04_views.sql) for the whole thing. Each correlated
`LATERAL` collapses one one-to-many relationship down to the single row that
belongs on the polygon — which is precisely what the Python was doing by
building dicts keyed on `parcel_id` and iterating.

A second view, `county.parcel_profile_geojson`, produces the FeatureCollection
that the script used to write to disk. The deliverable was never a file; it was
a query.

## Why this is faster, not just shorter

The nested-loop spatial join is the clearest case. `resolve_flood_zones()` in
the Python tests every parcel against every flood polygon, because the GiST
index that makes `ST_Intersects` cheap lives in the database and stops existing
the moment the rows are pulled out of it. On a county-wide run of 400k parcels
against 2k flood polygons that is 800 million predicate evaluations. The view
hands the same predicate to the planner, which uses `flood_zones_geom_gix`.

The same argument applies, less dramatically, to the other six joins: the
Python replaces index lookups with full in-memory scans and hash builds, and it
transfers every row of every table over the wire to do it.

## Proving it is safe to delete

`tests/test_parity.py` runs both implementations against the same database at
the same moment and compares all 18 output fields across all 12 parcels — one
test per column, so a failure names the column that broke.

Parity alone is not enough, though: two implementations can agree and both be
wrong. So `test_known_edge_cases` pins the business rules to literal expected
values, independently of either implementation, and `tests/test_formatting.py`
covers the pure functions directly — 52 assertions on rounding mode, `NULL`
handling, sort order and tie-breaks, with no database required. The seed data
exists to make those cases real:

| Parcel | What it pins down |
| --- | --- |
| 1001 | Prior owner excluded; a **$1 quitclaim recorded four years after the real sale** is ignored; a 6.8-year-old permit falls outside the window |
| 1002 | No assessment at all → `N/A`, not `$0` |
| 1003 | Three owners concatenate in order; never sold |
| 1004 | Ownership ended → `UNKNOWN`; a later deed with a `NULL` price is not a sale |
| 1005 | A `NULL`-valuation permit counts toward the count but not the sum |
| 1007 | Exemption cancels the assessment → `$0`; missing postal code drops cleanly out of the address |
| 1008 | `EXPIRED` is not an open permit |
| 1010 | Price of `264500.50` → **`$264,501`**, half away from zero |
| 1011 | `NULL` land area, `NULL` house number, `NULL` zoning; two arms-length sales on the same day |
| 1012 | Zoning code absent from the lookup table; eight-figure currency formatting |

### Three subtleties the test suite caught

1. **Collation.** `string_agg(... ORDER BY o.full_name)` orders by the
   database's collation. Python's `list.sort()` orders by code point. They
   agree under `C` and disagree under `en_US.UTF-8`, so the output silently
   changed depending on which host ran it. The view pins `COLLATE "C"`.

2. **Rounding mode.** `to_char(numeric, 'FM$999,999,999,990')` rounds half away
   from zero; Python's default is banker's rounding. Every value ending in
   exactly `.50` disagreed. The Python now opts into `ROUND_HALF_UP`
   explicitly.

3. **Whose clock.** The five-year permit window was anchored on the client's
   `date.today()` while the view uses the server's `CURRENT_DATE`. Different
   time zones, or a run that straddles midnight, produced different permit
   counts. The legacy script now asks the server.

## Running it

Requires Docker (for PostGIS) and Python 3.9+.

```bash
scripts/reset-db.sh                       # or .\scripts\reset-db.ps1 on Windows
pip install -r python/requirements.txt
pytest
```

The unit tests need neither Docker nor a database, and are worth running first:

```bash
pip install -r python/requirements.txt
pytest tests/test_formatting.py           # 52 passed
```

Without a database the parity tests skip rather than fail, so a bare `pytest`
on a machine with no Postgres reports `52 passed, 31 skipped`.

`reset-db` starts a `postgis/postgis:16-3.4` container and loads
`sql/01_schema.sql` → `02_indexes.sql` → `03_seed.sql` → `04_views.sql` in
order. It is safe to re-run; the schema is dropped and recreated.

To see the two implementations side by side:

```bash
psql postgresql://postgres:postgres@localhost:5432/parcels \
     -c 'SELECT parcel_id, owner_names, assessed_display, last_sale_display, flood_zone
           FROM county.parcel_profile ORDER BY parcel_id'

python python/legacy_enrichment.py --out parcels.geojson
```

CI runs the same thing on every push — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Layout

```
sql/
  01_schema.sql      8 tables; parcels holds the only authoritative geometry
  02_indexes.sql     GiST + the btree indexes each lateral depends on
  03_seed.sql        12 parcels, each chosen to hit a specific branch
  04_views.sql       county.parcel_profile  <- the point of the repository
python/
  legacy_enrichment.py   the 601-line "before", kept verbatim
  requirements.txt
tests/
  conftest.py          real database; no mocking layer, on purpose
  test_formatting.py   pure functions; no database needed
  test_parity.py       18 fields x 12 parcels, plus pinned business rules
scripts/
  reset-db.sh / reset-db.ps1
```

## Caveats

The dataset is synthetic and deliberately small — it is sized to exercise
branches, not to benchmark. The performance claims above are arguments from
algorithmic shape (indexed lookup vs. in-memory nested loop, and rows not sent
over the wire), not measurements from this repository.

One known divergence remains, documented in `format_money()`: Postgres renders
negative currency as `-$5` and the Python as `$-5`. No value in this dataset is
negative, so the two have never disagreed in practice.

## License

MIT — see [LICENSE](LICENSE).
