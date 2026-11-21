-- C1 world schema. GENERATED from src/argus/contracts/world.py by `make contracts`. Do not edit.
-- Argus queries only the views fact_*, log_*, log_events and the table dim_advertiser.
-- Every view shows rows with ingested_at <= getvariable('as_of').

-- Shop traffic funnel per hour and segment.
CREATE TABLE raw_funnel_hourly (
    ts TIMESTAMP,
    country VARCHAR,
    platform VARCHAR,
    channel VARCHAR,
    category VARCHAR,
    sessions BIGINT,
    product_views BIGINT,
    carts BIGINT,
    checkouts BIGINT,
    batch INTEGER,
    ingested_at TIMESTAMP
);
CREATE VIEW fact_funnel_hourly AS SELECT ts, country, platform, channel, category, CAST(SUM(sessions) AS BIGINT) AS sessions, CAST(SUM(product_views) AS BIGINT) AS product_views, CAST(SUM(carts) AS BIGINT) AS carts, CAST(SUM(checkouts) AS BIGINT) AS checkouts FROM raw_funnel_hourly WHERE ingested_at <= getvariable('as_of') GROUP BY ts, country, platform, channel, category;

-- Payment attempts and successes per hour, segment and payment provider.
CREATE TABLE raw_payments_hourly (
    ts TIMESTAMP,
    country VARCHAR,
    platform VARCHAR,
    provider VARCHAR,
    payment_attempts BIGINT,
    payment_successes BIGINT,
    batch INTEGER,
    ingested_at TIMESTAMP
);
CREATE VIEW fact_payments_hourly AS SELECT ts, country, platform, provider, CAST(SUM(payment_attempts) AS BIGINT) AS payment_attempts, CAST(SUM(payment_successes) AS BIGINT) AS payment_successes FROM raw_payments_hourly WHERE ingested_at <= getvariable('as_of') GROUP BY ts, country, platform, provider;

-- Orders and gross merchandise value per hour and segment.
CREATE TABLE raw_orders_hourly (
    ts TIMESTAMP,
    country VARCHAR,
    platform VARCHAR,
    channel VARCHAR,
    category VARCHAR,
    orders BIGINT,
    gmv DECIMAL(18,2),
    batch INTEGER,
    ingested_at TIMESTAMP
);
CREATE VIEW fact_orders_hourly AS SELECT ts, country, platform, channel, category, CAST(SUM(orders) AS BIGINT) AS orders, CAST(SUM(gmv) AS DECIMAL(18,2)) AS gmv FROM raw_orders_hourly WHERE ingested_at <= getvariable('as_of') GROUP BY ts, country, platform, channel, category;

-- Advertising delivery per hour, advertiser and segment (the ads business).
CREATE TABLE raw_ads_hourly (
    ts TIMESTAMP,
    advertiser_id VARCHAR,
    country VARCHAR,
    platform VARCHAR,
    ad_impressions BIGINT,
    ad_clicks BIGINT,
    ad_spend DECIMAL(18,2),
    ad_conversions BIGINT,
    attributed_gmv DECIMAL(18,2),
    batch INTEGER,
    ingested_at TIMESTAMP
);
CREATE VIEW fact_ads_hourly AS SELECT ts, advertiser_id, country, platform, CAST(SUM(ad_impressions) AS BIGINT) AS ad_impressions, CAST(SUM(ad_clicks) AS BIGINT) AS ad_clicks, CAST(SUM(ad_spend) AS DECIMAL(18,2)) AS ad_spend, CAST(SUM(ad_conversions) AS BIGINT) AS ad_conversions, CAST(SUM(attributed_gmv) AS DECIMAL(18,2)) AS attributed_gmv FROM raw_ads_hourly WHERE ingested_at <= getvariable('as_of') GROUP BY ts, advertiser_id, country, platform;

