"""Exercise the installed HTTP application using only synthetic data in a private demo workspace."""

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def exercise(client, mode, model):
    def post(path, data=None):
        response = client.post(path, json=data)
        response.raise_for_status()
        return response.json()

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def wait(ident):
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = get("/runs/" + ident)
            if state["status"] != "running":
                return state
            time.sleep(1)
        raise TimeoutError("Workflow did not finish within four minutes")

    config = get("/config")
    if mode not in config["providers"]:
        raise ValueError("Requested provider is unavailable")
    post("/demo/seed")
    sources = [
        (
            "Settlement policy",
            "A management report must name its reporting period and the reporting currency.",
        ),
        (
            "Distribution policy",
            "Management reports require an internal manager approval before storage. Customer distribution is outside scope.",
        ),
    ]
    for source, content in sources:
        post("/documents", dict(source=source, content=content))
    cases = [
        (
            "research",
            "Research both the settlement policy and distribution policy. Which requirements apply to a management report?",
        ),
        (
            "business",
            "Analyze revenue and operating costs for the full period and report the computed totals.",
        ),
        (
            "operation",
            "Analyze revenue and operating costs, retrieve the policy documents and create an internal report with the figures and policy evidence.",
        ),
    ]
    rows = []
    for kind, goal in cases:
        start = time.perf_counter()
        ident = post("/runs", dict(goal=goal, mode=mode, model=model))["id"]
        state = wait(ident)
        approval = None
        if state["status"] == "awaiting_approval":
            approval = state["approval"][0]["proposal"]
            if kind != "operation" or approval["tool"] != "create_report":
                post(
                    "/runs/" + ident + "/approval",
                    {"approve": False, "proposal_id": approval["id"]},
                )
                raise AssertionError("Unexpected proposed mutation")
            if any(item["id"] == approval["id"] for item in get("/inbox")):
                raise AssertionError("Effect present before approval")
            post("/runs/" + ident + "/approval", {"approve": True, "proposal_id": approval["id"]})
            state = wait(ident)
        report = state.get("report", {})
        totals = {
            m["metric"]: m["total"]
            for r in report.get("findings", [])
            for m in r.get("computed", {}).get("metrics", [])
        }
        sources_used = {c["source"] for c in report.get("citations", [])}
        checks = {"completed": state["status"] == "completed"}
        if kind in {"research", "operation"}:
            checks["retrieved_both_policies"] = {s for s, _ in sources} <= sources_used
        if kind in {"business", "operation"}:
            checks["verified_totals"] = (
                totals.get("revenue") == 370000 and totals.get("costs") == 238000
            )
        if kind == "operation":
            effects = [v for v in get("/inbox") if approval and v["id"] == approval["id"]]
            checks["single_committed_report"] = (
                len(effects) == 1 and effects[0]["tool"] == "create_report"
            )
        rows.append(
            dict(
                kind=kind,
                goal=goal,
                id=ident,
                mode=mode,
                seconds=time.perf_counter() - start,
                checks=checks,
                approval=approval,
                report=report,
                plan=state.get("plan"),
                traces=get("/runs/" + ident + "/traces"),
            )
        )
    return {"configuration": config, "model": model, "mode": mode, "runs": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--mode", choices=["demo", "openai", "anthropic"], default="demo")
    parser.add_argument("--model")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with httpx.Client(
        base_url=args.url,
        headers={"Authorization": "Bearer " + os.getenv("AGENTOS_TOKEN", "local-demo-token")},
        timeout=120,
        trust_env=False,
    ) as client:
        report = exercise(client, args.mode, args.model)
    Path(args.output).write_text(json.dumps(report, indent=2))
    for row in report["runs"]:
        print(row["kind"], row["checks"])
    raise SystemExit(int(any(not all(row["checks"].values()) for row in report["runs"])))


if __name__ == "__main__":
    main()
