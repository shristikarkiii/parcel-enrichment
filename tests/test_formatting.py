"""Unit tests for the legacy pipeline's pure functions.

No database required. These cover the formatting and resolution rules that
have to agree with Postgres exactly -- rounding mode, NULL handling, sort
order, tie-breaks -- so a divergence shows up here as a named failure rather
than as a mismatched column in the parity run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from legacy_enrichment import (
    build_situs_address,
    concat_ws,
    format_acres,
    format_money,
    resolve_assessment,
    resolve_last_sale,
    resolve_owners,
    resolve_zoning,
    subtract_years,
    summarize_permits,
)


# ---------------------------------------------------------------------------
# concat_ws
# ---------------------------------------------------------------------------


def test_concat_ws_skips_none():
    assert concat_ws(" ", "412", None, "Oak St") == "412 Oak St"


def test_concat_ws_keeps_empty_strings():
    """Postgres concat_ws drops NULL but not ''. Filtering on falsiness would
    collapse these two cases and quietly lose a separator."""
    assert concat_ws(",", "a", "", "b") == "a,,b"


def test_concat_ws_all_none_is_empty_string():
    assert concat_ws(" ", None, None) == ""


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,expected",
    [
        (None, None),
        (Decimal("0.00"), "$0"),
        (Decimal("319000.00"), "$319,000"),
        (Decimal("12450000.00"), "$12,450,000"),
        (Decimal("999.00"), "$999"),
        (Decimal("1000.00"), "$1,000"),
    ],
)
def test_format_money(amount, expected):
    assert format_money(amount) == expected


@pytest.mark.parametrize(
    "amount,expected",
    [
        (Decimal("264500.50"), "$264,501"),   # half away from zero, not to even
        (Decimal("264499.50"), "$264,500"),   # ...which here agrees with half-even
        (Decimal("0.50"), "$1"),
        (Decimal("1.50"), "$2"),
        (Decimal("2.50"), "$3"),              # half-even would give $2
        (Decimal("0.49"), "$0"),
    ],
)
def test_format_money_rounds_half_away_from_zero(amount, expected):
    """to_char(numeric, 'FM$999,999,999,990') rounds half away from zero.

    Python's default is ROUND_HALF_EVEN, which disagrees on 2.50 -> 2. Every
    value ending in exactly .50 is a potential divergence.
    """
    assert format_money(amount) == expected


# ---------------------------------------------------------------------------
# Acreage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sqft,expected",
    [
        (None, None),
        (Decimal("43560.00"), "1.000"),
        (Decimal("130680.00"), "3.000"),
        (Decimal("4356.00"), "0.100"),
        (Decimal("21780.00"), "0.500"),
        (Decimal("7200.00"), "0.165"),
        (Decimal("12000.00"), "0.275"),
        (Decimal("8125.00"), "0.187"),
    ],
)
def test_format_acres(sqft, expected):
    result = format_acres(sqft)
    assert (None if result is None else str(result)) == expected


# ---------------------------------------------------------------------------
# The five-year window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "anchor,years,expected",
    [
        (date(2026, 9, 12), 5, date(2021, 9, 12)),
        (date(2024, 2, 29), 4, date(2020, 2, 29)),   # target year is a leap year
        (date(2024, 2, 29), 1, date(2023, 2, 28)),   # clamped, as Postgres does
        (date(2026, 1, 1), 5, date(2021, 1, 1)),
    ],
)
def test_subtract_years(anchor, years, expected):
    assert subtract_years(anchor, years) == expected


# ---------------------------------------------------------------------------
# Address composition
# ---------------------------------------------------------------------------


def _parcel(**overrides):
    parcel = {
        "house_number": "412",
        "street_name": "Oak St",
        "unit": None,
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62704",
    }
    parcel.update(overrides)
    return parcel


def test_address_plain():
    assert build_situs_address(_parcel()) == "412 Oak St, Springfield, IL 62704"


def test_address_with_unit():
    parcel = _parcel(house_number="608", street_name="Birch Ln", unit="2B")
    assert build_situs_address(parcel) == "608 Birch Ln Unit 2B, Springfield, IL 62704"


def test_address_without_house_number():
    parcel = _parcel(house_number=None, street_name="Birch Ln")
    assert build_situs_address(parcel) == "Birch Ln, Springfield, IL 62704"


def test_address_without_postal_code():
    parcel = _parcel(house_number="513", street_name="Maple Ave", postal_code=None)
    assert build_situs_address(parcel) == "513 Maple Ave, Springfield, IL"


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

OWNERS = {
    1: {"owner_id": 1, "full_name": "Alice Nguyen"},
    2: {"owner_id": 2, "full_name": "Brian Ortega"},
    4: {"owner_id": 4, "full_name": "Dana Whitfield"},
}


def _link(owner_id, end_date=None):
    return {"owner_id": owner_id, "end_date": end_date}


def test_owners_excludes_ended_interests():
    ownership = {7: [_link(1), _link(2), _link(4, date(2019, 4, 12))]}
    assert resolve_owners(7, ownership, OWNERS) == ("Alice Nguyen & Brian Ortega", 2)


def test_owners_sorted_by_code_point():
    """Matches ORDER BY full_name COLLATE "C" in the view."""
    ownership = {7: [_link(4), _link(1), _link(2)]}
    names, count = resolve_owners(7, ownership, OWNERS)
    assert names == "Alice Nguyen & Brian Ortega & Dana Whitfield"
    assert count == 3


def test_owners_none_current():
    ownership = {7: [_link(1, date(2022, 9, 30))]}
    assert resolve_owners(7, ownership, OWNERS) == ("UNKNOWN", 0)


def test_owners_no_rows_at_all():
    assert resolve_owners(7, {}, OWNERS) == ("UNKNOWN", 0)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def _assessment(tax_year, land, improvement, exemption="0.00"):
    return {
        "tax_year": tax_year,
        "land_value": Decimal(land),
        "improvement_value": Decimal(improvement),
        "exemption_amount": Decimal(exemption),
    }


def test_assessment_takes_latest_year_and_nets_exemption():
    rows = {
        7: [
            _assessment(2023, "80000.00", "220000.00"),
            _assessment(2024, "85000.00", "240000.00", "6000.00"),
        ]
    }
    year, total, display = resolve_assessment(7, rows)
    assert (year, str(total), display) == (2024, "319000.00", "$319,000")


def test_assessment_missing_is_not_zero():
    """A parcel with no assessment on file is 'N/A'. Reporting $0 would imply
    the assessor valued it at nothing."""
    assert resolve_assessment(7, {}) == (None, None, "N/A")


def test_assessment_can_legitimately_net_to_zero():
    rows = {7: [_assessment(2023, "40000.00", "0.00", "40000.00")]}
    year, total, display = resolve_assessment(7, rows)
    assert (year, str(total), display) == (2023, "0.00", "$0")


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


def _sale(sale_id, sale_date, price, arms_length=True):
    return {
        "sale_id": sale_id,
        "sale_date": sale_date,
        "sale_price": None if price is None else Decimal(price),
        "is_arms_length": arms_length,
    }


def test_last_sale_ignores_non_arms_length():
    """A $1 quitclaim recorded after the real sale is not market evidence."""
    sales = {
        7: [
            _sale(1, date(2019, 4, 12), "285000.00"),
            _sale(2, date(2023, 11, 3), "1.00", arms_length=False),
        ]
    }
    _, _, display = resolve_last_sale(7, sales)
    assert display == "$285,000 on 2019-04-12"


def test_last_sale_ignores_unpriced_deeds():
    """NULL consideration is not a zero-dollar sale."""
    sales = {
        7: [
            _sale(4, date(2018, 2, 20), "199000.00"),
            _sale(5, date(2022, 9, 30), None),
        ]
    }
    _, _, display = resolve_last_sale(7, sales)
    assert display == "$199,000 on 2018-02-20"


def test_last_sale_ties_break_on_recording_order():
    sales = {
        7: [
            _sale(11, date(2021, 3, 8), "310000.00"),
            _sale(12, date(2021, 3, 8), "315000.00"),
        ]
    }
    _, price, display = resolve_last_sale(7, sales)
    assert str(price) == "315000.00"
    assert display == "$315,000 on 2021-03-08"


def test_last_sale_none():
    assert resolve_last_sale(7, {}) == (None, None, "No recorded sale")


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------

WINDOW_START = date(2021, 9, 12)


def _permit(issued, valuation, status="FINALED"):
    return {
        "issued_date": issued,
        "valuation": None if valuation is None else Decimal(valuation),
        "status": status,
    }


def test_permits_outside_window_are_excluded():
    permits = {
        7: [
            _permit(date(2019, 1, 1), "5000.00"),
            _permit(date(2024, 1, 1), "18000.00"),
        ]
    }
    count, valuation, has_open = summarize_permits(7, permits, WINDOW_START)
    assert (count, str(valuation), has_open) == (1, "18000.00", False)


def test_permit_with_null_valuation_still_counts():
    permits = {
        7: [
            _permit(date(2024, 1, 1), None),
            _permit(date(2024, 6, 1), "4500.00"),
        ]
    }
    count, valuation, has_open = summarize_permits(7, permits, WINDOW_START)
    assert (count, str(valuation), has_open) == (2, "4500.00", False)


@pytest.mark.parametrize(
    "status,expected",
    [("ISSUED", True), ("IN_REVIEW", True), ("FINALED", False), ("EXPIRED", False)],
)
def test_open_permit_statuses(status, expected):
    permits = {7: [_permit(date(2024, 1, 1), "1000.00", status)]}
    assert summarize_permits(7, permits, WINDOW_START)[2] is expected


def test_permits_none():
    count, valuation, has_open = summarize_permits(7, {}, WINDOW_START)
    assert (count, str(valuation), has_open) == (0, "0", False)


# ---------------------------------------------------------------------------
# Zoning
# ---------------------------------------------------------------------------

ZONING = {"R1": {"zoning_code": "R1", "description": "Single-Family Residential"}}


@pytest.mark.parametrize(
    "code,expected",
    [
        ("R1", "Single-Family Residential"),
        ("X9", "Unclassified"),   # code is not in the lookup table
        (None, "Unclassified"),
    ],
)
def test_resolve_zoning(code, expected):
    assert resolve_zoning(code, ZONING) == expected
