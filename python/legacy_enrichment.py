#!/usr/bin/env python3
"""Legacy parcel enrichment pipeline.

This is the "before" half of this repository. It pulls every supporting table
out of Postgres, rebuilds the relationships in memory, formats the results for
display, staples them onto the parcel polygons, and writes a GeoJSON
FeatureCollection.

It works. It has also been the single most expensive file in the codebase to
change, because every business rule below is expressed as control flow rather
than as a declaration:

  * the join keys live in seven different index-building helpers
  * "most recent assessment" and "most recent arms-length sale" are two
    separate hand-written argmax loops with two separate tie-break rules
  * the five-year permit window is recomputed by hand because Python has no
    native equivalent of INTERVAL '5 years'
  * currency formatting has to opt out of Python's default rounding mode to
    agree with the database
  * the spatial join is an O(parcels x zones) nested loop in Shapely

sql/04_views.sql expresses all of it as county.parcel_profile. The two are
kept honest by tests/test_parity.py, which runs both and asserts that every
field of every row matches exactly.

Usage:
    python python/legacy_enrichment.py --out parcels.geojson
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, getcontext

import psycopg2
import psycopg2.extras
from shapely import wkb as shapely_wkb


# Postgres evaluates numeric division at well over 20 significant digits before
# rounding. Python's default context is 28, which is enough to agree with it,
# but pin it explicitly so a caller who has narrowed the context elsewhere in
# the process cannot silently change our acreage figures.
getcontext().prec = 40

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/parcels"

SQUARE_FEET_PER_ACRE = Decimal("43560.0")

# Permit statuses that mean "work is still live on this parcel".
OPEN_PERMIT_STATUSES = ("ISSUED", "IN_REVIEW")

PERMIT_WINDOW_YEARS = 5

# Placeholders. These strings are load-bearing -- downstream consumers match on
# them -- so they are defined once here and once in the view.
UNKNOWN_OWNER = "UNKNOWN"
UNKNOWN_ZONING = "Unclassified"
NO_SALE = "No recorded sale"
NO_ASSESSMENT = "N/A"
DEFAULT_FLOOD_ZONE = "X"


# ---------------------------------------------------------------------------
# Connection and raw loading
# ---------------------------------------------------------------------------


def get_connection(dsn=None):
    """Open a connection, preferring an explicit DSN, then $DATABASE_URL."""
    resolved = dsn or os.environ.get("DATABASE_URL") or DEFAULT_DSN
    return psycopg2.connect(resolved)


def fetch_all(conn, sql, params=None):
    """Run a query and return a list of plain dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_current_date(conn):
    """Ask the server for its current date.

    The five-year permit window has to be anchored somewhere. Using the
    client's clock means the pipeline and the database disagree whenever they
    sit in different time zones, or whenever a run straddles midnight. Ask the
    server, which is what CURRENT_DATE in the view resolves against.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT CURRENT_DATE")
        return cur.fetchone()[0]


def load_parcels(conn):
    return fetch_all(
        conn,
        """
        SELECT parcel_id, apn, house_number, street_name, unit, city, state,
               postal_code, zoning_code, land_area_sqft, ST_AsBinary(geom) AS geom_wkb
          FROM county.parcels
         ORDER BY parcel_id
        """,
    )


def load_owners(conn):
    return fetch_all(conn, "SELECT owner_id, full_name, owner_type FROM county.owners")


def load_parcel_owners(conn):
    return fetch_all(
        conn,
        """
        SELECT parcel_id, owner_id, ownership_pct, start_date, end_date
          FROM county.parcel_owners
        """,
    )


def load_assessments(conn):
    return fetch_all(
        conn,
        """
        SELECT parcel_id, tax_year, land_value, improvement_value, exemption_amount
          FROM county.assessments
        """,
    )


def load_sales(conn):
    return fetch_all(
        conn,
        """
        SELECT sale_id, parcel_id, sale_date, sale_price, deed_type, is_arms_length
          FROM county.sales
        """,
    )


def load_permits(conn):
    return fetch_all(
        conn,
        """
        SELECT permit_id, parcel_id, issued_date, permit_type, valuation, status
          FROM county.permits
        """,
    )


def load_zoning_districts(conn):
    return fetch_all(
        conn,
        "SELECT zoning_code, description, is_residential FROM county.zoning_districts",
    )


def load_flood_zones(conn):
    return fetch_all(
        conn,
        """
        SELECT flood_zone_id, fema_zone, is_sfha, ST_AsBinary(geom) AS geom_wkb
          FROM county.flood_zones
        """,
    )


# ---------------------------------------------------------------------------
# In-memory index building
#
# Each of these reimplements a join that the database already knows how to do.
# ---------------------------------------------------------------------------


def index_by(rows, key):
    """Build a dict keyed on a unique column."""
    out = {}
    for row in rows:
        out[row[key]] = row
    return out


def group_by(rows, key):
    """Build a dict of lists keyed on a non-unique column."""
    out = defaultdict(list)
    for row in rows:
        out[row[key]].append(row)
    return out


def parse_geometries(rows, field="geom_wkb"):
    """Decode WKB into Shapely geometries, in place."""
    for row in rows:
        raw = row.pop(field)
        if raw is None:
            row["geometry"] = None
        else:
            row["geometry"] = shapely_wkb.loads(bytes(raw))
    return rows


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def concat_ws(separator, *parts):
    """Mirror Postgres concat_ws().

    The subtlety that cost an afternoon: concat_ws skips NULL arguments but
    keeps empty strings. Filtering on falsiness instead of on None produces
    different output for a parcel whose house number is an empty string rather
    than NULL, and the difference only shows up on a handful of rows.
    """
    return separator.join(part for part in parts if part is not None)


def format_money(amount):
    """Format a Decimal as $1,234,567, or None for a missing value.

    Rounds half away from zero to match to_char(numeric, 'FM$999,999,999,990').
    Python's default rounding is ROUND_HALF_EVEN, which disagrees with the
    database on every value ending in exactly .50 -- see parcel 1010.

    Known divergence: Postgres renders negatives as -$5 while this renders
    them as $-5. No assessment or sale price in this dataset is negative, so
    the two have never disagreed in practice.
    """
    if amount is None:
        return None
    whole = Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return "${:,}".format(whole)


def format_acres(land_area_sqft):
    """Convert square feet to acres, rounded to three places."""
    if land_area_sqft is None:
        return None
    acres = Decimal(land_area_sqft) / SQUARE_FEET_PER_ACRE
    return acres.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def format_iso_date(value):
    if value is None:
        return None
    return value.isoformat()


def subtract_years(anchor, years):
    """Subtract whole years from a date, clamping 29 February to the 28th.

    Postgres does this for free with CURRENT_DATE - INTERVAL '5 years'.
    """
    try:
        return anchor.replace(year=anchor.year - years)
    except ValueError:
        # 29 February in a non-leap target year.
        return anchor.replace(year=anchor.year - years, day=28)


# ---------------------------------------------------------------------------
# Per-parcel resolution
#
# One function per attribute group. Each one takes the pre-indexed lookups and
# returns the handful of fields that belong on the polygon.
# ---------------------------------------------------------------------------


def build_situs_address(parcel):
    """Compose a single-line address out of five nullable columns."""
    unit = parcel["unit"]
    unit_part = ("Unit " + unit) if unit is not None else None

    street_line = concat_ws(
        " ", parcel["house_number"], parcel["street_name"], unit_part
    )
    region_line = concat_ws(" ", parcel["state"], parcel["postal_code"])

    return concat_ws(", ", street_line, parcel["city"], region_line)


def resolve_owners(parcel_id, ownership_by_parcel, owners_by_id):
    """Collapse current ownership down to one display string and a count.

    Ownership is many-to-many and historical. A row is current when its
    end_date is NULL; anything with an end_date has been superseded by a
    transfer and must not appear, even though it is still on file.

    Sorting is plain Python string comparison, which orders by code point.
    That matches ORDER BY ... COLLATE "C" in the view. It does NOT match the
    database's default collation on a host configured for, say, en_US.UTF-8,
    which is why the view pins the collation explicitly.
    """
    current = [
        link
        for link in ownership_by_parcel.get(parcel_id, [])
        if link["end_date"] is None
    ]

    names = []
    for link in current:
        owner = owners_by_id.get(link["owner_id"])
        if owner is None:
            # Referential integrity says this cannot happen. It happened.
            continue
        names.append(owner["full_name"])

    names.sort()

    if not names:
        return UNKNOWN_OWNER, 0
    return " & ".join(names), len(names)


def resolve_assessment(parcel_id, assessments_by_parcel):
    """Pick the most recent tax year and net the three value columns.

    Returns (tax_year, total, display).
    """
    rows = assessments_by_parcel.get(parcel_id, [])
    if not rows:
        return None, None, NO_ASSESSMENT

    latest = rows[0]
    for row in rows[1:]:
        if row["tax_year"] > latest["tax_year"]:
            latest = row

    total = (
        latest["land_value"]
        + latest["improvement_value"]
        - latest["exemption_amount"]
    )

    return latest["tax_year"], total, format_money(total)


def resolve_last_sale(parcel_id, sales_by_parcel):
    """Pick the most recent arms-length sale that actually carries a price.

    Two filters that are easy to forget and expensive to get wrong:

      * non-arms-length transfers (quitclaims, intra-family deeds) are not
        market evidence. Parcel 1001 has a $1 quitclaim recorded four years
        after its real sale; reporting it would understate the parcel by
        $285,000.
      * some recorded deeds carry no consideration at all. A NULL price is not
        a zero price.

    Ties on sale_date are broken by the higher sale_id, which is the recording
    order. The view spells the same rule as ORDER BY sale_date DESC,
    sale_id DESC.
    """
    candidates = [
        sale
        for sale in sales_by_parcel.get(parcel_id, [])
        if sale["is_arms_length"] and sale["sale_price"] is not None
    ]

    if not candidates:
        return None, None, NO_SALE

    best = candidates[0]
    for sale in candidates[1:]:
        if (sale["sale_date"], sale["sale_id"]) > (best["sale_date"], best["sale_id"]):
            best = sale

    display = "{} on {}".format(
        format_money(best["sale_price"]), best["sale_date"].isoformat()
    )
    return best["sale_date"], best["sale_price"], display


def summarize_permits(parcel_id, permits_by_parcel, window_start):
    """Count permits in the window, sum their valuations, flag open work.

    Returns (count, valuation, has_open).

    A permit with a NULL valuation still counts toward the count -- it is a
    real permit -- but contributes nothing to the sum. Treating NULL as zero
    and treating it as "skip" give the same total; treating NULL as a reason to
    drop the row gives the wrong count. Parcel 1005 pins this down.
    """
    count = 0
    valuation = Decimal(0)
    has_open = False

    for permit in permits_by_parcel.get(parcel_id, []):
        if permit["issued_date"] < window_start:
            continue

        count += 1

        if permit["valuation"] is not None:
            valuation += permit["valuation"]

        if permit["status"] in OPEN_PERMIT_STATUSES:
            has_open = True

    return count, valuation, has_open


def resolve_flood_zones(parcel_geometry, flood_zones):
    """Nested-loop spatial join against the FEMA layer.

    Returns (zone_label, in_sfha).

    This is the part that does not scale. Every parcel is tested against every
    flood polygon because there is no index to consult -- the GiST index that
    makes ST_Intersects cheap is back in the database, and the moment the rows
    are pulled into Python it stops existing. A county-wide run of 400k
    parcels against 2k flood polygons is 800 million predicate evaluations.
    """
    matched = []
    in_sfha = False

    for zone in flood_zones:
        zone_geometry = zone["geometry"]
        if zone_geometry is None:
            continue
        if parcel_geometry.intersects(zone_geometry):
            matched.append(zone["fema_zone"])
            if zone["is_sfha"]:
                in_sfha = True

    if not matched:
        # No mapped hazard area. FEMA calls that zone X.
        return DEFAULT_FLOOD_ZONE, False

    distinct = sorted(set(matched))
    return ",".join(distinct), in_sfha


def resolve_zoning(zoning_code, zoning_by_code):
    """Look up a zoning description, tolerating codes missing from the table."""
    if zoning_code is None:
        return UNKNOWN_ZONING
    district = zoning_by_code.get(zoning_code)
    if district is None:
        return UNKNOWN_ZONING
    return district["description"]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def enrich_parcels(conn):
    """Build one enriched record per parcel, ordered by parcel_id.

    The field names and values here are contractually identical to the columns
    of county.parcel_profile. tests/test_parity.py asserts it.
    """
    today = fetch_current_date(conn)
    window_start = subtract_years(today, PERMIT_WINDOW_YEARS)

    parcels = parse_geometries(load_parcels(conn))
    flood_zones = parse_geometries(load_flood_zones(conn))

    owners_by_id = index_by(load_owners(conn), "owner_id")
    zoning_by_code = index_by(load_zoning_districts(conn), "zoning_code")

    ownership_by_parcel = group_by(load_parcel_owners(conn), "parcel_id")
    assessments_by_parcel = group_by(load_assessments(conn), "parcel_id")
    sales_by_parcel = group_by(load_sales(conn), "parcel_id")
    permits_by_parcel = group_by(load_permits(conn), "parcel_id")

    records = []

    for parcel in parcels:
        parcel_id = parcel["parcel_id"]

        owner_names, owner_count = resolve_owners(
            parcel_id, ownership_by_parcel, owners_by_id
        )

        assessed_year, assessed_total, assessed_display = resolve_assessment(
            parcel_id, assessments_by_parcel
        )

        last_sale_date, last_sale_price, last_sale_display = resolve_last_sale(
            parcel_id, sales_by_parcel
        )

        permit_count, permit_valuation, has_open_permit = summarize_permits(
            parcel_id, permits_by_parcel, window_start
        )

        flood_zone, in_sfha = resolve_flood_zones(parcel["geometry"], flood_zones)

        records.append(
            {
                "parcel_id": parcel_id,
                "apn": parcel["apn"],
                "situs_address": build_situs_address(parcel),
                "owner_names": owner_names,
                "owner_count": owner_count,
                "zoning_code": parcel["zoning_code"],
                "zoning_description": resolve_zoning(
                    parcel["zoning_code"], zoning_by_code
                ),
                "land_area_acres": format_acres(parcel["land_area_sqft"]),
                "assessed_year": assessed_year,
                "assessed_total": assessed_total,
                "assessed_display": assessed_display,
                "last_sale_date": last_sale_date,
                "last_sale_price": last_sale_price,
                "last_sale_display": last_sale_display,
                "permits_5yr_count": permit_count,
                "permits_5yr_valuation": permit_valuation,
                "has_open_permit": has_open_permit,
                "flood_zone": flood_zone,
                "in_sfha": in_sfha,
                "_geometry": parcel["geometry"],
            }
        )

    records.sort(key=lambda record: record["parcel_id"])
    return records


# ---------------------------------------------------------------------------
# GeoJSON output
# ---------------------------------------------------------------------------


def jsonify(value):
    """Coerce Decimals and dates into something json.dumps will accept."""
    if isinstance(value, Decimal):
        # GeoJSON consumers downstream expect numbers, not strings.
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def to_feature(record):
    properties = {
        key: jsonify(value)
        for key, value in record.items()
        if key not in ("_geometry", "parcel_id")
    }
    return {
        "type": "Feature",
        "id": record["parcel_id"],
        "geometry": json.loads(
            json.dumps(record["_geometry"].__geo_interface__, default=jsonify)
        ),
        "properties": properties,
    }


def to_feature_collection(records):
    return {
        "type": "FeatureCollection",
        "features": [to_feature(record) for record in records],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN. Defaults to $DATABASE_URL, then localhost.",
    )
    parser.add_argument(
        "--out",
        default="-",
        help="Output path for the GeoJSON FeatureCollection, or - for stdout.",
    )
    args = parser.parse_args(argv)

    conn = get_connection(args.dsn)
    try:
        records = enrich_parcels(conn)
    finally:
        conn.close()

    payload = json.dumps(to_feature_collection(records), indent=2, sort_keys=True)

    if args.out == "-":
        sys.stdout.write(payload + "\n")
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        sys.stderr.write(
            "wrote {} features to {}\n".format(len(records), args.out)
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
