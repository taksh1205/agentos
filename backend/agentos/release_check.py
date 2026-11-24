"""Capture live graph outputs for the three release workflows in isolated synthetic workspaces."""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .graph import build_graph
from .ingestion import extract_upload
from .mcp_client import call_tool
from .rag import Retrieval
from .store import Store

GOALS = {
    "A": "Compare the inventory and capacity policies for the East depot's reserve stock. Identify the conflicting thresholds, explain the operational risk, and give a cited recommendation with uncertainties.",
    "B": "Analyze February and March 2026 revenue, expenses, and profit. Calculate month-over-month changes for all three metrics, identify significant trends, and explain the findings.",
    "C": "Analyze overdue invoices as of 2026-04-01. Prepare an internal follow-up report identifying overdue invoice numbers and amounts. Save that report after my approval.",
}
DOCUMENTS = {
    "inventory-policy": "East depot inventory policy. The East depot must keep at least twenty reserve pallets on site to cover supply interruptions. Reducing reserve stock requires the inventory owner's approval.",
    "capacity-policy": "East depot capacity policy. The East depot may keep at most twelve reserve pallets on site to maintain fire-lane clearance. The capacity owner must review any proposed exception.",
    "travel-policy": "Employee travel policy. Rail fares are reimbursed upon submission of receipts.",
}


def approved_invoice_body(body, expected):
    identifiers = set(re.findall(r"\bINV-[0-9]+\b", body))
    amounts = {
        float(token.replace(",", ""))
        for token in re.findall(r"\$(-?[0-9][0-9,]*(?:\.[0-9]+)?)", body)
    }
    if not expected:
        return False
    values = {row["amount"] for row in expected}
    # Each invoice must carry its own balance. Matching two unordered sets
    # permits a report that swaps amounts between customers.
    for row in expected:
        match = re.search(
            rf"\b{re.escape(row['number'])}\b(?:(?!INV-)[^$\n])*?\$(-?[0-9][0-9,]*(?:\.[0-9]+)?)",
            body,
        )
        if not match or float(match[1].replace(",", "")) != row["amount"]:
            return False
    return identifiers == {row["number"] for row in expected} and (
        values <= amounts <= values | {sum(row["amount"] for row in expected)}
    )


def trial_cases():
    path = Path(
        os.getenv(
            "AGENTOS_TRIAL_DATASET",
            Path(__file__).resolve().parents[2] / "evals/datasets/live-hardening.json",
        )
    )
    if not path.exists():
        # Original acceptance workflows are also available from installed wheels.
        return {}
    return json.loads(path.read_text())


