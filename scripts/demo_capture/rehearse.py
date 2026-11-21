"""Play a sealed S4 recording twice against the local API and compare the evidence."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import time
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

QUESTION = "Could higher traffic explain the spend?"


def require(condition: object, detail: str) -> None:
    if not condition:
        raise ValueError(detail)


class LocalAPI:
    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        require(parsed.scheme == "http" and not parsed.path.strip("/"), "use the local HTTP API origin")
        host = parsed.hostname
        if host != "localhost" and (host is None or not ipaddress.ip_address(host).is_loopback):
            raise ValueError("rehearsal must run against a loopback server")
        self.connection = http.client.HTTPConnection(host, parsed.port, timeout=12)
        self.operator_headers: dict[str, str] = {}

    def json(
        self, path: str, body: dict[str, Any] | None = None, *, run_id: str | None = None, operator: bool = False
    ) -> Any:
        if run_id is not None:
            path = f"{path}?{urlencode({'run_id': run_id})}"
        method = "GET" if body is None else "POST"
        headers = {"Content-Type": "application/json"}
        if operator:
            headers.update(self.operator_headers)
        self.connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = self.connection.getresponse()
        data = response.read()
        if response.status != 200:
            raise ValueError(f"{method} {path} returned HTTP {response.status}")
        value = json.loads(data)
        if path == "/agent/operator/session":
            cookies: SimpleCookie = SimpleCookie()
            cookies.load(response.getheader("Set-Cookie", ""))
            self.operator_headers = {
                "Cookie": f"argus_operator={cookies['argus_operator'].coded_value}",
                "X-Argus-CSRF": value["csrf_token"],
            }
        return value

    def wait(self, status: str, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = self.json("/demo/state")
            require(state["run_id"] == run_id, "another operator replaced the rehearsal run")
            if state["status"] == status:
                return state
            time.sleep(0.05)
        raise ValueError(f"the demo did not reach {status}")


def receipt_path(link: dict[str, str]) -> str:
    key = "/".join(quote(link[field], safe="") for field in ("run_id", "world_revision", "receipt_id"))
    return f"/agent/receipts/{key}"


def showcase_prefix(api: LocalAPI) -> dict[str, Any]:
    """Play the fault and expected change, then place the graph cases on a fresh stream."""
    chapters = api.json("/demo/showcase")
    require(
        [chapter["id"] for chapter in chapters] == ["fault", "expected_change", "metric_placement", "agent"],
        "unexpected showcase order",
    )
    placement = chapters[2]
    catalog_path = placement["catalog"]
    previous = api.json(catalog_path)["stream"]
    api.json("/replay", {"action": "restart"})
    api.json("/replay", {"action": "pause"})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        catalog = api.json(catalog_path)
        if catalog["stream"] != previous and not catalog["placements"]:
            break
        time.sleep(0.05)
    else:
        raise ValueError("the showcase could not start a fresh graph stream")

    def play(chapter: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        started = api.json("/demo/start", chapter["start"] | {"speed": 100})
        run_id = started["run_id"]
        api.wait("completed", run_id)
        return run_id, api.json("/demo/snapshot", run_id=run_id)

    fault_id, fault = play(chapters[0])
    incidents = fault["incidents"]
    require(len(incidents) == 1 and incidents[0]["verdict"] == "SUPPORTED_CAUSE", "S1 lacks its supported fault")
    root = incidents[0]["findings"]["root"]
    require(root["node"] == "payment_success_rate", "S1 did not find the payment failure")
    fault_receipt = quote(root["change_pct"]["receipt"], safe="")
    fault_hash = api.json(f"/demo/receipts/{fault_receipt}", run_id=fault_id)["result_hash"]

    expected_id, harmless = play(chapters[1])
    notes = [
        event["payload"]
        for event in harmless["events"]
        if event["type"] == "note_logged" and event["payload"]["kind"] == "expected"
    ]
    require(
        not harmless["incidents"] and len(notes) == 1 and notes[0]["segment"].get("country") == "FR",
        "S2 must record the planned FR change with zero incidents",
    )
    note_hashes = [
        api.json(f"/demo/receipts/{quote(receipt, safe='')}", run_id=expected_id)["result_hash"]
        for receipt in notes[0]["receipts"]
    ]
    require(note_hashes, "S2 note lacks evidence")

    definitions = {metric["name"]: metric for metric in catalog["recorded"]}
    certificates = []
    for case in placement["cases"]:
        found = api.json(placement["path"], definitions[case["name"]])
        require(found["placed_as"] == case["placed_as"], f"{case['name']} placement changed")
        if case["show"]:
            require(found["certificate"]["receipts"], f"{case['name']} certificate lacks evidence")
            certificates.append(found["certificate"])
    return {
        "fault": incidents[0],
        "fault_hash": fault_hash,
        "expected": notes[0],
        "note_hashes": note_hashes,
        "certificates": certificates,
    }


def cold_run(api: LocalAPI, hold: float) -> tuple[str, dict[str, Any]]:
    start = api.json("/demo/start", {"scenario": "s4", "variant": "agent", "speed": 100})
    run_id = start["run_id"]
    require(start.get("variant") == "agent" and run_id, "server did not start an agent presentation")
    held = api.wait("awaiting_approval", run_id)
    proposals = api.json("/agent/actions", run_id=run_id)
    require(len(proposals) == 1 and proposals[0]["state"] == "AWAIT_OPERATOR", "expected one pending rollback")
    proposal = proposals[0]
    feed = api.json("/agent/activity", run_id=run_id)
    require(feed["mode"] == "replay", "the agent feed is outside recorded playback")
    pending_activity = feed["records"]
    require(
        not any(
            record["kind"] in {"action_decided", "action_applied", "effect_checked"} for record in pending_activity
        ),
        "post-approval activity appeared during the hold",
    )
    question = {"question": QUESTION, "incident_id": proposal["incident_ref"]}
    answer = api.json("/agent/ask", question, run_id=run_id)
    require(answer["receipt_links"], "recorded Ask response has no evidence")
    if thread := answer.get("conversation_id"):
        require(thread.startswith(f"{run_id}:"), "Ask conversation is scoped to a different presentation")
        answer["conversation_id"] = thread.split(":", 1)[1]
    asked = [api.json(receipt_path(link), run_id=run_id) for link in answer["receipt_links"]]
    time.sleep(hold)
    require(api.json("/demo/state") == held, "presentation clock moved during the hold")

    action_path = f"/agent/actions/{quote(proposal['id'], safe='')}"
    decision = {"digest": proposal["digest"], "idempotency_key": "offline-rehearsal-approval"}
    api.json("/agent/operator/session", {})
    api.json(f"{action_path}/approve", decision, run_id=run_id, operator=True)
    done = api.wait("completed", run_id)
    action = api.json(action_path, run_id=run_id)
    require(action["state"] == "VERIFIED", "the recorded action did not verify")
    effect = action["effect"]
    require(len(effect["receipt_refs"]) >= 2, "the effect lacks treated and untouched evidence")
    measured = [api.json(receipt_path(link), run_id=run_id) for link in effect["receipt_refs"]]
    require(
        all(proof["verified_at_capture"] for proof in (*asked, *measured)),
        "an evidence receipt was not verified at capture",
    )
    activity = api.json("/agent/activity", run_id=run_id)["records"]
    require(sum(record["kind"] == "action_applied" for record in activity) == 1, "expected one applied action")
    report = api.json("/demo/report/morning", run_id=run_id)
    require(report["through_seq"] == done["through_seq"] > held["through_seq"], "report cutoff is outside the tape")
    return run_id, {
        "ask": answer,
        "ask_hashes": [proof["receipt"]["result_hash"] for proof in asked],
        "effect_hashes": [proof["receipt"]["result_hash"] for proof in measured],
        "action": action,
        "activity": activity,
        "report_cursor": report["through_seq"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--showcase", action="store_true", help="rehearse all four showcase chapters")
    args = parser.parse_args()
    try:
        api = LocalAPI(args.url)
        first_prefix = showcase_prefix(api) if args.showcase else None
        first_id, first = cold_run(api, hold=0.1)
        second_prefix = showcase_prefix(api) if args.showcase else None
        second_id, second = cold_run(api, hold=1.3)
        require(
            first_id != second_id and first == second and first_prefix == second_prefix,
            "cold playbacks produced different evidence",
        )
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        parser.exit(1, f"Offline rehearsal failed. {exc}\n")
    evidence = first if first_prefix is None else {"showcase": first_prefix, "agent": first}
    checksum = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    print(
        json.dumps(
            {
                "cold_runs": 2,
                "evidence_sha256": checksum,
                "ask_receipt_hashes": first["ask_hashes"],
                "effect_receipt_hashes": first["effect_hashes"],
            }
        )
    )


if __name__ == "__main__":
    main()
