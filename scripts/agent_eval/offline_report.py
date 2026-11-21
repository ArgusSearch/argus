"""Report deterministic agent eval coverage and require every case to pass."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from scripts.agent_eval.bench_gate import SCENARIOS, SEEDS

CASES = {
    "E01": "scenario disposition",
    "E02": "root cause and segment",
    "E03": "S1 holdout refutes the release",
    "E04": "verified numbers and receipt integrity",
    "E05": "predictions before queries",
    "E06": "verdict gate rejects incomplete checks",
    "E07": "fabricated numbers trigger repair and template fallback",
    "E08": "untrusted log and memory instructions",
    "E09": "operator approval",
    "E10": "S4 rollback effect and historical receipts",
    "E11": "budget exhaustion and Stage 2 fallback",
    "E12": "tool allowlist",
    "E13": "cold replay and approval cut",
    "E14": "usage and zero replay spend",
    "E15": "Ask grounding and authority",
    "E16": "same-tick Stage 2 on provider errors",
    "E17": "quiet world with no paid calls",
}
CASE_NAME = re.compile(r"test_(e\d{2})(?:_|\[|$)", re.IGNORECASE)
FIRST_DIFFERENCE = re.compile(r"(?:turn|observation) (\d+)", re.IGNORECASE)
SCENARIO_MATRIX = {
    f"test_e01_disposition_on_sealed_scenarios[{seed}-{scenario}]": (scenario, seed)
    for scenario in SCENARIOS
    for seed in SEEDS
}


def summarize(xml: Path, commit: str) -> dict[str, object]:
    tests: dict[str, list[dict[str, str | int | None]]] = {case: [] for case in CASES}
    try:
        tree = ElementTree.parse(xml)
    except (OSError, ElementTree.ParseError):
        tree = ElementTree.ElementTree(ElementTree.Element("testsuites"))
    for result in tree.iter("testcase"):
        name = result.get("name", "")
        match = CASE_NAME.match(name)
        if match is None or (case := match[1].upper()) not in tests:
            continue
        outcome = "pass"
        diagnostic = None
        for kind in ("error", "failure", "skipped"):
            child = result.find(kind)
            if child is not None:
                outcome = kind
                diagnostic = child.get("message")
                break
        difference = FIRST_DIFFERENCE.search(diagnostic or "")
        tests[case].append(
            {
                "test": name,
                "outcome": outcome,
                "diagnostic": diagnostic,
                "first_bad_turn": int(difference[1]) if difference else None,
            }
        )
    dispositions = {test["test"]: test["outcome"] for test in tests["E01"]}
    matrix = [
        {"scenario": scenario, "seed": seed, "outcome": dispositions.get(name, "missing")}
        for name, (scenario, seed) in SCENARIO_MATRIX.items()
    ]
    matrix_complete = all(run["outcome"] == "pass" for run in matrix)
    cases = [
        {
            "id": case,
            "invariant": invariant,
            "passed": (
                bool(tests[case])
                and all(test["outcome"] == "pass" for test in tests[case])
                and (case != "E01" or matrix_complete)
            ),
            "trials": tests[case],
        }
        for case, invariant in CASES.items()
    ]
    return {
        "commit": commit,
        "cohort": "deterministic_agent",
        "required": len(cases),
        "passed": sum(bool(case["passed"]) for case in cases),
        "junit": str(xml),
        "scenario_matrix": matrix,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = summarize(args.xml, head)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Deterministic agent evals: {report['passed']}/{report['required']}; scorecard: {args.out}")
    if report["passed"] != report["required"]:
        parser.exit(1)


if __name__ == "__main__":
    main()
