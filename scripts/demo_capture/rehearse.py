"""Play a sealed S4 recording twice against the local API and compare the evidence."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import time
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

    def json(self, path: str, body: dict[str, Any] | None = None, *, run_id: str | None = None) -> Any:
        if run_id is not None:
            path = f"{path}?{urlencode({'run_id': run_id})}"
        method = "GET" if body is None else "POST"
        self.connection.request(
            method,
            path,
            json.dumps(body) if body is not None else None,
            {
                "Content-Type": "application/json",
            },
        )
        response = self.connection.getresponse()
        data = response.read()
        if response.status != 200:
            raise ValueError(f"{method} {path} returned HTTP {response.status}")
        return json.loads(data)

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
    asked = [api.json(receipt_path(link), run_id=run_id) for link in answer["receipt_links"]]
    time.sleep(hold)
    require(api.json("/demo/state") == held, "presentation clock moved during the hold")

    action_path = f"/agent/actions/{quote(proposal['id'], safe='')}"
    decision = {"digest": proposal["digest"], "idempotency_key": "offline-rehearsal-approval"}
    api.json(f"{action_path}/approve", decision, run_id=run_id)
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
    args = parser.parse_args()
    try:
        api = LocalAPI(args.url)
        first_id, first = cold_run(api, hold=0.1)
        second_id, second = cold_run(api, hold=1.3)
        require(first_id != second_id and first == second, "cold playbacks produced different evidence")
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        parser.exit(1, f"Offline rehearsal failed. {exc}\n")
    checksum = hashlib.sha256(json.dumps(first, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
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
