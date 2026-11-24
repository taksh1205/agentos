"""Labeled agent evaluation: generated scenarios are never reported as executed runs."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import os
import statistics
import tempfile
import time
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .graph import build_graph
from .rag import Retrieval
from .store import Store
from .tools import MUTATIONS

ROOT = Path(__file__).resolve().parents[2]


def scenarios(n):
    curated = json.loads((ROOT / "evals/datasets/agents.json").read_text())
    for record in curated[:n]:
        yield {**record, "origin": "hand-authored"}
    count = len(curated)
    if n <= count:
        return
    periods = [
        ("2026-01", "2026-01"),
        ("2026-02", "2026-02"),
        ("2026-03", "2026-03"),
        ("2026-01", "2026-02"),
        ("2026-02", "2026-03"),
        ("2026-01", "2026-03"),
    ]
    contexts = [
        "reporting rules",
        "cost review",
        "subscription review",
        "metric dictionary",
        "retention policy",
        "inventory procedure",
        "invoice procedure",
        "deployment checklist",
        "CSV safety",
        "tracing policy",
    ]
    actions = [
        "create_report",
        "export_csv",
        "create_followup",
        "draft_email",
        "create_notification",
    ]
    for metric, period, context, action in itertools.product(
        ["revenue", "costs", "profit", "margin"], periods, contexts, actions
    ):
        if count >= n:
            return
        start, end = period
        goal = f"Analyze {metric} from {start} through {end}, consult {context}, and prepare {action} for internal review."
        yield {
            "id": f"generated-{count - len(curated):04}",
            "goal": goal,
            "workflow": "operations",
            "expected_agents": ["data", "research", "action"],
            "expected_tools": ["business_metrics", "document_search", action],
            "expected_values": {},
            "expected_status": "completed",
            "expected_arguments": {"start": start, "end": end, "metric": metric},
            "approval": "approve",
            "origin": "combinatorial-generated",
            "label_notes": "Distinct parameter/context/action combinations, not independent real-world benchmark questions.",
        }
        count += 1


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)] if values else None


async def benchmark(n, mode, model, output, memory=False, dataset=None):
    store = Store()
    rag = Retrieval(store)
    w = "benchmark-" + str(uuid.uuid4())
    store.seed(w)
    corpus = json.loads((ROOT / "evals/datasets/retrieval.json").read_text())
    for doc in corpus["documents"]:
        rag.ingest(w, doc["id"], doc["title"] + "\n" + doc["text"])
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        async with AsyncSqliteSaver.from_conn_string(str(Path(temp) / "cp")) as cp:
            graph = build_graph(store, rag, cp)
            cases = (
                (
                    dict(r, origin="held-out authored")
                    for r in json.loads(Path(dataset).read_text())[:n]
                )
                if dataset
                else scenarios(n)
            )
            for case in cases:
                start = time.perf_counter()
                error = None
                out = {}
                workspace = w
                if case.get("empty_corpus"):
                    workspace = w + "-empty"
                    store.seed(workspace)
                original = store.analytics
                injected = [False]
                if case.get("inject_failure"):

                    def flaky(*args, **kwargs):
                        if not injected[0]:
                            injected[0] = True
                            raise TimeoutError("Benchmark injected transient failure")
                        return original(*args, **kwargs)

                    store.analytics = flaky
                approvals = 0
                try:
                    async with asyncio.timeout(
                        float(os.getenv("BENCHMARK_CASE_TIMEOUT_SECONDS", "240"))
                    ):
                        cfg = {
                            "configurable": {"thread_id": workspace + ":" + case["id"]},
                            "recursion_limit": 40,
                        }
                        out = await graph.ainvoke(
                            dict(
                                goal=case["goal"],
                                workflow="auto",
                                workspace=workspace,
                                run_id=case["id"],
                                mode=mode,
                                model=model,
                                memory_enabled=memory,
                                results=[],
                                events=[],
                            ),
                            cfg,
                        )
                        approvals = 0
                        while "__interrupt__" in out:
                            approvals += 1
                            if approvals > 12:
                                raise RuntimeError("Approval loop exceeded")
                            proposal = out["__interrupt__"][0].value.get("proposal", {})
                            permitted = (
                                case.get("approval") == "approve"
                                and proposal.get("tool") in set(case["expected_tools"]) & MUTATIONS
                            )
                            out = await graph.ainvoke(Command(resume=permitted), cfg)
                except Exception as exc:
                    error = type(exc).__name__
                finally:
                    store.analytics = original
                results = out.get("results", [])
                actual_agents = {r["agent"] for r in results if r.get("ok")}
                trace_rows = store.execute(
                    "SELECT payload FROM traces WHERE workspace=:w AND run_id=:r AND kind='tool_call'",
                    dict(w=workspace, r=case["id"]),
                )
                actual_tools = [json.loads(r["payload"])["tool"] for r in trace_rows]
                observed = {}
                for result in results:
                    if "computed" in result:
                        for metric in result["computed"].get("metrics", []):
                            observed[metric["metric"]] = metric["total"]
                            observed[metric["metric"] + "_growth"] = metric.get("growth")
                        if "unpaid_total" in result["computed"]:
                            observed["unpaid_total"] = result["computed"]["unpaid_total"]
                values_correct = all(
                    key in observed
                    and isinstance(observed[key], (float, int))
                    and abs(observed[key] - value) < 1e-6
                    for key, value in case.get("expected_values", {}).items()
                )
                args_expected = case.get("expected_arguments")
                args_correct = None
                if args_expected:
                    intents = [r["intent"] for r in results if "intent" in r]
                    args_correct = any(
                        i.get("start") == args_expected["start"]
                        and i.get("end") == args_expected["end"]
                        and args_expected["metric"] in i.get("metrics", [])
                        for i in intents
                    )
                research_findings = [
                    r.get("finding", {}) for r in results if r.get("agent") == "research"
                ]
                contradiction_correct = (
                    any(f.get("contradictions") for f in research_findings)
                    if case.get("expected_contradiction")
                    else None
                )
                sufficiency_correct = (
                    any(f.get("insufficient") for f in research_findings)
                    if case.get("expected_insufficient")
                    else None
                )
                retrieved_sources = {h["source"] for r in results for h in r.get("sources", [])}
                coverage_correct = set(case.get("expected_sources", [])) <= retrieved_sources
                expected_sources = set(case.get("expected_sources", []))
                citation_ids = {cid for f in research_findings for cid in f.get("citations", [])}
                source_by_id = {h["id"]: h["source"] for r in results for h in r.get("sources", [])}
                precision = (
                    sum(source_by_id.get(cid) in expected_sources for cid in citation_ids)
                    / len(citation_ids)
                    if expected_sources and citation_ids
                    else None
                )
                answer = " ".join(f.get("summary", "") for f in research_findings).casefold()
                facts = case.get("required_answer_fragments", [])
                completeness = (
                    sum(f.casefold() in answer for f in facts) / len(facts) if facts else None
                )
                status = out.get("report", {}).get("status")
                required_tools = set(case["expected_tools"])
                chosen = set(actual_tools) - {"dataset_schema"}
                tool_correct = required_tools <= set(actual_tools)
                tool_exact = chosen == required_tools - {"dataset_schema"}
                routing_correct = actual_agents == set(case["expected_agents"])
                mutations = set(actual_tools) & set(MUTATIONS)
                approval_correct = (
                    (
                        approvals > 0
                        and (bool(mutations) if case["approval"] == "approve" else not mutations)
                    )
                    if (case.get("approval") and "action" in case["expected_agents"])
                    else None
                )
                task_success = (
                    status == case["expected_status"]
                    and values_correct
                    and tool_correct
                    and (tool_exact if dataset else True)
                    and routing_correct
                    and args_correct is not False
                    and contradiction_correct is not False
                    and sufficiency_correct is not False
                    and completeness in (None, 1.0)
                    and coverage_correct
                    and (approval_correct is not False)
                )
                usage = out.get("usage", {})
                records = [
                    json.loads(row["payload"])
                    for row in store.execute(
                        "SELECT payload FROM traces WHERE workspace=:w AND run_id=:r AND kind='model' ORDER BY created",
                        dict(w=workspace, r=case["id"]),
                    )
                ]
                if records:
                    usage["tokens"] = (
                        sum(r["tokens"] for r in records)
                        if all(r.get("tokens") is not None for r in records)
                        else None
                    )
                    usage["estimated_cost_usd"] = (
                        sum(r["estimated_cost_usd"] for r in records)
                        if all(r.get("estimated_cost_usd") is not None for r in records)
                        else None
                    )
                rows.append(
                    {
                        "model_attempts": records,
                        "plan": out.get("plan"),
                        "answer_summaries": [
                            r.get("finding", r.get("interpretation", {})).get("summary")
                            for r in results
                            if r.get("ok") and r.get("agent") in {"research", "data"}
                        ],
                        "id": case["id"],
                        "origin": case["origin"],
                        "goal": case["goal"],
                        "expected_status": case["expected_status"],
                        "actual_status": status,
                        "completed": status == "completed",
                        "task_success": task_success,
                        "planning_valid": bool(
                            out.get("plan") or out.get("refusal") or out.get("clarification")
                        ),
                        "approval_correct": approval_correct,
                        "approval_interrupts": approvals,
                        "unexpected_tools": sorted(
                            set(actual_tools) - set(case["expected_tools"]) - {"dataset_schema"}
                        ),
                        "routing_correct": routing_correct,
                        "tool_selection_correct": tool_exact if dataset else tool_correct,
                        "all_required_tools_used": tool_correct,
                        "tool_set_exact": tool_exact,
                        "tool_arguments_correct": args_correct,
                        "computed_values_correct": values_correct,
                        "contradiction_detection_correct": contradiction_correct,
                        "evidence_sufficiency_correct": sufficiency_correct,
                        "expected_source_coverage": coverage_correct,
                        "observed_values": observed,
                        "actual_tools": actual_tools,
                        "recovery_success": task_success if case.get("inject_failure") else None,
                        "retry_count": sum(max(0, r.get("attempts", 1) - 1) for r in results),
                        "seconds": time.perf_counter() - start,
                        "tokens": usage.get("tokens", 0 if mode == "demo" else None),
                        "estimated_cost_usd": usage.get("estimated_cost_usd"),
                        "error": error,
                        "answer_faithfulness": None,
                        "semantic_citation_correctness": None,
                        "citation_precision_against_labeled_documents": precision,
                        "required_fragment_recall": completeness,
                        "judge_notes": "No human claim-level truth labels supplied; no semantic score invented.",
                    }
                )
    latencies = [r["seconds"] for r in rows]
    summary = {
        "configuration": {
            "mode": mode,
            "model": model,
            "memory": memory,
            "embedding": rag.descriptor,
        },
        "scenarios": len(rows),
        "completed": sum(r["completed"] for r in rows),
        "task_success_rate": statistics.mean(r["task_success"] for r in rows),
        "routing_accuracy": statistics.mean(r["routing_correct"] for r in rows),
        "tool_selection_accuracy": statistics.mean(r["tool_selection_correct"] for r in rows),
        "planning_validity": statistics.mean(r["planning_valid"] for r in rows),
        "p50_seconds": statistics.median(latencies),
        "p95_seconds": percentile(latencies, 0.95),
        "total_tokens": sum(r["tokens"] for r in rows)
        if all(r["tokens"] is not None for r in rows)
        else None,
        "estimated_cost_usd": sum(r["estimated_cost_usd"] for r in rows)
        if all(r["estimated_cost_usd"] is not None for r in rows)
        else None,
        "error_rate": statistics.mean(r["error"] is not None for r in rows),
        "retry_count": sum(r["retry_count"] for r in rows),
        "recall_at_5": None,
        "mrr": None,
        "notes": "Agent metrics use authored expectations. Retrieval metrics are separate. Offline rules are not model reasoning. Semantic claim metrics remain unlabeled/null.",
        "rows": rows,
    }
    Path(output).write_text(json.dumps(summary, indent=2))
    store.execute(
        "INSERT INTO experiments VALUES(:id,:w,:r,:t)",
        dict(id=str(uuid.uuid4()), w="demo", r=json.dumps(summary), t=time.time()),
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=24)
    parser.add_argument("--mode", choices=["demo", "openai", "anthropic"], default="demo")
    parser.add_argument("--model")
    parser.add_argument("--output", default="../evals/results/offline/agent-results.json")
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Enable shared semantic memory across independent cases (off by default)",
    )
    parser.add_argument("--generate")
    parser.add_argument("--dataset")
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n must be positive")
    if args.generate:
        Path(args.generate).write_text("\n".join(json.dumps(c) for c in scenarios(args.n)))
    else:
        asyncio.run(
            benchmark(
                args.n,
                args.mode,
                args.model,
                args.output,
                args.memory and not args.no_memory,
                args.dataset,
            )
        )
