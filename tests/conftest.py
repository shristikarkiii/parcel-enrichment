"""Shared fixtures.

The suite talks to a real PostGIS database. There is no mocking layer on
purpose: the whole claim being tested is that the database produces the same
answers as the Python, and a fake database cannot support that claim.

Point $DATABASE_URL at a loaded instance, or run `scripts/reset-db.ps1`
(Windows) / `scripts/reset-db.sh` (everything else) to bring one up.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/parcels"


@pytest.fixture(scope="session")
def dsn():
    return os.environ.get("DATABASE_URL", DEFAULT_DSN)


@pytest.fixture(scope="session")
def conn(dsn):
    psycopg2 = pytest.importorskip("psycopg2")
    try:
        connection = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        pytest.skip("no database at {}: {}".format(dsn, exc))
    connection.set_session(readonly=True, autocommit=True)
    yield connection
    connection.close()
