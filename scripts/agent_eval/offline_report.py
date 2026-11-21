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
INTELLIGENCE_CASES = {
    "E18": "hypothesis board matches independent cause and rejected alternatives",
    "E19": "SQL allowlist, as-of isolation and receipt integrity",
    "E20": "self-written checks cannot grant a verdict",
    "E21": "counter-check catches a decoy without false vetoes",
    "E22": "critic independence, caps and monotone verdicts",
    "E23": "denials and verified precedents govern proposals",
    "E24": "case memory cannot contribute evidence",
    "E25": "receipted cause chains and impact",
    "E26": "investigation caps, cost accounting and zero replay spend",
    "E27": "v1 immutability and v2 cold replay",
    "E28": "advisory STL agreement on pages and quiet hours",
}
INTELLIGENCE_MIN_TRIALS = {
    "E18": 11,  # eight positive and three negative worlds or captures
    "E19": 39,  # 28 rejections, ten accepted cuts, and the future-hour check
    "E20": 2,
    "E21": 9,
    "E22": 20,
    "E23": 1,
    "E24": 4,
    "E25": 9,
    "E26": 1,
    "E27": 4,
    "E28": 1,
}
CASE_NAME = re.compile(r"test_(e\d{2})(?:_|\[|$)", re.IGNORECASE)
FIRST_DIFFERENCE = re.compile(r"(?:turn|observation) (\d+)", re.IGNORECASE)
SCENARIO_MATRIX = {
    f"test_e01_disposition_on_sealed_scenarios[{seed}-{scenario}]": (scenario, seed)
    for scenario in SCENARIOS
    for seed in SEEDS
}


def summarize(xml: Path, commit: str, *, intelligence: bool = False, cut_stl: bool = False) -> dict[str, object]:
    index = CASES | INTELLIGENCE_CASES if intelligence else CASES
    tests: dict[str, list[dict[str, str | int | None]]] = {case: [] for case in index}
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
                len({test["test"] for test in tests[case]}) >= INTELLIGENCE_MIN_TRIALS.get(case, 1)
                and all(test["outcome"] == "pass" for test in tests[case])
                and (case != "E01" or matrix_complete)
            ),
            "trials": tests[case],
        }
        for case, invariant in index.items()
        if case != "E28" or not cut_stl
    ]
    return {
        "commit": commit,
        "cohort": "deterministic_agent",
        "required": len(cases),
        "passed": sum(bool(case["passed"]) for case in cases),
        "junit": str(xml),
        "scenario_matrix": matrix,
        "cases": cases,
        **({"cuts": ["E28"] if cut_stl else []} if intelligence else {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--intelligence", action="store_true", help="include the v2 intelligence evals")
    parser.add_argument("--cut-stl", action="store_true", help="mark the optional STL feature as cut")
    args = parser.parse_args()
    if args.cut_stl and not args.intelligence:
        parser.error("--cut-stl requires --intelligence")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = summarize(args.xml, head, intelligence=args.intelligence, cut_stl=args.cut_stl)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Deterministic agent evals: {report['passed']}/{report['required']}; scorecard: {args.out}")
    if report["passed"] != report["required"]:
        parser.exit(1)


if __name__ == "__main__":
    main()
