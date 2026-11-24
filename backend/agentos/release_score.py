"""Check observable acceptance conditions against independent fixtures and stored receipts."""

import argparse
import json
import math
from pathlib import Path


def score(case, run):
    results = (run.get("report") or {}).get("findings", [])
    traces = run.get("model_and_tool_traces", [])
    models = [t for t in traces if t["kind"] == "model"]
    tools = [t["tool"] for t in traces if t["kind"] == "tool_call"]
    checks = {
        "terminal_report_completed": (run.get("report") or {}).get("status") == "completed",
        "received_live_model_response": any(t["response_received"] for t in models),
    }
    if case == "A":
        research = [r for r in results if r["agent"] == "research"]
        expected = {"inventory-policy", "capacity-policy"}
        cited = set()
        exact_quotes = set()
        for r in research:
            sources = {h["id"]: h for h in r["sources"]}
            for claim in r["finding"]["claims"]:
                for cid in claim["citations"]:
                    h = sources.get(cid)
                    if h:
                        cited.add(h["source"])
                        expected_clause = {
                            "inventory-policy": "at least twenty reserve pallets",
                            "capacity-policy": "at most twelve reserve pallets",
                        }.get(h["source"])
                        if (
                            claim.get("quote")
                            and claim["quote"] in h["text"]
                            and expected_clause
                            and expected_clause in claim["quote"].casefold()
                        ):
                            exact_quotes.add(h["source"])
        checks.update(
            neural_search=run.get("embedding_descriptor", "").startswith("neural:")
            and "document_search" in tools,
            both_policies_cited=expected <= cited,
            no_unrelated_citations=cited == expected,
            support_quotes_from_both=expected <= exact_quotes,
            contradiction_reported=any(r["finding"]["contradictions"] for r in research),
        )
        narrative = " ".join(r["finding"]["summary"] for r in research).casefold()
        checks["both_thresholds_in_answer"] = ("twenty" in narrative or "20" in narrative) and (
            "twelve" in narrative or "12" in narrative
        )
        checks["only_document_tools"] = set(tools) == {"document_search"}
    elif case == "B":
        rows = [r for r in run["source_sales"] if r["month"] in {"2026-02", "2026-03"}]
        metrics = {
            m["metric"]: m for r in results for m in r.get("computed", {}).get("metrics", [])
        }
        for name in ("revenue", "costs", "profit"):
            values = [r["revenue"] - r["costs"] if name == "profit" else r[name] for r in rows]
            actual = metrics.get(name, {})
            checks[name + "_periods_values_and_change"] = (
                len(values) == 2
                and actual.get("rows")
                == [{"month": r["month"], "value": v} for r, v in zip(rows, values)]
                and math.isclose(actual.get("absolute_change", math.inf), values[1] - values[0])
                and math.isclose(actual.get("growth", math.inf), values[1] / values[0] - 1)
            )
            if len(values) == 2:
                delta = values[1] - values[0]
                summary = " ".join(
                    r.get("interpretation", {}).get("summary", "") for r in results
                ).replace(",", "")
                checks[name + "_rendered_values_and_change"] = (
                    all(
                        token in summary
                        for token in (
                            f"{values[0]:.2f}",
                            f"{values[1]:.2f}",
                            f"{delta:+.2f}",
                            f"{delta / values[0]:+.2%}",
                        )
                    )
                    if values[0]
                    else False
                )
        checks["requested_tools"] = "business_metrics" in tools
    else:
        expected = [r for r in run["source_invoices"] if not r["paid"] and r["due"] < "2026-04-01"]
        balances = [r["computed"] for r in results if "overdue_rows" in r.get("computed", {})]
        effects = run["effects_after"]
        proposal = run.get("proposal", {})
        checks.update(
            correct_overdue_records=any(
                x["overdue_rows"] == expected
                and x["overdue_total"] == sum(r["amount"] for r in expected)
                and x["as_of"] == "2026-04-01"
                for x in balances
            ),
            no_effect_before_approval=run.get("effects_before") == [],
            approval_bound=run.get("test_operator_approved") is True
            and proposal.get("tool") == "create_report",
            exactly_one_persisted_effect=len(effects) == 1,
            persisted_approved_arguments_and_replay_match=len(effects) == 1
            and json.loads(effects[0]["result"]) == run.get("replay")
            and effects[0]["approval_id"] == proposal.get("id")
            and json.loads(effects[0]["result"])["payload"] == proposal.get("arguments"),
            invoice_and_report_tools={"invoice_analysis", "create_report"} <= set(tools),
        )
    return {
        "checks": checks,
        "machine_verdict": "FAIL" if not all(checks.values()) else "REQUIRES_SEMANTIC_REVIEW",
        "model_attempts": len(models),
        "responses": sum(bool(t["response_received"]) for t in models),
        "known_tokens": sum(
            t["input_tokens"] + t["output_tokens"] for t in models if t["usage_known"]
        ),
        "attempts_without_usage": sum(not t["usage_known"] for t in models),
        "elapsed_seconds": run["elapsed_seconds"],
        "estimated_cost_usd": None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directories",
        type=Path,
        nargs="+",
        help="Supply attempts in chronological order. The last recorded file for each case is scored.",
    )
    args = parser.parse_args()
    summary = {}
    for case in "ABC":
        files = [
            directory / (case + ".json")
            for directory in args.directories
            if (directory / (case + ".json")).is_file()
        ]
        if not files:
            summary[case] = {"machine_verdict": "BLOCKED", "reason": "Missing execution evidence"}
            continue
        evidence = files[-1]
        summary[case] = {"artifact": str(evidence), **score(case, json.loads(evidence.read_text()))}
    print(json.dumps(summary, indent=2))
