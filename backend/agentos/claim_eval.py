"""Score structured verifier decisions against authored evidence packets."""

import argparse
import json
from pathlib import Path

from .verification import assess_claim

DATA = Path(__file__).resolve().parents[2] / "evals/datasets/claims-heldout.json"


def evaluate(output):
    corpus = json.loads(DATA.read_text())
    rows = []
    for example in corpus["cases"]:
        status, reason = assess_claim(
            example["claim"], corpus["sources"], corpus["computed"], corpus["effects"]
        )
        rows.append(
            {
                "id": example["id"],
                "expected": example["expected"],
                "actual": status,
                "reason": reason,
                "correct": status == example["expected"],
            }
        )
    approved = [r for r in rows if r["actual"] == "supported"]
    citations = [
        r
        for r, case in zip(rows, corpus["cases"])
        if case["claim"].get("citations") and r["actual"] == "supported"
    ]
    report = {
        "kind": "Verifier challenge, supplied claims; no generated answers",
        "cases": len(rows),
        "accuracy": sum(r["correct"] for r in rows) / len(rows),
        "support_precision": sum(r["correct"] for r in approved) / len(approved)
        if approved
        else None,
        "citation_support_precision": sum(r["correct"] for r in citations) / len(citations)
        if citations
        else None,
        "accepted_citation_cases": len(citations),
        "rows": rows,
    }
    Path(output).write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    evaluate(parser.parse_args().output)
