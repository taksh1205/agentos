"""Bounded dependency context, capability ownership and machine-checkable completion."""

import hashlib
import json

from .tools import CAPABILITIES, MUTATIONS, SCHEMAS

OWNERS = {
    "research": {"document_search"},
    "data": {"dataset_schema", "business_metrics", "inventory_retrieval", "invoice_analysis"},
    "action": MUTATIONS,
}


def validate_capabilities(plan):
    for step in plan.steps:
        if step.tool and (step.tool not in CAPABILITIES or step.tool not in OWNERS[step.agent]):
            raise PermissionError("Tool is not owned by the selected agent")
        if step.tool and step.arguments:
            SCHEMAS[step.tool].model_validate(step.arguments)
        for check in step.checks:
            allowed_kinds = {
                "research": {"source_count", "tool"},
                "data": {"metric", "tool"},
                "action": {"action_receipt", "tool"},
            }
            if check.kind not in allowed_kinds[step.agent]:
                raise ValueError("Completion check cannot be established by this agent")
            if check.kind == "tool" and check.tool not in OWNERS[step.agent]:
                raise ValueError("Completion tool is not owned by the assigned agent")
            if check.kind == "metric" and check.metric is None:
                raise ValueError("Metric completion check needs a metric")
            if check.tool and check.tool not in CAPABILITIES:
                raise ValueError("Unknown completion tool")
        if step.agent == "action":
            step.requires_approval = True


def dependency_results(state, step):
    by_id = {p["id"]: p for p in state.get("plan", [])}
    pending = list(step.get("dependencies", []))
    ids = set()
    while pending:
        ident = pending.pop()
        if ident in ids:
            continue
        ids.add(ident)
        pending.extend(by_id.get(ident, {}).get("dependencies", []))
    return [r for r in state.get("results", []) if r["step"] in ids and r.get("ok")]


def context_packet(state, step, max_chars=12000):
    rows = []
    used = 0
    for result in dependency_results(state, step):
        value = {
            key: result[key]
            for key in [
                "step",
                "agent",
                "finding",
                "interpretation",
                "computed",
                "analytics",
                "effect",
            ]
            if key in result
        }
        # Preserve bound ID/text snippets, rather than truncating serialized JSON mid-field.
        value["sources"] = [
            {"id": s["id"], "source": s["source"], "text": s["text"][:1000]}
            for s in result.get("sources", [])[:4]
        ]
        size = len(json.dumps(value))
        if used + size > max_chars:
            value = {
                "step": result["step"],
                "agent": result["agent"],
                "omitted_large_payload": True,
                "source_ids": [s["id"] for s in result.get("sources", [])],
            }
            size = len(json.dumps(value))
        if used + size <= max_chars:
            rows.append(value)
            used += size
    return rows


def evidence_fingerprint(state):
    values = [
        {
            k: r[k]
            for k in [
                "step",
                "agent",
                "ok",
                "finding",
                "interpretation",
                "computed",
                "analytics",
                "sources",
                "error",
                "receipt",
                "denied",
            ]
            if k in r
        }
        for r in state.get("results", [])
        if r["step"] in {p["id"] for p in state.get("plan", [])}
    ]
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def completion_issues(step, result):
    errors = []
    for check in step.get("checks", []):
        kind = check["kind"]
        if kind == "source_count" and len(
            {s["document_id"] for s in result.get("sources", [])}
        ) < check.get("minimum", 1):
            errors.append("insufficient_distinct_sources")
        elif kind == "metric":
            values = [
                m.get("total")
                for m in result.get("computed", {}).get("metrics", [])
                if m["metric"] == check.get("metric")
            ]
            if not values:
                errors.append("completion_metric_missing")
            elif check.get("expected") is not None and abs(values[0] - check["expected"]) > 1e-6:
                errors.append("completion_metric_incorrect")
        elif kind == "tool" and check.get("tool") not in result.get("tools_used", []):
            errors.append("completion_tool_missing")
        elif (
            kind == "action_receipt"
            and not result.get("denied")
            and not result.get("effect", {}).get("stored")
        ):
            errors.append("completion_receipt_missing")
    return errors


def expand_capability_plan(candidate):
    from .models import Plan, Step

    owners = {tool: agent for agent, tools in OWNERS.items() for tool in tools}
    steps = []
    for i, task in enumerate(candidate.tasks):
        if any(j < 0 or j >= i for j in task.after):
            raise ValueError("Dependency must refer to an earlier zero-based task index")
        steps.append(
            Step(
                id=str(i),
                agent=owners[task.capability],
                instruction=task.instruction,
                tool=task.capability,
                dependencies=[str(j) for j in task.after],
                requires_approval=task.capability in MUTATIONS,
            )
        )
    plan = Plan(steps=steps, clarification=candidate.clarification, refusal=candidate.refusal)
    validate_capabilities(plan)
    return plan
