"""The cause chain of a supported incident (docs/ext/agent.md "Board"): a read model, derived from C4 findings only.

    event -> root node in its segment -> formula hop of the LMDI walk -> EUR impact, plus silenced symptoms

Every tested link carries the receipts of the check that established it, qualified with the run that cites
them (`ReceiptLink`). An incident without a supported cause has no chain: nothing here guesses one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from argus.agent.types import CauseChain, ChainLink, ReceiptLink
from argus.contracts.findings import Findings, Incident, Segment, TrailStep, Verdict

STAGE2_RUN = "stage2"
"""`ReceiptLink.run_id` of receipts cited by an incident no agent run touched (the Stage-2 investigator's own)."""


def segment_text(segment: Segment) -> str:
    return " / ".join(segment.values()) if segment else "all segments"


def node_label(node: str, labels: Mapping[str, str] | None = None) -> str:
    return (labels or {}).get(node) or node.replace("_", " ")


def links(receipts: Iterable[str | None], run_id: str | None, world_revision: str) -> list[ReceiptLink]:
    """Qualify bare C4 receipt ids (deduplicated, in order) with the run that cites them."""
    out: list[ReceiptLink] = []
    for rid in receipts:
        if rid and all(link.receipt_id != rid for link in out):
            out.append(ReceiptLink(run_id=run_id or STAGE2_RUN, world_revision=world_revision, receipt_id=rid))
    return out


def tagged(text: str, receipts: Iterable[str]) -> str:
    """A host-rendered sentence with its receipt tags, the way every number reaches a human."""
    ids = list(dict.fromkeys(r for r in receipts if r))
    return f"{text} [{', '.join(ids)}]" if ids else text


def _event_steps(trail: list[TrailStep], ref: str) -> list[TrailStep]:
    return [
        s
        for s in trail
        if s.tool == "holdout_check" and isinstance(s.data.get("event"), dict) and s.data["event"].get("ref") == ref
    ]


def _outcome(step: TrailStep) -> str | None:
    ledger = step.data.get("ledger")
    return ledger.get("outcome") if isinstance(ledger, dict) else None


def _formula_hops(findings: Findings, root: str) -> Iterable[tuple[str, str, float | None, list[str]]]:
    """Read the chosen LMDI walk backwards, from its last factor to the scored metric."""
    last = root
    for step in reversed(findings.trail):
        data = step.data
        parent = data.get("node")
        if step.tool != "decompose_formula" or data.get("follow") != last or not isinstance(parent, str):
            continue
        children = data.get("children")
        if not isinstance(children, list):
            continue
        factor = next((child for child in children if isinstance(child, dict) and child.get("node") == last), {})
        share = factor.get("share")
        yield last, parent, float(share) if isinstance(share, int | float) else None, step.receipts
        last = parent
    if (parent := findings.decomposed_node) and parent not in (root, last):
        contribution = next((c for c in findings.decomposition if c.node == last), None)
        if contribution is not None:
            yield last, parent, contribution.share, [contribution.receipt] if contribution.receipt else []


def _eur(value: float) -> str:
    return f"EUR {value:+,}".removesuffix(".0")


def chain_of(
    findings: Findings,
    incident_id: str,
    *,
    symptoms: Iterable[str] = (),
    run_id: str | None = None,
    world_revision: str = "factual",
    labels: Mapping[str, str] | None = None,
) -> CauseChain | None:
    root = findings.root
    if findings.verdict is not Verdict.SUPPORTED_CAUSE or root is None or root.evidence is None:
        return None
    event = root.evidence

    def qualify(receipts: Iterable[str | None]) -> list[ReceiptLink]:
        return links(receipts, run_id, world_revision)

    out: list[ChainLink] = []
    consistent = [s for s in _event_steps(findings.trail, event.ref) if _outcome(s) == "consistent"]
    event_receipts = qualify(consistent[-1].receipts if consistent else [])
    out.append(
        ChainLink(
            kind="event",
            source=event.ref,
            target=root.node,
            label=event.description,
            share=None,
            status="tested" if event_receipts else "untested",
            receipts=event_receipts,
        )
    )

    search = next((s for s in findings.trail if s.tool == "segment_search"), None)
    path = search.data.get("path") if search is not None else None
    final_cut = path[-1] if root.segment and isinstance(path, list) and path else None
    ep = final_cut.get("ep") if isinstance(final_cut, dict) else None
    root_receipts = qualify([root.change_pct.receipt, *(search.receipts if search is not None else [])])
    out.append(
        ChainLink(
            kind="root",
            source=root.node,
            target=root.node,
            label=f"{node_label(root.node, labels)} in {segment_text(root.segment)}",
            share=float(ep) if isinstance(ep, int | float) else None,
            status="tested" if root_receipts else "untested",
            receipts=root_receipts,
        )
    )

    last = root.node
    for source, target, share, receipts in _formula_hops(findings, root.node):
        source_label, target_label = node_label(source, labels), node_label(target, labels)
        out.append(
            ChainLink(
                kind="formula",
                source=source,
                target=target,
                label=(
                    tagged(f"{source_label} carries {share:.0%} of the change of {target_label}", receipts)
                    if share is not None and receipts
                    else f"{source_label} feeds {target_label}"
                ),
                share=share,
                status="tested" if receipts else "untested",
                receipts=qualify(receipts),
            )
        )
        last = target

    impact = findings.impact
    if impact is not None:
        if impact.node != last:
            out.append(
                ChainLink(
                    kind="formula",
                    source=last,
                    target=impact.node,
                    label=f"{node_label(last, labels)} feeds {node_label(impact.node, labels)}",
                    share=None,
                    status="untested",
                    receipts=[],
                )
            )
        eur = impact.eur_so_far
        out.append(
            ChainLink(
                kind="impact",
                source=impact.node,
                target="eur",
                label=tagged(
                    f"{_eur(impact.gmv_eur_per_hour.value)} per hour, {_eur(eur.value)} so far",
                    [r for r in (impact.gmv_eur_per_hour.receipt, eur.receipt) if r],
                ),
                share=None,
                status="tested",
                receipts=qualify([impact.gmv_eur_per_hour.receipt, eur.receipt, impact.per_hour.receipt]),
            )
        )

    on_chain = {link.target for link in out} | {root.node}
    for node in symptoms:
        if node not in on_chain:
            on_chain.add(node)
            out.append(
                ChainLink(
                    kind="symptom",
                    source=root.node,
                    target=node,
                    label=f"{node_label(node, labels)}: its alert is silenced as a symptom of this incident",
                    share=None,
                    status="untested",
                    receipts=root_receipts or event_receipts,
                )
            )

    steps = [event.description, f"{node_label(root.node, labels)} in {segment_text(root.segment)}"]
    steps += [node_label(link.target, labels) for link in out if link.kind == "formula"]
    if impact is not None:
        steps.append(f"{_eur(impact.eur_so_far.value)} so far")
    return CauseChain(incident_id=incident_id, links=out, text=" -> ".join(steps))


def build_chain(
    incident: Incident,
    *,
    run_id: str | None = None,
    world_revision: str = "factual",
    labels: Mapping[str, str] | None = None,
) -> CauseChain | None:
    """The chain of one incident, or None when its verdict names no supported cause."""
    return chain_of(
        incident.findings,
        incident.id,
        symptoms=incident.symptoms,
        run_id=run_id,
        world_revision=world_revision,
        labels=labels,
    )
