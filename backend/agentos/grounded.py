"""Typed evidence selection for constrained model serving."""

import json
import re
from typing import Literal

from pydantic import Field, create_model

from .models import Claim, Finding, Plan, Step, StrictModel

Read = Literal["document_search", "business_metrics", "invoice_analysis", "inventory_retrieval"]
Write = Literal[
    "create_report",
    "export_csv",
    "create_followup",
    "draft_email",
    "update_inventory",
    "create_notification",
]


class ReadSelection(StrictModel):
    primary: Read | Literal["multiple_sources"] | None
    clarification: str | None = None


class Selection(ReadSelection):
    write: Write | None = None


class ReportSelection(ReadSelection):
    write: Literal["create_report"] | None = None


def selection_schema(goal, can_write):
    if not can_write:
        return ReadSelection
    # A request explicitly naming the object to persist should not grant a
    # different mutation just because the report describes a follow-up.
    if re.search(
        r"\b(?:save|store|persist)\s+(?:(?:that|the|this|an?|internal|management|follow-up)\s+)*report\b",
        goal,
        re.I,
    ) and not re.search(r"\b(?:task|csv|email|notification|update)\b", goal, re.I):
        return ReportSelection
    return Selection


def compile_selection(choice, goal):
    reads = [choice.primary] if choice.primary else []
    steps = [
        Step(
            id=str(i),
            agent="research" if tool == "document_search" else "data",
            tool=tool,
            instruction=goal,
        )
        for i, tool in enumerate(reads)
    ]
    if write := getattr(choice, "write", None):
        steps.append(
            Step(
                id="write",
                agent="action",
                tool=write,
                instruction=goal,
                dependencies=[s.id for s in steps],
                requires_approval=True,
            )
        )
    return Plan(steps=steps, clarification=choice.clarification if not steps else None)


def synthesis_candidates(hits):
    """Drop weak dense-only tail hits when stronger matched passages are available."""
    best = max((hit.get("dense_score", 0.0) for hit in hits), default=0.0)
    return [
        hit
        for hit in hits
        if hit.get("rerank_score") is not None
        or hit.get("lexical_score", 1) > 0
        or hit.get("dense_score", 0) >= best / 2
    ]


class PolicyReading(StrictModel):
    analysis: str
    conflict: str | None
    recommendation: Literal[
        "seek_joint_review", "apply_consistent_requirements", "request_more_evidence"
    ]
    uncertainty: Literal["precedence_unknown", "evidence_incomplete", "no_conflict_identified"]


async def compare_passages(p, goal, shown):
    passages = {
        f"P{n}": (h["id"], sentence)
        for n, (h, sentence) in enumerate(
            (
                (hit, part)
                for hit in shown
                for part in re.split(r"(?<=[.!?])\s+", hit["text"])
                if part.strip()
                and not re.fullmatch(
                    r"[\w -]+\b(?:policy|manual|handbook|guidelines?)\.", part.strip(), re.I
                )
            ),
            1,
        )
    }
    if not passages:
        return Finding(summary="No passage available.", insufficient=True)
    schema = create_model(
        "PolicyAnalysis",
        __base__=PolicyReading,
        support=(list[Literal[tuple(passages)]], Field(min_length=1, max_length=12)),
    )
    result = await p.structured(
        schema,
        "Explain the requirements, any conflict and operational risks using only the passages. "
        "Select a recommendation and uncertainty. Conflicting requirements with no precedence rule "
        "need joint review. Never assign authority to waive a rule. Select only supporting passages.",
        json.dumps({"question": goal, "passages": passages}),
    )
    quotes = [
        Claim(
            kind="extractive", text=passages[k][1], quote=passages[k][1], citations=[passages[k][0]]
        )
        for k in dict.fromkeys(result.support)
    ]
    recommendations = {
        "seek_joint_review": "Ask the responsible policy owners to review the conflict together and document a resolution before changing operations.",
        "apply_consistent_requirements": "Apply the consistent requirements described in the cited passages.",
        "request_more_evidence": "Request the missing policy evidence before deciding.",
    }
    uncertainties = {
        "precedence_unknown": "The cited passages do not establish which requirement takes precedence.",
        "evidence_incomplete": "The available evidence leaves part of the question unresolved.",
        "no_conflict_identified": "This conclusion is limited to the passages reviewed.",
    }
    if result.conflict and result.recommendation == "apply_consistent_requirements":
        raise ValueError("Unresolved conflict cannot authorize implementation")
    # A conflict summary must carry its selected premises into downstream reports,
    # including reports consumed without the separate citation pane.
    conflict = (
        "Conflicting requirements: " + " ".join(claim.quote for claim in quotes)
        if result.conflict
        else ""
    )
    return Finding(
        summary=" ".join(
            filter(
                None,
                [
                    re.sub(r"\s*[(\[]P[0-9]+[)\]]", "", result.analysis),
                    conflict,
                    recommendations[result.recommendation],
                    uncertainties[result.uncertainty],
                ],
            )
        ),
        claims=quotes,
        citations=list(dict.fromkeys(c.citations[0] for c in quotes)),
        contradictions=[conflict] if conflict else [],
    )


