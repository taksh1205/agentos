"""Frozen live-model evaluation: fresh workspace per run, real tools, programmatic grading.

Each case seeds its own synthetic records and documents, runs the full five-agent graph
with a live model (OpenAI-compatible or Anthropic), lets a synthetic operator approve
only proposals that match the case's independent labels, and grades the outcome with
checks that never consult the graph's own verdict alone.

    python -m agentos.live_eval --dataset ../evals/datasets/live-frozen-v1.json \
        --mode openai --model qwen3-4b-local --repeats 3 --output /tmp/live.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .graph import build_graph, run_profile
from .rag import Retrieval
from .release_check import approved_invoice_body
from .store import Store
from .tools import MUTATIONS, ToolService
from .verification import numbers

ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------- grading


def _any(text, options):
    options = [options] if isinstance(options, str) else options
    return any(option.casefold() in text.casefold() for option in options)


def fact_present(text, fact):
    """Strings match case-insensitively; numbers match by value, sign-agnostic."""
    if isinstance(fact, (str, list)):
        return _any(text, fact)
    values = [abs(v) for v in numbers(text)]
    if "percent" in fact:
        target = abs(fact["percent"])
        return any(math.isclose(v, target, abs_tol=6e-4) for v in values)
    target = abs(fact["number"])
    return any(math.isclose(v, target, rel_tol=1e-3, abs_tol=0.011) for v in values)


def operator_decision(case, proposal):
    """Synthetic reviewer. Approves only an exact, independently correct proposal."""
    policy = case.get("operator") or {"decision": "decline"}
    if policy["decision"] != "approve_if" or proposal.get("tool") != policy.get("tool"):
        return False
    body = json.dumps(proposal.get("arguments", {}), ensure_ascii=False)
    readable = " ".join(str(v) for v in proposal.get("arguments", {}).values())
    if "invoice_balances" in policy:
        expected = [{"number": k, "amount": v} for k, v in policy["invoice_balances"].items()]
        if not approved_invoice_body(readable, expected):
            return False
    if "require_any" in policy and not _any(readable, policy["require_any"]):
        return False
    for pattern in policy.get("forbid_patterns", []):
        if re.search(pattern, body, re.I):
            return False
    return True


def grade(case, run):
    expected = case["expected"]
    report = run.get("report") or {}
    findings = report.get("findings", [])
    proposals = run["proposals"]
    effects = run["effects"]
    tools = set(run["tools_called"])
    text = run["answer_text"]
    checks = {"no_exception": run.get("exception") is None}
    checks["status"] = report.get("status") in expected["status"]
    checks["live_inference"] = run["model_responses"] > 0
    if expected.get("tools_required"):
        checks["tools_required"] = set(expected["tools_required"]) <= (
            tools | {p["tool"] for p in proposals}
        )
    if expected.get("no_proposals"):
        checks["no_write_proposed"] = not proposals and not (tools & MUTATIONS)
    if "proposal_tool" in expected:
        checks["proposal_tool"] = bool(proposals) and all(
            p["tool"] == expected["proposal_tool"] for p in proposals
        )
    if "effects" in expected:
        checks["effects"] = len(effects) == expected["effects"]
        if expected["effects"]:
            checks["approved_by_operator"] = any(p["approved"] for p in proposals)
            checks["replay_idempotent"] = run.get("replay_identical") is True
    research = [r.get("finding", {}) for r in findings if r.get("agent") == "research"]
    if "contradiction" in expected:
        flagged = any(f.get("contradictions") for f in research)
        checks["contradiction"] = flagged == expected["contradiction"]
    if expected.get("insufficient"):
        stated = re.search(
            r"\b(?:no information|not (?:found|mention|specif|cover|address|contain|provide|include)"
            r"|does not (?:mention|specify|cover|address|contain|provide|include|state)"
            r"|insufficient|missing|unresolved|not available|unavailable|no (?:relevant |such )?"
            r"(?:policy|document|evidence))",
            text,
            re.I,
        )
        checks["insufficient"] = any(f.get("insufficient") for f in research) or bool(stated)
    cited = {
        hit["source"]
        for r in findings
        for hit in r.get("sources", [])
        if hit["id"] in r.get("finding", {}).get("citations", [])
    }
    if expected.get("cited_sources"):
        checks["cited_sources"] = set(expected["cited_sources"]) <= cited
    if expected.get("forbidden_citations"):
        checks["no_distractor_citations"] = not (set(expected["forbidden_citations"]) & cited)
    for i, fact in enumerate(expected.get("facts", [])):
        checks[f"fact_{i}"] = fact_present(text, fact)
    for i, pattern in enumerate(expected.get("forbidden_patterns", [])):
        checks[f"forbidden_{i}"] = re.search(pattern, text, re.I) is None
    return {"passed": all(checks.values()), "checks": checks}


# --------------------------------------------------------------------------- execution


def seed(store, w, case):
    for month, revenue, costs in case.get("sales", []):
        store.execute(
            "INSERT INTO sales(id,workspace,month,revenue,costs) VALUES(:id,:w,:m,:r,:c)",
            dict(id=f"{w}:{month}", w=w, m=month, r=revenue, c=costs),
        )
    for number, amount, paid, due in case.get("invoices", []):
        store.execute(
            "INSERT INTO invoices(workspace,number,amount,paid,due) VALUES(:w,:n,:a,:p,:d)",
            dict(w=w, n=number, a=amount, p=paid, d=due),
        )
    for sku, quantity, threshold in case.get("inventory", []):
        store.execute(
            "INSERT INTO inventory(workspace,sku,quantity,threshold) VALUES(:w,:s,:q,:t)",
            dict(w=w, s=sku, q=quantity, t=threshold),
        )


async def replay(w, proposal):
    if os.getenv("USE_MCP") == "true":
        from .mcp_client import call_tool

        return await call_tool(
            w,
            proposal["tool"],
            proposal["arguments"],
            approval_id=proposal["id"],
            scopes=["action:write"],
        )
    return await asyncio.to_thread(
        ToolService(Store(), None).invoke,
        w,
        proposal["tool"],
        proposal["arguments"],
        scopes=["action:write"],
        approval_id=proposal["id"],
    )


async def run_case(case, defaults, mode, model, rag, store):
    w = f"live-{case['id']}-{uuid4().hex[:10]}"
    seed(store, w, case)
    for source, content in case.get("documents", {}).items():
        await asyncio.to_thread(rag.ingest, w, source, content)
    run = {"case": case["id"], "group": case.get("group"), "workspace": w, "proposals": []}
    cfg = {"configurable": {"thread_id": w}, "recursion_limit": 40}
    start = time.perf_counter()
    state = {}
    try:
        with tempfile.TemporaryDirectory() as temp:
            async with AsyncSqliteSaver.from_conn_string(str(Path(temp) / "cp.db")) as cp:
                graph = build_graph(store, rag, cp)
                inputs = dict(
                    workspace=w,
                    run_id=case["id"],
                    goal=case["goal"],
                    workflow="auto",
                    memory_enabled=False,
                    mode=mode,
                    model=model,
                    results=[],
                    events=[],
                    scopes=case.get("scopes", defaults["scopes"]),
                )
                async with asyncio.timeout(float(os.getenv("LIVE_CASE_TIMEOUT_SECONDS", "900"))):
                    state = await graph.ainvoke(inputs, cfg)
                    for _ in range(4):
                        if "__interrupt__" not in state:
                            break
                        proposal = state["__interrupt__"][0].value["proposal"]
                        decision = operator_decision(
                            {**case, "operator": case.get("operator", defaults["operator"])},
                            proposal,
                        )
                        run["proposals"].append({**proposal, "approved": decision})
                        state = await graph.ainvoke(Command(resume=decision), cfg)
    except Exception as exc:  # recorded and graded; never hidden
        run["exception"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    run["seconds"] = time.perf_counter() - start
    effects = store.execute(
        "SELECT approval_id,tool,result FROM effects WHERE workspace=:w", {"w": w}
    )
    run["effects"] = [{**e, "result": json.loads(e["result"])} for e in effects]
    if effects:
        approved = next((p for p in run["proposals"] if p["approved"]), None)
        if approved:
            again = await replay(w, approved)
            after = store.execute("SELECT approval_id FROM effects WHERE workspace=:w", {"w": w})
            run["replay_identical"] = again == run["effects"][0]["result"] and len(after) == 1
    report = state.get("report") or {}
    run["report"] = report
    run["plan"] = state.get("plan")
    traces = [
        {"kind": r["kind"], **json.loads(r["payload"])}
        for r in store.execute(
            "SELECT kind,payload FROM traces WHERE workspace=:w AND kind IN ('model','tool_call') "
            "ORDER BY created",
            {"w": w},
        )
    ]
    models = [t for t in traces if t["kind"] == "model"]
    run["tools_called"] = [t["tool"] for t in traces if t["kind"] == "tool_call"]
    run["model_attempts"] = len(models)
    run["model_responses"] = sum(bool(t.get("response_received")) for t in models)
    run["tokens"] = (
        sum(t["input_tokens"] + t["output_tokens"] for t in models)
        if all(t.get("usage_known") for t in models)
        else None
    )
    run["model_records"] = models
    summaries = [
        r.get("finding", r.get("interpretation", {})).get("summary", "")
        for r in report.get("findings", [])
        if r.get("agent") in {"research", "data"}
    ]
    bodies = [" ".join(str(v) for v in p["arguments"].values()) for p in run["proposals"]]
    extra = [report.get("clarification") or "", report.get("refusal") or ""]
    run["answer_text"] = "\n".join(filter(None, summaries + bodies + extra))
    run["grade"] = grade(case, run)
    return run


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)] if values else None


def summarize(runs, repeats):
    by_case = {}
    for run in runs:
        by_case.setdefault(run["case"], []).append(run)
    cases = {}
    for case_id, items in by_case.items():
        passes = [r["grade"]["passed"] for r in items]
        failed = sorted(
            {name for r in items for name, ok in r["grade"]["checks"].items() if not ok}
        )
        cases[case_id] = {
            "group": items[0]["group"],
            "runs": len(items),
            "passed": sum(passes),
            "pass_all_k": all(passes),
            "failed_checks": failed,
            "median_seconds": statistics.median(r["seconds"] for r in items),
        }
    groups = {}
    for group in sorted({c["group"] for c in cases.values()}):
        members = [r for r in runs if r["group"] == group]
        ids = [k for k, c in cases.items() if c["group"] == group]
        groups[group] = {
            "cases": len(ids),
            "runs": len(members),
            "pass_at_1": statistics.mean(r["grade"]["passed"] for r in members),
            f"pass_all_{repeats}": statistics.mean(cases[k]["pass_all_k"] for k in ids),
        }
    seconds = [r["seconds"] for r in runs]
    tokens = [r["tokens"] for r in runs if r["tokens"] is not None]
    return {
        "runs": len(runs),
        "pass_at_1": statistics.mean(r["grade"]["passed"] for r in runs),
        f"pass_all_{repeats}": statistics.mean(c["pass_all_k"] for c in cases.values()),
        "groups": groups,
        "p50_seconds": statistics.median(seconds),
        "p95_seconds": percentile(seconds, 0.95),
        "mean_tokens_per_run": statistics.mean(tokens) if tokens else None,
        "total_tokens": sum(tokens) if len(tokens) == len(runs) else None,
        "mean_model_responses_per_run": statistics.mean(r["model_responses"] for r in runs),
        "exceptions": sum(r.get("exception") is not None for r in runs),
        "unapproved_effects": sum(
            bool(r["effects"]) and not any(p["approved"] for p in r["proposals"]) for r in runs
        ),
        "cases": cases,
    }


def git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return None


async def main(args):
    dataset = json.loads(Path(args.dataset).read_text())
    cases = [c for c in dataset["cases"] if not args.cases or c["id"] in args.cases]
    store = Store()
    rag = Retrieval(store)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    runs = []
    for repeat in range(args.repeats):
        for case in cases:
            run = await run_case(case, dataset["defaults"], args.mode, args.model, rag, store)
            run["repeat"] = repeat + 1
            runs.append(run)
            verdict = "PASS" if run["grade"]["passed"] else "FAIL"
            failed = [k for k, ok in run["grade"]["checks"].items() if not ok]
            print(
                f"[{repeat + 1}/{args.repeats}] {case['id']:4} {verdict} {run['seconds']:6.1f}s "
                f"tokens={run['tokens']} {failed if failed else ''}",
                flush=True,
            )
            result = {
                "configuration": {
                    "dataset": dataset["name"],
                    "mode": args.mode,
                    "model": args.model,
                    "model_sha256": os.getenv("MODEL_SHA256"),
                    "inference_server": os.getenv("INFERENCE_SERVER"),
                    "planner_profile": run_profile({"mode": args.mode}),
                    "structured_output": os.getenv("OPENAI_STRUCTURED_OUTPUT", "tool"),
                    "embedding": rag.descriptor,
                    "retrieval_method": os.getenv("RETRIEVAL_METHOD", "hybrid"),
                    "use_mcp": os.getenv("USE_MCP") == "true",
                    "repeats": args.repeats,
                    "git_commit": git_commit(),
                },
                "summary": summarize(runs, args.repeats),
                "runs": runs,
            }
            output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps({k: v for k, v in result["summary"].items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(ROOT / "evals/datasets/live-frozen-v1.json"))
    parser.add_argument("--mode", choices=["openai", "anthropic"], default="openai")
    parser.add_argument("--model", required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
