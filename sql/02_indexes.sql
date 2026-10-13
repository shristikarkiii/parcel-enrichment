-- ---------------------------------------------------------------------------
-- 02_indexes.sql
--
-- Indexes that the parcel_profile view depends on. Without the GiST indexes
-- the flood-zone predicate degrades to a full cross product; without the
-- parcel_id indexes each lateral becomes a sequential scan per parcel.
-- ---------------------------------------------------------------------------

CREATE INDEX parcels_geom_gix       ON county.parcels     USING gist (geom);
CREATE INDEX flood_zones_geom_gix   ON county.flood_zones USING gist (geom);

CREATE INDEX parcel_owners_parcel_ix ON county.parcel_owners (parcel_id)
    WHERE end_date IS NULL;

CREATE INDEX assessments_parcel_year_ix ON county.assessments (parcel_id, tax_year DESC);

CREATE INDEX sales_parcel_date_ix ON county.sales (parcel_id, sale_date DESC)
    WHERE is_arms_length AND sale_price IS NOT NULL;

CREATE INDEX permits_parcel_date_ix ON county.permits (parcel_id, issued_date);