-- Pacing plan: planned spend per hour = daily budget x expected share of daily traffic in the hour.
CREATE TABLE raw_ad_plan_hourly (
    ts TIMESTAMP,
    advertiser_id VARCHAR,
    country VARCHAR,
    planned_spend DECIMAL(18,2),
    batch INTEGER,
    ingested_at TIMESTAMP
);
CREATE VIEW fact_ad_plan_hourly AS SELECT ts, advertiser_id, country, CAST(SUM(planned_spend) AS DECIMAL(18,2)) AS planned_spend FROM raw_ad_plan_hourly WHERE ingested_at <= getvariable('as_of') GROUP BY ts, advertiser_id, country;

-- Loader log: one row per delivered micro-batch. Completeness of a table-hour = SUM(share).
CREATE TABLE raw_ingestion (
    table_name VARCHAR,
    ts TIMESTAMP,
    batch INTEGER,
    share DOUBLE,
    ingested_at TIMESTAMP
);
CREATE VIEW log_ingestion AS SELECT table_name, ts, batch, share FROM raw_ingestion WHERE ingested_at <= getvariable('as_of');

-- Deploys and releases (kind: deploy | release | config).
CREATE TABLE raw_deploys (
    id VARCHAR,
    ts TIMESTAMP,
    kind VARCHAR,
    scope JSON,
    description VARCHAR,
    service VARCHAR,
    version VARCHAR,
    ingested_at TIMESTAMP
);
CREATE VIEW log_deploys AS SELECT id, ts, kind, scope, description, service, version FROM raw_deploys WHERE ingested_at <= getvariable('as_of');

-- Status feed of external payment providers (kind: degraded | resolved | maintenance).
CREATE TABLE raw_provider_status (
    id VARCHAR,
    ts TIMESTAMP,
    kind VARCHAR,
    scope JSON,
    description VARCHAR,
    provider VARCHAR,
    ingested_at TIMESTAMP
);
CREATE VIEW log_provider_status AS SELECT id, ts, kind, scope, description, provider FROM raw_provider_status WHERE ingested_at <= getvariable('as_of');

-- Planned business events (kind: promo | holiday | campaign). `planned_uplift` = {node_id: relative uplift}.
CREATE TABLE raw_calendar (
    id VARCHAR,
    ts TIMESTAMP,
    kind VARCHAR,
    scope JSON,
    description VARCHAR,
    end_ts TIMESTAMP,
    planned_uplift JSON,
    ingested_at TIMESTAMP
);
CREATE VIEW log_calendar AS SELECT id, ts, kind, scope, description, end_ts, planned_uplift FROM raw_calendar WHERE ingested_at <= getvariable('as_of');

-- Advertiser budget and pacer changes (kind: budget_set | budget_change | pacer_change).
CREATE TABLE raw_ad_budgets (
    id VARCHAR,
    ts TIMESTAMP,
    kind VARCHAR,
    scope JSON,
    description VARCHAR,
    advertiser_id VARCHAR,
    country VARCHAR,
    daily_budget DECIMAL(18,2),
    pacer_version VARCHAR,
    ingested_at TIMESTAMP
);
CREATE VIEW log_ad_budgets AS SELECT id, ts, kind, scope, description, advertiser_id, country, daily_budget, pacer_version FROM raw_ad_budgets WHERE ingested_at <= getvariable('as_of');

-- Static advertiser attributes.
CREATE TABLE dim_advertiser (
    advertiser_id VARCHAR,
    name VARCHAR,
    vertical VARCHAR
);

-- All evidence logs in one shape, for event lookup by the investigator.
CREATE VIEW log_events AS
SELECT 'log_deploys' AS log, id, ts, kind, scope, description FROM log_deploys
UNION ALL
SELECT 'log_provider_status' AS log, id, ts, kind, scope, description FROM log_provider_status
UNION ALL
SELECT 'log_calendar' AS log, id, ts, kind, scope, description FROM log_calendar
UNION ALL
SELECT 'log_ad_budgets' AS log, id, ts, kind, scope, description FROM log_ad_budgets;
