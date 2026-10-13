-- ---------------------------------------------------------------------------
-- 01_schema.sql
--
-- County property data model. Everything hangs off county.parcels, which is
-- the only table with the authoritative polygon geometry. The other tables are
-- the "sorts of tables" that have to be pulled in, reshaped and stapled back
-- onto each polygon: ownership, assessments, sales, permits, zoning lookups,
-- and FEMA flood layers.
--
-- Run against a database with PostGIS available:
--     psql "$DATABASE_URL" -f sql/01_schema.sql
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS postgis;

DROP SCHEMA IF EXISTS county CASCADE;
CREATE SCHEMA county;


-- The polygons. One row per legal parcel of land.
CREATE TABLE county.parcels (
    parcel_id      bigint PRIMARY KEY,
    apn            text NOT NULL UNIQUE,          -- assessor's parcel number
    house_number   text,
    street_name    text,
    unit           text,                          -- NULL for non-condo parcels
    city           text NOT NULL,
    state          char(2) NOT NULL,
    postal_code    text,
    zoning_code    text,                          -- may be NULL or unknown
    land_area_sqft numeric(14,2),                 -- may be NULL for unsurveyed
    geom           geometry(MultiPolygon, 4326) NOT NULL
);


-- Parties that can hold title.
CREATE TABLE county.owners (
    owner_id   bigint PRIMARY KEY,
    full_name  text NOT NULL,
    owner_type text NOT NULL
        CHECK (owner_type IN ('INDIVIDUAL', 'TRUST', 'LLC', 'CORP', 'GOV'))
);


-- Ownership is many-to-many and historical. end_date IS NULL means current.
CREATE TABLE county.parcel_owners (
    parcel_id     bigint NOT NULL REFERENCES county.parcels,
    owner_id      bigint NOT NULL REFERENCES county.owners,
    ownership_pct numeric(6,3) NOT NULL,
    start_date    date NOT NULL,
    end_date      date,
    PRIMARY KEY (parcel_id, owner_id, start_date)
);


-- One row per parcel per tax year. Only the most recent year is reported.
CREATE TABLE county.assessments (
    parcel_id         bigint NOT NULL REFERENCES county.parcels,
    tax_year          int    NOT NULL,
    land_value        numeric(14,2) NOT NULL DEFAULT 0,
    improvement_value numeric(14,2) NOT NULL DEFAULT 0,
    exemption_amount  numeric(14,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (parcel_id, tax_year)
);


-- Recorded transfers. Quitclaims and intra-family transfers are flagged
-- non-arms-length and must not be reported as market sales.
CREATE TABLE county.sales (
    sale_id        bigint PRIMARY KEY,
    parcel_id      bigint NOT NULL REFERENCES county.parcels,
    sale_date      date   NOT NULL,
    sale_price     numeric(14,2),                 -- NULL on unpriced deeds
    deed_type      text,
    is_arms_length boolean NOT NULL DEFAULT true
);


-- Building permits.
CREATE TABLE county.permits (
    permit_id   bigint PRIMARY KEY,
    parcel_id   bigint NOT NULL REFERENCES county.parcels,
    issued_date date   NOT NULL,
    permit_type text   NOT NULL,
    valuation   numeric(14,2),                    -- NULL for no-value permits
    status      text   NOT NULL
        CHECK (status IN ('ISSUED', 'IN_REVIEW', 'FINALED', 'EXPIRED'))
);


-- Zoning code lookup. Parcels may reference a code that is missing here.
CREATE TABLE county.zoning_districts (
    zoning_code    text PRIMARY KEY,
    description    text NOT NULL,
    is_residential boolean NOT NULL
);


-- FEMA flood hazard layer. Overlaps parcels spatially; there is no key to
-- join on, so this one needs a real geometry predicate.
CREATE TABLE county.flood_zones (
    flood_zone_id bigint PRIMARY KEY,
    fema_zone     text    NOT NULL,
    is_sfha       boolean NOT NULL,               -- special flood hazard area
    geom          geometry(MultiPolygon, 4326) NOT NULL
);
