"""Metric placement for the Cartographer lives in :mod:`argus.graph.extension`.

``POST /graph/metrics`` accepts a metric definition. Live worlds use the graph
classifier to check the definition, test candidate edges and issue a placement
certificate. Replay worlds serve placements from the recorded metric catalog.
"""
