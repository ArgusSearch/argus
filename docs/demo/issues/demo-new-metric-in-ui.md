# [api] POST /metrics so the "new metric places itself" moment plays in Mission Control

Labels: api, graph, demo · Owner: graph lane (G) · MISSING line in `docs/demo/click-path.md` (beat 3)

The third demo moment (a metric YAML dropped into `metrics/` places itself in the graph with a certificate)
works in the terminal on main:

```bash
uv run python -m argus.graph.classify metrics/roas_by_advertiser.yml --world runs/s1-7/world.duckdb --cards
# new metric -> NEW_DIMENSION roas_by_advertiser ...
#   PROPOSED -> VALID  roas by advertiser_id  children sum off by at most 0.00 % over 672 h
#   PROPOSED -> VALID  roas by country        children sum off by at most 0.00 % over 672 h
```

(1.7 s on the laptop, checked 2026-11-21.) In the web app `POST /metrics` still answers 501, so nothing in the
browser shows the placement. What the page needs: `POST /metrics` with a C2 YAML (or the name of a file in
`metrics/`) that runs the classifier and publishes `graph_changed` plus the `edge_status` events of the new
edges, so the graph and the feed's "Graph" tab show the new node and its certificate without a reload.

Until then the video records beat 3 from the terminal (see the click path).
