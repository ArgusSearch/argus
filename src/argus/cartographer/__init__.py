"""Cartographer (lane G, Stage 2): onboard a new metric from its C2 YAML and place it in the graph.

Pipeline (build plan section 7): parse with sqlglot (`argus.contracts.metric.parse_metric` is the start),
fan-out guard on joins, propose candidate edges (lineage overlap, brute-force arithmetic over related
nodes, optional LLM proposals), check formulas on 28 days of history (median residual < 0.5%),
check dimensions with an extra GROUP BY, lagged-correlation cause tests with BH correction, then
register the node with a `Certificate` (C3) and append a `GraphChange`.

Demo metrics: roas_by_advertiser (EXACT), gmv_by_seller_type (NEW_DIMENSION), app_crash_rate (AMBIGUOUS).
Entry point the API will call: `POST /metrics` (currently a 501 stub).
"""
