-- ---------------------------------------------------------------------------
-- 03_seed.sql
--
-- Twelve parcels laid out on a 4x3 grid near Springfield, IL. The data is
-- small on purpose but every row is chosen to hit a branch that the legacy
-- Python pipeline had to handle by hand:
--
--   1001  two current owners + one historical owner; non-arms-length sale
--         recorded AFTER the real sale; a permit just outside the 5y window
--   1002  no assessment at all            -> assessed_display 'N/A'
--   1003  three owners; no sales          -> 'No recorded sale'; no permits
--   1004  owner's interest has ended      -> 'UNKNOWN'; unpriced later sale
--   1005  permit with NULL valuation      -> counted but not summed
--   1006  open permit (IN_REVIEW)
--   1007  total assessment nets to zero; NULL postal code
--   1008  expired permit is not "open"
--   1009  two permits, one open
--   1010  price ending in .50            -> half-up rounding; unit number
--   1011  NULL land area; NULL house number; unknown zoning code;
--         two arms-length sales on the SAME day -> tie broken by sale_id
--   1012  zoning code missing from the lookup table; eight-figure values
--
-- Permit dates are relative to CURRENT_DATE so the five-year window stays
-- meaningful no matter when this is loaded.
-- ---------------------------------------------------------------------------

INSERT INTO county.zoning_districts (zoning_code, description, is_residential) VALUES
    ('R1', 'Single-Family Residential', true),
    ('R3', 'Multi-Family Residential',  true),
    ('C2', 'Community Commercial',      false),
    ('I1', 'Light Industrial',          false),
    ('PF', 'Public Facility',           false);


INSERT INTO county.parcels
    (parcel_id, apn, house_number, street_name, unit, city, state, postal_code,
     zoning_code, land_area_sqft, geom)
VALUES
    (1001, '14-22-100-001', '412',  'Oak St',    NULL, 'Springfield', 'IL', '62704', 'R1',   7200.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6600 39.7800, -89.6590 39.7800, -89.6590 39.7810, -89.6600 39.7810, -89.6600 39.7800))', 4326))),
    (1002, '14-22-100-002', '418',  'Oak St',    NULL, 'Springfield', 'IL', '62704', 'R1',   6534.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6588 39.7800, -89.6578 39.7800, -89.6578 39.7810, -89.6588 39.7810, -89.6588 39.7800))', 4326))),
    (1003, '14-22-100-003', '424',  'Oak St',    NULL, 'Springfield', 'IL', '62704', 'C2',  12000.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6576 39.7800, -89.6566 39.7800, -89.6566 39.7810, -89.6576 39.7810, -89.6576 39.7800))', 4326))),
    (1004, '14-22-100-004', '430',  'Oak St',    NULL, 'Springfield', 'IL', '62704', 'R1',   5400.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6564 39.7800, -89.6554 39.7800, -89.6554 39.7810, -89.6564 39.7810, -89.6564 39.7800))', 4326))),
    (1005, '14-22-100-005', '501',  'Maple Ave', NULL, 'Springfield', 'IL', '62704', 'R3',   9800.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6600 39.7812, -89.6590 39.7812, -89.6590 39.7822, -89.6600 39.7822, -89.6600 39.7812))', 4326))),
    (1006, '14-22-100-006', '507',  'Maple Ave', NULL, 'Springfield', 'IL', '62704', 'R1',   4356.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6588 39.7812, -89.6578 39.7812, -89.6578 39.7822, -89.6588 39.7822, -89.6588 39.7812))', 4326))),
    (1007, '14-22-100-007', '513',  'Maple Ave', NULL, 'Springfield', 'IL', NULL,    'PF',  21780.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6576 39.7812, -89.6566 39.7812, -89.6566 39.7822, -89.6576 39.7822, -89.6576 39.7812))', 4326))),
    (1008, '14-22-100-008', '519',  'Maple Ave', NULL, 'Springfield', 'IL', '62704', 'R1',   8125.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6564 39.7812, -89.6554 39.7812, -89.6554 39.7822, -89.6564 39.7822, -89.6564 39.7812))', 4326))),
    (1009, '14-22-100-009', '602',  'Birch Ln',  NULL, 'Springfield', 'IL', '62704', 'R1',  43560.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6600 39.7824, -89.6590 39.7824, -89.6590 39.7834, -89.6600 39.7834, -89.6600 39.7824))', 4326))),
    (1010, '14-22-100-010', '608',  'Birch Ln',  '2B', 'Springfield', 'IL', '62704', 'R1',   6250.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6588 39.7824, -89.6578 39.7824, -89.6578 39.7834, -89.6588 39.7834, -89.6588 39.7824))', 4326))),
    (1011, '14-22-100-011', NULL,   'Birch Ln',  NULL, 'Springfield', 'IL', '62704', NULL,      NULL,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6576 39.7824, -89.6566 39.7824, -89.6566 39.7834, -89.6576 39.7834, -89.6576 39.7824))', 4326))),
    (1012, '14-22-100-012', '620',  'Birch Ln',  NULL, 'Springfield', 'IL', '62704', 'X9', 130680.00,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6564 39.7824, -89.6554 39.7824, -89.6554 39.7834, -89.6564 39.7834, -89.6564 39.7824))', 4326)));


