"""`python -m mockmart.remediation apply --request <request.json>`: the one fixed remediation command.

Prints the execution manifest as JSON on success (exit 0). A refused request prints `{"error": ...}` and
exits 2 with nothing written to the output directory's world files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mockmart.remediation.rollback import RemediationError, RemediationRequest, apply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mockmart.remediation", description="Apply an approved remediation")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("apply", help="write the treated world described by a request file")
    run.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = RemediationRequest.from_json(json.loads(args.request.read_text()))
        result = apply(request)
    except (RemediationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