def requested_metrics(goal):
    """Constrain a single-ledger comparison when the request enumerates its measures."""
    patterns = {
        "revenue": r"\brevenues?\b|\bsales\b(?!\s+(?:ledger|records?|data|report|costs?|margins?|profit)\b)",
        "costs": r"\b(?:expenses?|costs?)\b",
        "profit": r"\bprofits?\b(?!\s+margins?\b)",
        "margin": r"\bmargins?\b",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, goal, re.I)]


class LedgerReading(StrictModel):
    focus: Literal["revenue", "costs", "profit", "margin"]
    direction: Literal["increase", "decrease", "flat"]


async def interpret_sales(p, goal, data):
    metrics = data["metrics"]
    if not metrics or not all(m["rows"] and m["absolute_change"] is not None for m in metrics):
        return Finding(summary="Insufficient period data.", insufficient=True)
    reading = await p.structured(
        LedgerReading,
        "Identify a significant measured trend. Select one supplied metric and its observed direction.",
        json.dumps({"request": goal, "metrics": metrics}),
    )
    lines = []
    focus = None
    for m in metrics:
        first, last = m["rows"][0], m["rows"][-1]
        delta = m["absolute_change"]
        direction = "increase" if delta > 0 else "decrease" if delta < 0 else "flat"
        if m["metric"] == reading.focus and direction == reading.direction:
            focus = m["metric"]
        pct = f"{m['growth']:+.2%}" if m["growth"] is not None else "undefined relative change"
        lines.append(
            f"{m['metric'].capitalize()} from {first['month']} to {last['month']}: {first['value']:,.2f} to {last['value']:,.2f} ({delta:+,.2f}, {pct})."
        )
    if not focus:
        raise ValueError("Model trend contradicted the ledger")
    return Finding(
        summary=" ".join(lines)
        + f" The selected trend is the {reading.direction} in {focus}. The records do not establish a cause."
    )


class InvoiceReading(StrictModel):
    numbers: list[str]
    next_step: Literal["review_for_followup", "no_followup_needed"]


async def interpret_overdue(p, goal, data):
    reading = await p.structured(
        InvoiceReading,
        "Select every overdue unpaid invoice as of the supplied cutoff. Return its exact number and indicate whether follow-up review is warranted.",
        json.dumps(
            {"goal": goal, "as_of": data["as_of"], "overdue_unpaid_records": data["overdue_rows"]}
        ),
    )
    rows = data["overdue_rows"]
    if set(reading.numbers) != {r["number"] for r in rows} or (
        reading.next_step == "review_for_followup"
    ) != bool(rows):
        raise ValueError("Model selection differs from cutoff-filtered invoice records")
    lines = [f"{r['number']} is overdue for ${r['amount']:,.2f}." for r in rows]
    return Finding(
        summary=f"As of {data['as_of']}, overdue total is ${data['overdue_total']:,.2f}. "
        + " ".join(lines)
        + (" Review for follow-up." if rows else " No follow-up needed.")
    )