INSERT INTO county.owners (owner_id, full_name, owner_type) VALUES
    ( 1, 'Alice Nguyen',          'INDIVIDUAL'),
    ( 2, 'Brian Ortega',          'INDIVIDUAL'),
    ( 3, 'Cedar Ridge Holdings',  'LLC'),
    ( 4, 'Dana Whitfield',        'INDIVIDUAL'),
    ( 5, 'Elm Street Trust',      'TRUST'),
    ( 6, 'Foster Family Trust',   'TRUST'),
    ( 7, 'Grace Lindqvist',       'INDIVIDUAL'),
    ( 8, 'Harbor Point Corp',     'CORP'),
    ( 9, 'Ivan Petrov',           'INDIVIDUAL'),
    (10, 'City of Springfield',   'GOV'),
    (11, 'Jasmine Okafor',        'INDIVIDUAL'),
    (12, 'Kenji Watanabe',        'INDIVIDUAL'),
    (13, 'Lorena Diaz',           'INDIVIDUAL');


INSERT INTO county.parcel_owners (parcel_id, owner_id, ownership_pct, start_date, end_date) VALUES
    -- 1001: two current owners, plus a prior owner who must be excluded
    (1001,  4, 100.000, DATE '2010-05-01', DATE '2019-04-12'),
    (1001,  1,  50.000, DATE '2019-04-12', NULL),
    (1001,  2,  50.000, DATE '2019-04-12', NULL),
    (1002,  3, 100.000, DATE '2021-06-14', NULL),
    -- 1003: three current owners
    (1003,  4,  33.334, DATE '2016-01-15', NULL),
    (1003,  5,  33.333, DATE '2016-01-15', NULL),
    (1003,  6,  33.333, DATE '2016-01-15', NULL),
    -- 1004: interest ended, nobody current
    (1004,  7, 100.000, DATE '2018-02-20', DATE '2022-09-30'),
    (1005,  8, 100.000, DATE '2024-03-05', NULL),
    (1006,  9, 100.000, DATE '2015-08-19', NULL),
    (1007, 10, 100.000, DATE '1974-07-01', NULL),
    (1008, 11, 100.000, DATE '2023-01-27', NULL),
    (1009, 12, 100.000, DATE '2020-12-01', NULL),
    (1010, 13, 100.000, DATE '2022-05-17', NULL),
    (1011,  1, 100.000, DATE '2021-03-08', NULL),
    (1012,  2,  60.000, DATE '2017-07-04', NULL),
    (1012,  3,  40.000, DATE '2017-07-04', NULL);


INSERT INTO county.assessments (parcel_id, tax_year, land_value, improvement_value, exemption_amount) VALUES
    (1001, 2023,   80000.00,  220000.00,       0.00),
    (1001, 2024,   85000.00,  240000.00,    6000.00),   -- latest year wins
    -- 1002 deliberately has no assessment
    (1003, 2024,  120000.00,       0.00,       0.00),
    (1004, 2022,   60000.00,  140000.00,       0.00),
    (1004, 2024,   70000.00,  150000.00,   10000.00),
    (1005, 2024,   95000.00,  305000.00,       0.00),
    (1006, 2024,   55000.00,       0.00,       0.00),
    (1007, 2023,   40000.00,       0.00,   40000.00),   -- nets to zero
    (1008, 2024,  110000.00,  390000.00,    7500.00),
    (1009, 2024,  250000.00, 1250000.00,       0.00),
    (1010, 2024,   65000.00,  185000.00,    2500.00),
    (1011, 2024,   88000.00,  212000.00,       0.00),
    (1012, 2024, 3200000.00, 9250000.00,       0.00);