async def run(case, dest):
    start = time.monotonic()
    w = "release-" + str(uuid4())
    store = Store()
    store.seed(w)
    trial = trial_cases().get(case, {})
    goal = trial.get("goal") or GOALS[case]
    kind = trial.get("kind", case)
    for month, revenue, costs in trial.get("sales", []):
        store.execute(
            "INSERT INTO sales(id,workspace,month,revenue,costs) VALUES(:id,:w,:m,:r,:c)",
            dict(id=str(uuid4()), w=w, m=month, r=revenue, c=costs),
        )
    if "invoices" in trial:
        store.execute("DELETE FROM invoices WHERE workspace=:w", {"w": w})
        for number, amount, paid, due in trial["invoices"]:
            store.execute(
                "INSERT INTO invoices(workspace,number,amount,paid,due) VALUES(:w,:n,:a,:p,:d)",
                dict(w=w, n=number, a=amount, p=paid, d=due),
            )
    if case == "B" and os.getenv("RELEASE_TRANSFER") == "1":
        goal = "For February and March 2026, compare sales revenue, costs and profit. Explain the month-over-month movement using the ledger."
        store.execute(
            "UPDATE sales SET revenue=:revenue, costs=:costs WHERE workspace=:w AND month=:month",
            {"w": w, "month": "2026-03", "revenue": 105000, "costs": 81000},
        )
    log = {"goal": goal, "model": os.environ["OPENAI_MODEL"], "workspace": w}
    cfg = {"configurable": {"thread_id": w}, "recursion_limit": 40}
    params = {"w": w}

    def effects():
        return store.execute(
            "SELECT approval_id,tool,result FROM effects WHERE workspace=:w", params
        )

    async def invoke(graph, inputs):
        try:
            return await graph.ainvoke(inputs, cfg)
        finally:
            snapshot = await graph.aget_state(cfg)
            log["last_checkpoint"] = {
                key: snapshot.values[key]
                for key in ("plan", "results", "events")
                if key in snapshot.values
            }

    try:
        if os.getenv("USE_MCP") != "true":
            raise RuntimeError("Release workflows must execute tools through MCP")
        # Model serving, indexing and MCP search have distinct lifetimes. Release the
        # indexer's encoder before the search service loads the same pinned encoder.
        rag = None
        if kind == "A":
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "agentos.release_check",
                "--index-workspace",
                w,
                "--corpus",
                case,
                stdout=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode:
                raise RuntimeError("Neural indexing failed; inspect the case log")
            log["embedding_descriptor"] = stdout.decode().strip()
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = str(Path(temp) / "checkpoint.db")
            async with AsyncSqliteSaver.from_conn_string(checkpoint) as cp:
                graph = build_graph(store, rag, cp)
                state = await invoke(
                    graph,
                    dict(
                        workspace=w,
                        run_id=case,
                        goal=goal,
                        workflow="auto",
                        memory_enabled=False,
                        mode="openai",
                        model=log["model"],
                        results=[],
                        events=[],
                        scopes=["data:read", "action:write"] if kind == "C" else ["data:read"],
                    ),
                )
            if "__interrupt__" in state:
                proposal = state["__interrupt__"][0].value["proposal"]
                log.update(proposal=proposal, effects_before=effects())
                body = proposal["arguments"].get("body", "")
                permit = (
                    kind == "C"
                    and not effects()
                    and proposal["tool"] == "create_report"
                    and approved_invoice_body(
                        body,
                        store.execute(
                            "SELECT number,amount FROM invoices WHERE workspace=:w AND paid=0 AND due<:cutoff",
                            {"w": w, "cutoff": trial.get("cutoff", "2026-04-01")},
                        ),
                    )
                )
                log["test_operator_approved"] = permit
                async with AsyncSqliteSaver.from_conn_string(checkpoint) as cp:
                    graph = build_graph(store, rag, cp)
                    state = await invoke(graph, Command(resume=permit))
                if permit and effects():
                    log["replay"] = await call_tool(
                        w,
                        proposal["tool"],
                        proposal["arguments"],
                        approval_id=proposal["id"],
                        scopes=["action:write"],
                    )
            for field in ["report", "results", "plan", "events", "usage"]:
                log[field] = state.get(field)
    except asyncio.CancelledError:
        log["exception"] = {
            "type": "TimeoutOrCancellation",
            "message": "Run interrupted before terminal output",
        }
        raise
    except Exception as exc:
        log["exception"] = {"type": type(exc).__name__, "message": str(exc)[:2200]}
    finally:
        log["effects_after"] = effects()
        log["model_and_tool_traces"] = [
            {"kind": r["kind"], **json.loads(r["payload"])}
            for r in store.execute(
                "SELECT kind,payload FROM traces WHERE workspace=:w AND kind IN ('model','tool_call') ORDER BY created",
                params,
            )
        ]
        log["source_sales"] = store.execute(
            "SELECT month,revenue,costs FROM sales WHERE workspace=:w ORDER BY month", params
        )
        log["source_invoices"] = store.execute(
            "SELECT number,amount,paid,due FROM invoices WHERE workspace=:w ORDER BY number", params
        )
        log["elapsed_seconds"] = time.monotonic() - start
        dest.write_text(json.dumps(log, indent=2, default=str) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-workspace")
    parser.add_argument("--corpus", default="A")
    parser.add_argument("case", nargs="?", choices=list(GOALS) + list(trial_cases()))
    parser.add_argument("output", nargs="?", type=Path)
    args = parser.parse_args()
    if args.index_workspace:
        rag = Retrieval(Store(), backend="neural")
        for source, content in (
            trial_cases().get(args.corpus, {}).get("documents", DOCUMENTS).items()
        ):
            data = asyncio.run(extract_upload(source + ".txt", content.encode()))
            rag.ingest(args.index_workspace, source, data)
        print(rag.descriptor)
        sys.exit(0)
    if not args.case or not args.output:
        parser.error("Supply a release case and output path")
    asyncio.run(
        asyncio.wait_for(
            run(args.case, args.output), timeout=float(os.getenv("RELEASE_TIMEOUT_SECONDS", "420"))
        )
    )
