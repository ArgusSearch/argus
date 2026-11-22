"""Turn trusted provider schemas and immutable snapshots into graph placements."""

from __future__ import annotations

from collections.abc import Sequence

from argus.connectors.data import METRICS, SOURCE_PREFIX, Snapshot
from argus.contracts.graph import Certificate, Graph, Node, NodeKind
from argus.contracts.metric import MetricDefinition
from argus.graph.classify import Placement
from argus.semantic.compile import render_node_sql
from argus.semantic.runner import Runner


def prepare(snapshot: Snapshot, graph: Graph, runner: Runner) -> Sequence[Placement]:
    """Read everybody's receipt before changing the graph, so a failed read cannot half-place a source."""
    source = f"{SOURCE_PREFIX}{snapshot.provider}"
    metrics = METRICS[snapshot.provider]
    ids = {metric.id for metric in metrics}
    if any(node.id in ids and node.source != source for node in graph.nodes):
        raise ValueError("A provider metric name is already in use.")

    nodes: list[Node] = []
    for metric in metrics:
        description = metric.description
        label = metric.id.replace("_", " ").capitalize()
        if metric.id == "stripe_gross_payments" and snapshot.currency:
            description += f" ({snapshot.currency.upper()})"
            label += f" ({snapshot.currency.upper()} minor units)"
        nodes.append(
            Node(
                id=metric.id,
                label=label,
                description=description,
                kind=NodeKind.RATIO if metric.numerator else NodeKind.ADDITIVE,
                unit=metric.unit,
                dims=[metric.dimension] if metric.dimension else [],
                table=None if metric.numerator else metric.table,
                measure=None if metric.numerator else "amount",
                numerator=metric.numerator,
                denominator=metric.denominator,
                source=source,
            )
        )
    next_graph = graph.model_copy(update={"nodes": [n for n in graph.nodes if n.id not in ids] + nodes})
    results = []
    for node in nodes:
        sql: str | None
        if node.numerator and node.denominator:
            num = next_graph.node(node.numerator)
            den = next_graph.node(node.denominator)
            sql = (
                "SELECT ts, SUM(n.amount)::DOUBLE / NULLIF(SUM(d.amount), 0) AS value "
                f"FROM {num.table} AS n JOIN {den.table} AS d USING (ts) GROUP BY ts"
            )
        else:
            sql = render_node_sql(next_graph, node)
        if sql is None:
            raise ValueError("The provider metric could not be compiled.")
        node.sql = sql
        _, receipt = runner.query(sql, snapshot.synced_at, purpose=f"imported {node.id}")
        summary = f"{node.description} through {snapshot.latest_day.isoformat()}."
        results.append(
            Placement(
                metric=MetricDefinition(name=node.id, description=node.description, sql=sql),
                certificate=Certificate(metric=node.id, placed_as="EXACT", summary=summary, receipts=[receipt.id]),
                graph=next_graph,
                as_of=snapshot.synced_at,
                node=node,
                definition="Daily series from the provider snapshot.",
            )
        )
    return results