INSERT INTO county.sales (sale_id, parcel_id, sale_date, sale_price, deed_type, is_arms_length) VALUES
    ( 1, 1001, DATE '2019-04-12',  285000.00, 'WARRANTY',  true),
    ( 2, 1001, DATE '2023-11-03',       1.00, 'QUITCLAIM', false),  -- newer, must be ignored
    ( 3, 1002, DATE '2021-06-14',  450000.00, 'WARRANTY',  true),
    -- 1003 has never sold
    ( 4, 1004, DATE '2018-02-20',  199000.00, 'WARRANTY',  true),
    ( 5, 1004, DATE '2022-09-30',       NULL, 'DEED',      true),   -- unpriced, must be ignored
    ( 6, 1005, DATE '2024-03-05',  610000.00, 'WARRANTY',  true),
    ( 7, 1006, DATE '2015-08-19',   88000.00, 'WARRANTY',  true),
    -- 1007 is government-owned and has never sold
    ( 8, 1008, DATE '2023-01-27',  525000.00, 'WARRANTY',  true),
    ( 9, 1009, DATE '2020-12-01', 1750000.00, 'WARRANTY',  true),
    (10, 1010, DATE '2022-05-17',  264500.50, 'WARRANTY',  true),   -- rounds half-up to 264,501
    (11, 1011, DATE '2021-03-08',  310000.00, 'WARRANTY',  true),   -- same day as sale 12
    (12, 1011, DATE '2021-03-08',  315000.00, 'WARRANTY',  true),   -- higher sale_id wins
    (13, 1012, DATE '2017-07-04', 8900000.00, 'WARRANTY',  true);


INSERT INTO county.permits (permit_id, parcel_id, issued_date, permit_type, valuation, status) VALUES
    ( 1, 1001, CURRENT_DATE -  120, 'ROOF',       18000.00, 'FINALED'),
    ( 2, 1001, CURRENT_DATE -  900, 'ADDITION',  125000.00, 'FINALED'),
    ( 3, 1001, CURRENT_DATE - 2500, 'DEMO',        5000.00, 'FINALED'),  -- outside 5y window
    ( 4, 1002, CURRENT_DATE -   30, 'SOLAR',      22000.00, 'ISSUED'),
    -- 1003 has no permits
    ( 5, 1004, CURRENT_DATE - 2200, 'REMODEL',    40000.00, 'FINALED'),  -- outside 5y window
    ( 6, 1005, CURRENT_DATE -  400, 'KITCHEN',        NULL, 'FINALED'),  -- counted, not summed
    ( 7, 1005, CURRENT_DATE -   60, 'ELECTRICAL',  4500.00, 'FINALED'),
    ( 8, 1006, CURRENT_DATE -   10, 'NEW_SFR',   350000.00, 'IN_REVIEW'),
    -- 1007 has no permits
    ( 9, 1008, CURRENT_DATE - 1500, 'ADA_RAMP',   12000.00, 'EXPIRED'),  -- expired is not open
    (10, 1009, CURRENT_DATE -  200, 'POOL',       75000.00, 'FINALED'),
    (11, 1009, CURRENT_DATE -    5, 'FENCE',       3000.00, 'ISSUED'),
    -- 1010 has no permits
    (12, 1011, CURRENT_DATE - 1800, 'REROOF',      9000.00, 'FINALED'),
    (13, 1012, CURRENT_DATE -   45, 'TENANT_IMP', 240000.00, 'ISSUED'),
    (14, 1012, CURRENT_DATE -  365, 'SIGNAGE',        NULL, 'FINALED');


-- Flood layers. AE covers the two left columns, VE sits entirely inside 1001,
-- and X clips the right column. Nothing merely touches an edge -- boundary
-- contact is a coin flip between GEOS predicates and hand-rolled Python.
INSERT INTO county.flood_zones (flood_zone_id, fema_zone, is_sfha, geom) VALUES
    (1, 'AE', true,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6605 39.7795, -89.6585 39.7795, -89.6585 39.7845, -89.6605 39.7845, -89.6605 39.7795))', 4326))),
    (2, 'VE', true,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6598 39.7802, -89.6594 39.7802, -89.6594 39.7806, -89.6598 39.7806, -89.6598 39.7802))', 4326))),
    (3, 'X',  false,
     ST_Multi(ST_GeomFromText('POLYGON((-89.6560 39.7795, -89.6548 39.7795, -89.6548 39.7845, -89.6560 39.7845, -89.6560 39.7795))', 4326)));
