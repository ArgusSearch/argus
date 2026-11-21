# S5 Market control

S5 simulates a decline in demand shared by MockMart and an independent peer-market index.
An internal checkout-routing change then reduces payment success for PayCo on Android in Germany while the market decline is still in progress.
Argus records the shared fall in sessions, orders and GMV as `EXPECTED` and opens one incident for the routing fault.

## Run the scenario

```sh
uv run argus-bench case s5 --seed 7 --agents argus
uv run argus-bench run --scenarios s5 --seeds 1,3,7 --agents argus
make demo SCENARIO=s5
```

The default `uv run argus-bench` scorecard includes S5.
The bench seals both injected events before starting Argus and grades each event after revealing the truth.
Use `uv run argus-bench verify runs/bench/s5-7` to independently verify the case commitment.
`make api SCENARIO=s5` replays the checked-in seed 1 recording in `fixtures/s5`.
Use `uv run argus-bench record s5 --seed 7 --out runs/s5-replay` to create a recording of another seed for `uv run argus api --replay runs/s5-replay`.

## Mission Control contract

Subscribe to `GET /events` and listen for `investigation_step`.
Use the C5 event's `payload.anomaly_id` to associate the check with its anomaly.
Read `payload.step.data.market_control` when `payload.step.tool` equals `check_control_group`.
The same payload works in live mode and replay.
The following is an excerpt from the seed 7 sessions event, showing its last evidence point.

```json
{
  "verdict": "market",
  "node": "sessions",
  "segment": {},
  "control": "market_demand_hourly",
  "hour": "2026-11-20T18:00:00",
  "reason": "The metric tracked the market-wide decline within the residual band.",
  "receipt_id": "r174",
  "series": [
    {
      "ts": "2026-11-20T18:00:00",
      "metric_value": 118442.0,
      "metric_expected": 168058.0,
      "control_value": 71.1755370019866,
      "control_expected": 97.83038712267445,
      "metric_change_pct": -29.52314082043104,
      "control_change_pct": -27.24598246479797,
      "adjusted_expected": 122268.94678930983,
      "residual_pct": -3.129941730752217,
      "baseline_weeks": 4
    }
  ]
}
```

| `verdict` | Meaning | Result |
| --- | --- | --- |
| `market` | Both series fell by at least 12% and the metric lies within 8% of the adjusted expectation. | Argus files an `EXPECTED` note. |
| `us` | The metric fell by at least 12% and lies more than 8% below the adjusted expectation. | Argus continues to investigate the local shortfall. |
| `inconclusive` | The available data did not meet either condition. | Argus continues the investigation. |

Plot `metric_change_pct` and `control_change_pct` against `ts` on a common percentage axis.
Plot `residual_pct` against zero to show how much the metric deviated after accounting for market movement.
Percentage fields measure relative change from the corresponding expectation, so `-30` means a 30% decline.
The array contains up to 12 ordered hourly pairs ending at `hour`, with gaps where evidence is unavailable.
An empty segment denotes the whole marketplace.

Fetch the query at `GET /receipts/{receipt_id}` and rerun it with `POST /receipts/{receipt_id}/rerun` when a world is attached.
The expected note appears in `GET /notes` and as a `note` event.
The routing fault appears in the existing `incident_updated` stream and `GET /incidents/{id}` with verdict `SUPPORTED_CAUSE` and evidence `dep_checkout-routing_retry-policy`.
The complete wire event is in [market-step.json](../../tests/market/fixtures/market-step.json).

## Investigator hook

Import `check_control_group` from `argus.market` and call `check_control_group(runner, graph, anomaly, as_of)` after freshness, identity and calendar checks.
The Stage 2 runtime activates the check through `from argus.market.investigator import investigate` in `src/argus/runtime/loop.py`.
The MockMart registry selects `apply_s5` and calls its DuckDB feed writer after the normal C1 tables are written.
The bench registers S5 in the scorecard and accepts it in the `case`, `record` and `run --scenarios` commands.

The producer exposes `market_demand_hourly` as a DuckDB view with `ts TIMESTAMP` and `demand_index DOUBLE`, with one positive index value per hour.
The view exposes each observation once the world's `as_of` reaches its ingestion timestamp.

The control applies to unplanned drops in the additive traffic-sensitive nodes `sessions`, `orders` and `gmv`.
For each hour, the query pairs the metric and outside index for the same hour of the week over the preceding four weeks and requires at least three complete pairs.
It takes each series' median over those matched hours, scales the metric expectation by the control's relative change, and expresses the residual relative to that adjusted expectation.
The check returns `None` for an ineligible anomaly or unavailable current evidence.
Rate anomalies such as payment success follow the existing Stage 2 checks and are investigated independently.
