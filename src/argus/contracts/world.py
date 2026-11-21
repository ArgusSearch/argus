"""C1 world schema: the tables Argus is allowed to see.

The simulator (lane W) produces these tables; every other lane reads them.
The Python specs below are the single source of truth.
`contracts/schema.sql` is generated from them (`make contracts`).

Rules (frozen, change only with agreement of producer and consumers):

* Raw tables `raw_*` hold micro-batches: the grain columns, additive measures, `batch` and `ingested_at`.
* Argus only queries the views `fact_*`, `log_*` and the table `dim_advertiser`.
  A view shows exactly the rows whose `ingested_at <= getvariable('as_of')`, summed over batches.
  Pinning `as_of` makes every query (and its receipt hash) reproducible even after late data arrives.
* `ts` is the start of the hour, naive UTC.
* Dimension names and values are identical in every table (see `DIMENSIONS`).
* A log row carries `scope`, a JSON object mapping dimension names to lists of values.
  A missing dimension means "all values"; `{}` means global.
* Ground truth lives in a separate database owned by the simulator; Argus never receives a path to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AS_OF_VARIABLE = "as_of"

COUNTRIES: tuple[str, ...] = ("DE", "FR", "UK", "ES", "NL")
PLATFORMS: tuple[str, ...] = ("android", "ios", "web")
CHANNELS: tuple[str, ...] = ("organic", "paid", "email", "direct")
CATEGORIES: tuple[str, ...] = ("electronics", "fashion", "home", "beauty", "toys", "grocery")
PROVIDERS: tuple[str, ...] = ("PayCo", "CardHub", "WalletGo")
ADVERTISERS: tuple[str, ...] = ("adv_01", "adv_02", "adv_03", "adv_04", "adv_05", "adv_06")

DIMENSIONS: dict[str, tuple[str, ...]] = {
    "country": COUNTRIES,
    "platform": PLATFORMS,
    "channel": CHANNELS,
    "category": CATEGORIES,
    "provider": PROVIDERS,
    "advertiser_id": ADVERTISERS,
}

ColumnRole = Literal["time", "grain", "measure", "attr"]


@dataclass(frozen=True)
class Column:
    name: str
    sql_type: str
    role: ColumnRole
    description: str = ""


@dataclass(frozen=True)
class TableSpec:
    """One logical table as Argus sees it (a view over a raw micro-batch table, or a plain table)."""

    name: str
    kind: Literal["fact", "log", "dim"]
    description: str
    columns: tuple[Column, ...]
    batched: bool = True

    @property
    def raw_name(self) -> str:
        if not self.batched:
            return self.name
        return "raw_" + self.name.removeprefix("fact_").removeprefix("log_")

    @property
    def grain(self) -> list[str]:
        """Grain key: one row per distinct value of these columns (needed by the fan-out guard)."""
        return [c.name for c in self.columns if c.role in ("time", "grain")]

    @property
    def dims(self) -> list[str]:
        return [c.name for c in self.columns if c.role == "grain"]

    @property
    def measures(self) -> list[str]:
        return [c.name for c in self.columns if c.role == "measure"]


def _ts() -> Column:
    return Column("ts", "TIMESTAMP", "time", "start of the hour, naive UTC")


def _dim(name: str) -> Column:
    return Column(name, "VARCHAR", "grain", "one of " + ", ".join(DIMENSIONS[name]))


def _count(name: str, description: str) -> Column:
    return Column(name, "BIGINT", "measure", description)


def _amount(name: str, description: str) -> Column:
    # Money is exact: DECIMAL sums are deterministic, parallel DOUBLE sums differ in the last bits per run.
    return Column(name, "DECIMAL(18,2)", "measure", description)


def _log_common() -> tuple[Column, ...]:
    return (
        Column("id", "VARCHAR", "attr", "stable id of the log entry, referenced by findings"),
        Column("ts", "TIMESTAMP", "attr", "when the change happened (minute precision)"),
        Column("kind", "VARCHAR", "attr", "entry kind, see the table description"),
        Column("scope", "JSON", "attr", "affected segments: {dim: [values]}; missing dim = all values"),
        Column("description", "VARCHAR", "attr", "human readable text"),
    )


_INGESTED_AT = Column("ingested_at", "TIMESTAMP", "attr", "when the row became visible")
_BATCH = Column("batch", "INTEGER", "attr", "micro-batch number within the hour (0..3)")

FACT_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "fact_funnel_hourly",
        "fact",
        "Shop traffic funnel per hour and segment.",
        (
            _ts(),
            _dim("country"),
            _dim("platform"),
            _dim("channel"),
            _dim("category"),
            _count("sessions", "sessions that started in the hour"),
            _count("product_views", "sessions that viewed a product"),
            _count("carts", "sessions that added to cart"),
            _count("checkouts", "sessions that started checkout"),
        ),
    ),
    TableSpec(
        "fact_payments_hourly",
        "fact",
        "Payment attempts and successes per hour, segment and payment provider.",
        (
            _ts(),
            _dim("country"),
            _dim("platform"),
            _dim("provider"),
            _count("payment_attempts", "checkouts that attempted a payment"),
            _count("payment_successes", "successful payments (each one is an order)"),
        ),
    ),
    TableSpec(
        "fact_orders_hourly",
        "fact",
        "Orders and gross merchandise value per hour and segment.",
        (
            _ts(),
            _dim("country"),
            _dim("platform"),
            _dim("channel"),
            _dim("category"),
            _count("orders", "orders placed (identity: equals payment_successes)"),
            _amount("gmv", "gross merchandise value in EUR"),
        ),
    ),
    TableSpec(
        "fact_ads_hourly",
        "fact",
        "Advertising delivery per hour, advertiser and segment (the ads business).",
        (
            _ts(),
            _dim("advertiser_id"),
            _dim("country"),
            _dim("platform"),
            _count("ad_impressions", "ads served"),
            _count("ad_clicks", "ad clicks"),
            _amount("ad_spend", "advertiser spend in EUR (what the marketplace earns)"),
            _count("ad_conversions", "orders attributed to an ad click"),
            _amount("attributed_gmv", "GMV of attributed orders in EUR"),
        ),
    ),
    TableSpec(
        "fact_ad_plan_hourly",
        "fact",
        "Pacing plan: planned spend per hour = daily budget x expected share of daily traffic in the hour.",
        (
            _ts(),
            _dim("advertiser_id"),
            _dim("country"),
            _amount("planned_spend", "planned spend in EUR for the hour"),
        ),
    ),
)

LOG_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "log_ingestion",
        "log",
        "Loader log: one row per delivered micro-batch. Completeness of a table-hour = SUM(share).",
        (
            Column("table_name", "VARCHAR", "attr", "fact view name, e.g. fact_orders_hourly"),
            Column("ts", "TIMESTAMP", "attr", "hour the batch belongs to"),
            Column("batch", "INTEGER", "attr", "micro-batch number"),
            Column("share", "DOUBLE", "attr", "fraction of the hour's source events in this batch"),
        ),
    ),
    TableSpec(
        "log_deploys",
        "log",
        "Deploys and releases (kind: deploy | release | config).",
        (
            *_log_common(),
            Column("service", "VARCHAR", "attr", "deployed service or app, e.g. android-app"),
            Column("version", "VARCHAR", "attr", "deployed version, e.g. 8.3.0"),
        ),
    ),
    TableSpec(
        "log_provider_status",
        "log",
        "Status feed of external payment providers (kind: degraded | resolved | maintenance).",
        (*_log_common(), Column("provider", "VARCHAR", "attr", "payment provider")),
    ),
    TableSpec(
        "log_calendar",
        "log",
        "Planned business events (kind: promo | holiday | campaign). `planned_uplift` = {node_id: relative uplift}.",
        (
            *_log_common(),
            Column("end_ts", "TIMESTAMP", "attr", "end of the planned event"),
            Column("planned_uplift", "JSON", "attr", "expected relative change per node id"),
        ),
    ),
    TableSpec(
        "log_ad_budgets",
        "log",
        "Advertiser budget and pacer changes (kind: budget_set | budget_change | pacer_change).",
        (
            *_log_common(),
            Column("advertiser_id", "VARCHAR", "attr", "advertiser"),
            Column("country", "VARCHAR", "attr", "country of the budget line"),
            Column("daily_budget", "DECIMAL(18,2)", "attr", "daily budget in EUR after the change"),
            Column("pacer_version", "VARCHAR", "attr", "pacer version serving this budget line"),
        ),
    ),
)

DIM_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "dim_advertiser",
        "dim",
        "Static advertiser attributes.",
        (
            Column("advertiser_id", "VARCHAR", "attr", "advertiser id"),
            Column("name", "VARCHAR", "attr", "display name (fictional)"),
            Column("vertical", "VARCHAR", "attr", "mobile_games | retail"),
        ),
        batched=False,
    ),
)

ALL_TABLES: tuple[TableSpec, ...] = FACT_TABLES + LOG_TABLES + DIM_TABLES

# Logs whose rows can be evidence for a first cause. All of them share the columns of `_log_common`.
EVIDENCE_LOGS: tuple[str, ...] = ("log_deploys", "log_provider_status", "log_calendar", "log_ad_budgets")


def table(name: str) -> TableSpec:
    for spec in ALL_TABLES:
        if spec.name == name:
            return spec
    raise KeyError(f"unknown table {name!r}")


def raw_columns(spec: TableSpec) -> list[Column]:
    """Columns of the physical table behind a view, in DDL order (used by the simulator to load data)."""
    cols = list(spec.columns)
    if spec.kind == "fact":
        cols += [_BATCH, _INGESTED_AT]
    elif spec.kind == "log":
        cols += [_INGESTED_AT]
    return cols


def render_schema_sql() -> str:
    """Render the DDL that creates raw tables and the `as_of` views (written to contracts/schema.sql)."""
    lines = [
        "-- C1 world schema. GENERATED from src/argus/contracts/world.py by `make contracts`. Do not edit.",
        "-- Argus queries only the views fact_*, log_*, log_events and the table dim_advertiser.",
        f"-- Every view shows rows with ingested_at <= getvariable('{AS_OF_VARIABLE}').",
        "",
    ]
    for spec in ALL_TABLES:
        body = ",\n".join(f"    {c.name} {c.sql_type}" for c in raw_columns(spec))
        lines.append(f"-- {spec.description}")
        lines.append(f"CREATE TABLE {spec.raw_name} (\n{body}\n);")
        if spec.kind == "fact":
            keys = ", ".join(spec.grain)
            sums = ", ".join(
                f"CAST(SUM({c.name}) AS {c.sql_type}) AS {c.name}" for c in spec.columns if c.role == "measure"
            )
            lines.append(
                f"CREATE VIEW {spec.name} AS SELECT {keys}, {sums} FROM {spec.raw_name} "
                f"WHERE ingested_at <= getvariable('{AS_OF_VARIABLE}') GROUP BY {keys};"
            )
        elif spec.kind == "log":
            names = ", ".join(c.name for c in spec.columns)
            lines.append(
                f"CREATE VIEW {spec.name} AS SELECT {names} FROM {spec.raw_name} "
                f"WHERE ingested_at <= getvariable('{AS_OF_VARIABLE}');"
            )
        lines.append("")
    union = "\nUNION ALL\n".join(
        f"SELECT '{name}' AS log, id, ts, kind, scope, description FROM {name}" for name in EVIDENCE_LOGS
    )
    lines.append("-- All evidence logs in one shape, for event lookup by the investigator.")
    lines.append(f"CREATE VIEW log_events AS\n{union};")
    lines.append("")
    return "\n".join(lines)
