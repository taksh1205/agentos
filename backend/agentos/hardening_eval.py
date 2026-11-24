"""Independent outcome checks for the repeated synthetic release trials."""

import argparse
import json
import math
import re
from pathlib import Path
from statistics import median

from .release_check import approved_invoice_body, trial_cases


def evaluate(case, run):
    fixture = trial_cases()[case]
    label = fixture["expected"]
    report = run.get("report") or {}
    results = report.get("findings", [])
    traces = run.get("model_and_tool_traces", [])
    calls = [t for t in traces if t["kind"] == "model"]
    tools = {t["tool"] for t in traces if t["kind"] == "tool_call"}
    checks = {
        "completed": report.get("status") == "completed",
        "inference": any(t["response_received"] for t in calls),
    }
    if case == "R":
        support = {}
        summaries = []
        for result in results:
            finding = result.get("finding", {})
            sources = {hit["id"]: hit for hit in result.get("sources", [])}
            if finding.get("contradictions"):
                summaries.append(finding["summary"].lower())
            for claim in finding.get("claims", []):
                for cid in claim["citations"]:
                    source = sources.get(cid, {})
                    quote = claim.get("quote")
                    if quote and quote in source.get("text", ""):
                        support.setdefault(source["source"], []).append(quote.lower())
        checks["source_precision"] = set(support) == set(label["quotes"])
        for source, clause in label["quotes"].items():
            checks[source] = any(clause in q for q in support.get(source, [])) and any(
                clause in summary for summary in summaries
            )
        checks["neural_tool"] = tools == {label["tool"]} and run.get(
            "embedding_descriptor", ""
        ).startswith("neural:")
    elif case == "L":
        checks["tools"] = tools == {"business_metrics", "dataset_schema"}
        metrics = {
            m["metric"]: m for r in results for m in r.get("computed", {}).get("metrics", [])
        }
        checks["metric_set"] = set(metrics) == set(label["metrics"])
        summary = " ".join(r.get("interpretation", {}).get("summary", "") for r in results)
        for name, (first, last, delta, growth) in label["metrics"].items():
            metric = metrics.get(name, {})
            sentence = re.search(rf"\b{re.escape(name)} from [^()]+\([^)]*\)", summary, re.I)
            checks[name] = (
                metric.get("rows")
                == [
                    {"month": month, "value": value}
                    for month, value in zip(label["months"], [first, last])
                ]
                and metric.get("absolute_change") == delta
                and math.isclose(metric["growth"], growth)
                and sentence is not None
                and all(
                    value in sentence.group()
                    for value in (
                        f"{first:,.2f}",
                        f"{last:,.2f}",
                        f"{delta:+,.2f}",
                        f"{growth:+.2%}",
                    )
                )
            )
    else:
        proposal = run.get("proposal", {})
        effects = run.get("effects_after", [])
        body = proposal.get("arguments", {}).get("body", "")
        expected = [{"number": k, "amount": v} for k, v in label["balances"].items()]
        checks["argument_bindings"] = (
            fixture["cutoff"] in body
            and approved_invoice_body(body, expected)
            and f"${label['total']:,.2f}" in body
        )
        checks["correct_tool"] = proposal.get("tool") == label["tool"] and tools == {
            "dataset_schema",
            "invoice_analysis",
            label["tool"],
        }
        checks["approval"] = (
            run.get("effects_before") == [] and run.get("test_operator_approved") is True
        )
        checks["exactly_once"] = (
            len(effects) == 1
            and bool(proposal.get("id"))
            and effects[0]["approval_id"] == proposal.get("id")
            and (
                json.loads(effects[0]["result"]) == run.get("replay")
                and run["replay"]["payload"] == proposal["arguments"]
            )
        )
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "elapsed_seconds": run["elapsed_seconds"],
        "responses": sum(bool(t["response_received"]) for t in calls),
        "attempts": len(calls),
        "known_tokens": sum(t["tokens"] for t in calls if t.get("usage_known")),
        "workspace": run["workspace"],
    }


def summarize(directory):
    rows = []
    for path in sorted(directory.glob("*.json")):
        case = path.stem.split("-")[0]
        if case not in trial_cases():
            continue
        row = evaluate(case, json.loads(path.read_text()))
        rows.append({"case": case, "file": path.name, **row})
    if len({r["workspace"] for r in rows}) != len(rows):
        raise ValueError("Duplicate trial workspace")
    return {
        "rows": rows,
        "groups": {
            case: aggregate([r for r in rows if r["case"] == case]) for case in trial_cases()
        },
    }


def aggregate(rows):
    seconds = sorted(r["elapsed_seconds"] for r in rows)
    return {
        "executed": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "p50_seconds": median(seconds) if rows else None,
        "p95_seconds": seconds[math.ceil(0.95 * len(rows)) - 1] if rows else None,
        "known_tokens": sum(r["known_tokens"] for r in rows),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory), indent=2))
