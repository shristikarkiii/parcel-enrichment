"""The view and the legacy pipeline must agree, field for field.

This is the test that made the deletion safe. It runs
python/legacy_enrichment.py and county.parcel_profile against the same
database at the same moment and compares every field of every row.

test_known_edge_cases exists because parity alone is not enough: two
implementations can agree and both be wrong. Those assertions pin the
business rules to literal expected values, independently of either
implementation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from legacy_enrichment import enrich_parcels

VIEW_SQL = """
    SELECT parcel_id, apn, situs_address, owner_names, owner_count,
           zoning_code, zoning_description, land_area_acres, assessed_year,
           assessed_total, assessed_display, last_sale_date, last_sale_price,
           last_sale_display, permits_5yr_count, permits_5yr_valuation,
           has_open_permit, flood_zone, in_sfha
      FROM county.parcel_profile
     ORDER BY parcel_id
"""

# Numeric columns are compared at a fixed scale. Postgres reports
# coalesce(sum(...), 0) over an empty set as a scale-0 numeric and a real sum
# at scale 2; both mean the same amount of money, and neither implementation
# should fail over the representation.
QUANTA = {
    "land_area_acres": Decimal("0.001"),
    "assessed_total": Decimal("0.01"),
    "last_sale_price": Decimal("0.01"),
    "permits_5yr_valuation": Decimal("0.01"),
}

FIELDS = [
    "apn",
    "situs_address",
    "owner_names",
    "owner_count",
    "zoning_code",
    "zoning_description",
    "land_area_acres",
    "assessed_year",
    "assessed_total",
    "assessed_display",
    "last_sale_date",
    "last_sale_price",
    "last_sale_display",
    "permits_5yr_count",
    "permits_5yr_valuation",
    "has_open_permit",
    "flood_zone",
    "in_sfha",
]

EXPECTED_PARCEL_COUNT = 12


def normalize(field, value):
    """Reduce a field to a comparable, printable form."""
    if value is None:
        return None
    if field in QUANTA:
        return str(Decimal(value).quantize(QUANTA[field]))
    if isinstance(value, date):
        return value.isoformat()
    return value


def normalize_row(row):
    return {field: normalize(field, row[field]) for field in FIELDS}


@pytest.fixture(scope="module")
def view_rows(conn):
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(VIEW_SQL)
        return {row["parcel_id"]: normalize_row(row) for row in cur.fetchall()}


@pytest.fixture(scope="module")
def legacy_rows(conn):
    return {
        record["parcel_id"]: normalize_row(record) for record in enrich_parcels(conn)
    }


def test_seed_data_is_loaded(view_rows):
    assert len(view_rows) == EXPECTED_PARCEL_COUNT


def test_same_parcels_on_both_sides(view_rows, legacy_rows):
    assert sorted(view_rows) == sorted(legacy_rows)


@pytest.mark.parametrize("field", FIELDS)
def test_field_matches_for_every_parcel(field, view_rows, legacy_rows):
    """One test per column, so a failure names the column that broke."""
    mismatches = []
    for parcel_id in sorted(view_rows):
        from_view = view_rows[parcel_id][field]
        from_legacy = legacy_rows[parcel_id][field]
        if from_view != from_legacy:
            mismatches.append(
                "  parcel {}: view={!r} legacy={!r}".format(
                    parcel_id, from_view, from_legacy
                )
            )

    assert not mismatches, "{} differs on {} parcel(s):\n{}".format(
        field, len(mismatches), "\n".join(mismatches)
    )


# ---------------------------------------------------------------------------
# Business rules, pinned to literals.
# ---------------------------------------------------------------------------

KNOWN_VALUES = {
    1001: {
        "situs_address": "412 Oak St, Springfield, IL 62704",
        "owner_names": "Alice Nguyen & Brian Ortega",   # prior owner excluded
        "owner_count": 2,
        "land_area_acres": "0.165",
        "assessed_year": 2024,
        "assessed_display": "$319,000",
        "last_sale_display": "$285,000 on 2019-04-12",  # $1 quitclaim ignored
        "permits_5yr_count": 2,                         # 6.8y-old permit excluded
        "permits_5yr_valuation": "143000.00",
        "has_open_permit": False,
        "flood_zone": "AE,VE",
        "in_sfha": True,
    },
    1002: {
        "assessed_year": None,
        "assessed_display": "N/A",
        "has_open_permit": True,
        "flood_zone": "AE",
    },
    1003: {
        "owner_count": 3,
        "owner_names": "Dana Whitfield & Elm Street Trust & Foster Family Trust",
        "last_sale_display": "No recorded sale",
        "permits_5yr_count": 0,
        "permits_5yr_valuation": "0.00",
        "flood_zone": "X",
        "in_sfha": False,
    },
    1004: {
        "owner_names": "UNKNOWN",                       # interest ended
        "owner_count": 0,
        "last_sale_display": "$199,000 on 2018-02-20",  # unpriced 2022 deed ignored
        "permits_5yr_count": 0,
    },
    1005: {
        "permits_5yr_count": 2,                         # NULL valuation still counts
        "permits_5yr_valuation": "4500.00",
    },
    1007: {
        "situs_address": "513 Maple Ave, Springfield, IL",  # no postal code
        "assessed_display": "$0",
        "zoning_description": "Public Facility",
    },
    1008: {
        "has_open_permit": False,                       # EXPIRED is not open
        "permits_5yr_count": 1,
    },
    1010: {
        "situs_address": "608 Birch Ln Unit 2B, Springfield, IL 62704",
        "last_sale_display": "$264,501 on 2022-05-17",  # .50 rounds half up
    },
    1011: {
        "situs_address": "Birch Ln, Springfield, IL 62704",  # no house number
        "land_area_acres": None,
        "zoning_code": None,
        "zoning_description": "Unclassified",
        "last_sale_display": "$315,000 on 2021-03-08",  # tie broken by sale_id
    },
    1012: {
        "zoning_code": "X9",                            # not in the lookup table
        "zoning_description": "Unclassified",
        "assessed_display": "$12,450,000",
        "owner_names": "Brian Ortega & Cedar Ridge Holdings",
        "permits_5yr_count": 2,
        "permits_5yr_valuation": "240000.00",
        "has_open_permit": True,
    },
}


@pytest.mark.parametrize("parcel_id", sorted(KNOWN_VALUES))
def test_known_edge_cases(parcel_id, view_rows):
    row = view_rows[parcel_id]
    for field, expected in KNOWN_VALUES[parcel_id].items():
        assert row[field] == expected, "parcel {} field {}".format(parcel_id, field)


def test_geojson_view_wraps_every_parcel(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT geojson FROM county.parcel_profile_geojson")
        payload = cur.fetchone()[0]

    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == EXPECTED_PARCEL_COUNT

    first = payload["features"][0]
    assert first["id"] == 1001
    assert first["geometry"]["type"] == "MultiPolygon"
    assert first["properties"]["owner_names"] == "Alice Nguyen & Brian Ortega"
    assert "geom" not in first["properties"]
