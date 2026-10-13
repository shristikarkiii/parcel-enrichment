-- ---------------------------------------------------------------------------
-- 04_views.sql
--
-- county.parcel_profile is the whole point of this repository. It replaces
-- python/legacy_enrichment.py -- roughly 500 lines of hand-rolled joins,
-- loops and string formatting -- with one view.
--
-- Every attribute below is defined once, in one place, and the planner gets
-- to decide how to fetch it. The laterals are correlated aggregates: each one
-- collapses a one-to-many relationship down to the single row that belongs on
-- the polygon, which is exactly what the Python was doing by building dicts
-- keyed on parcel_id and looping.
--
-- Conventions worth knowing before you edit this:
--   * ORDER BY ... COLLATE "C" on owner names is deliberate. Without it the
--     concatenation order depends on the database's collation, and the output
--     silently changes when the pipeline moves to another host.
--   * to_char(..., 'FM$999,999,999,990') rounds half away from zero. The
--     parity test seeds a price ending in .50 to pin that behaviour down.
--   * The five-year permit window is evaluated against CURRENT_DATE on the
--     server, so callers cannot drift out of agreement with it.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW county.parcel_profile AS
SELECT p.parcel_id,
       p.apn,
       concat_ws(', ', concat_ws(' ', p.house_number, p.street_name, 'Unit ' || p.unit),
                       p.city,
                       concat_ws(' ', p.state, p.postal_code))          AS situs_address,
       coalesce(own.owner_names, 'UNKNOWN')                             AS owner_names,
       own.owner_count,
       p.zoning_code,
       coalesce(z.description, 'Unclassified')                          AS zoning_description,
       round(p.land_area_sqft / 43560.0, 3)                             AS land_area_acres,
       asmt.tax_year                                                    AS assessed_year,
       asmt.assessed_total,
       coalesce(to_char(asmt.assessed_total, 'FM$999,999,999,990'), 'N/A')
                                                                        AS assessed_display,
       sale.sale_date                                                   AS last_sale_date,
       sale.sale_price                                                  AS last_sale_price,
       coalesce(to_char(sale.sale_price, 'FM$999,999,999,990')
                || ' on ' || to_char(sale.sale_date, 'YYYY-MM-DD'),
                'No recorded sale')                                     AS last_sale_display,
       prm.permit_count                                                 AS permits_5yr_count,
       prm.permit_valuation                                             AS permits_5yr_valuation,
       coalesce(prm.has_open, false)                                    AS has_open_permit,
       coalesce(fld.fema_zones, 'X')                                    AS flood_zone,
       coalesce(fld.is_sfha, false)                                     AS in_sfha,
       p.geom
  FROM county.parcels p
  LEFT JOIN county.zoning_districts z ON z.zoning_code = p.zoning_code
  LEFT JOIN LATERAL (
       SELECT string_agg(o.full_name, ' & ' ORDER BY o.full_name COLLATE "C") AS owner_names,
              count(*)                                                        AS owner_count
         FROM county.parcel_owners po
         JOIN county.owners o USING (owner_id)
        WHERE po.parcel_id = p.parcel_id AND po.end_date IS NULL) own ON true
  LEFT JOIN LATERAL (
       SELECT a.tax_year,
              a.land_value + a.improvement_value - a.exemption_amount AS assessed_total
         FROM county.assessments a
        WHERE a.parcel_id = p.parcel_id
        ORDER BY a.tax_year DESC LIMIT 1) asmt ON true
  LEFT JOIN LATERAL (
       SELECT s.sale_date, s.sale_price
         FROM county.sales s
        WHERE s.parcel_id = p.parcel_id AND s.is_arms_length AND s.sale_price IS NOT NULL
        ORDER BY s.sale_date DESC, s.sale_id DESC LIMIT 1) sale ON true
  LEFT JOIN LATERAL (
       SELECT count(*)                                     AS permit_count,
              coalesce(sum(pm.valuation), 0)               AS permit_valuation,
              bool_or(pm.status IN ('ISSUED', 'IN_REVIEW')) AS has_open
         FROM county.permits pm
        WHERE pm.parcel_id = p.parcel_id
          AND pm.issued_date >= CURRENT_DATE - INTERVAL '5 years') prm ON true
  LEFT JOIN LATERAL (
       SELECT string_agg(DISTINCT f.fema_zone, ',' ORDER BY f.fema_zone) AS fema_zones,
              bool_or(f.is_sfha)                                         AS is_sfha
         FROM county.flood_zones f
        WHERE ST_Intersects(f.geom, p.geom)) fld ON true;


-- ---------------------------------------------------------------------------
-- The legacy script's actual deliverable was a GeoJSON file on disk. That is
-- a second view, not a second program.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW county.parcel_profile_geojson AS
SELECT jsonb_build_object(
           'type',     'FeatureCollection',
           'features', coalesce(jsonb_agg(feature ORDER BY parcel_id), '[]'::jsonb)
       ) AS geojson
  FROM (SELECT pp.parcel_id,
               jsonb_build_object(
                   'type',       'Feature',
                   'id',         pp.parcel_id,
                   'geometry',   ST_AsGeoJSON(pp.geom)::jsonb,
                   'properties', to_jsonb(pp) - 'geom' - 'parcel_id'
               ) AS feature
          FROM county.parcel_profile pp) f;
