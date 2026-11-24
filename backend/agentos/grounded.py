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
    # Offered only when the request asks to persist a document, so the write is not optional.
    write: Literal["create_report"] = "create_report"


PERSIST_VERB = re.compile(r"\b(?:save|store|persist|file|record|keep|put)\b", re.I)
DOCUMENT_NOUN = re.compile(r"\b(?:report|memo|brief|briefing|summary|write-?up|document)\b", re.I)
OTHER_WRITE_TARGET = re.compile(
    r"\b(?:task|csv|export|e-?mail|notification|notify|alert|update|inventory)\b", re.I
)


def selection_schema(goal, can_write):
    if not can_write:
        return ReadSelection
    # A request to persist a document ("file a memo", "store the report") names its
    # target. Restrict the write to create_report so a small model cannot substitute a
    # notification or task for the document the user asked to keep.
    if (
        PERSIST_VERB.search(goal)
        and DOCUMENT_NOUN.search(goal)
        and not OTHER_WRITE_TARGET.search(goal)
    ):
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
    # A boolean, not free text: small models write "None" into a text field.
    conflict_found: bool
    recommendation: Literal[
        "answer_directly",
        "seek_joint_review",
        "apply_consistent_requirements",
        "request_more_evidence",
    ]
    uncertainty: Literal["precedence_unknown", "evidence_incomplete", "no_conflict_identified"]


CLAUSE_VERBS = re.compile(
    r"\b(?:must|may|shall|should|will|can|cannot|is|are|was|were|be|requires?|has|have|"
    r"keeps?|retains?|deletes?|applies|allows?|prohibits?|needs?)\b",
    re.I,
)


def is_heading(sentence):
    """A document title line ("Orion privacy schedule.") is not a requirement.

    Short verbless fragments are dropped so they cannot be selected as support or be
    pasted into the summary. Any sentence with a modal or main verb is kept.
    """
    words = re.findall(r"[\w'-]+", sentence)
    return (
        0 < len(words) <= 6
        and words[0].lower() not in {"the", "a", "an", "this", "these", "all", "each"}
        and not CLAUSE_VERBS.search(sentence)
    )


def restates(question, analysis):
    """True when the model's analysis only echoes the user's request."""
    terms = set(re.findall(r"[a-z0-9]{3,}", analysis.lower()))
    asked = set(re.findall(r"[a-z0-9]{3,}", question.lower()))
    return bool(terms) and len(terms - asked) <= max(1, len(terms) // 8)


async def compare_passages(p, goal, shown):
    passages = {
        f"P{n}": (h["id"], sentence)
        for n, (h, sentence) in enumerate(
            (
                (hit, part)
                for hit in shown
                for index, part in enumerate(re.split(r"(?<=[.!?])\s+", hit["text"]))
                if part.strip() and not (index == 0 and is_heading(part))
            ),
            1,
        )
    }
    if not passages:
        return Finding(summary="No passage available.", insufficient=True)
    schema = create_model(
        "PolicyAnalysis",
        __base__=PolicyReading,
        support=(list[Literal[tuple(passages)]], Field(max_length=12)),
    )
    result = await p.structured(
        schema,
        "Answer the question using only the passages. For a factual question, state the answer "
        "in analysis, set conflict_found false and recommendation answer_directly. If passages "
        "impose incompatible requirements, set conflict_found true and recommend joint review; "
        "never assign authority to waive a rule. If the passages do not contain the answer, say "
        "so, set uncertainty evidence_incomplete, recommendation request_more_evidence and select "
        "no support. Otherwise select only the passages that support the answer.",
        json.dumps({"question": goal, "passages": passages}),
    )
    quotes = [
        Claim(
            kind="extractive", text=passages[k][1], quote=passages[k][1], citations=[passages[k][0]]
        )
        for k in dict.fromkeys(result.support)
    ]
    recommendations = {
        "answer_directly": "",
        "seek_joint_review": "Ask the responsible policy owners to review the conflict together and document a resolution before changing operations.",
        "apply_consistent_requirements": "Apply the consistent requirements described in the cited passages.",
        "request_more_evidence": "Request the missing policy evidence before deciding.",
    }
    uncertainties = {
        "precedence_unknown": "The cited passages do not establish which requirement takes precedence.",
        "evidence_incomplete": "The available evidence leaves part of the question unresolved.",
        "no_conflict_identified": "This conclusion is limited to the passages reviewed.",
    }
    if result.conflict_found and result.recommendation in {
        "apply_consistent_requirements",
        "answer_directly",
    }:
        raise ValueError("Unresolved conflict cannot authorize implementation")
    abstained = (
        result.recommendation == "request_more_evidence"
        or result.uncertainty == "evidence_incomplete"
    )
    if not quotes and not abstained:
        raise ValueError("An answer must select at least one supporting passage")
    # A conflict summary must carry its selected premises into downstream reports,
    # including reports consumed without the separate citation pane.
    source_of = {h["id"]: h.get("source", "source") for h in shown}
    conflict = (
        "Conflicting requirements: "
        + "; ".join(f'{source_of[c.citations[0]]} says "{c.quote}"' for c in quotes)
        if result.conflict_found
        else ""
    )
    analysis = re.sub(r"\s*[(\[]P[0-9]+[)\]]", "", result.analysis).strip()
    if restates(goal, analysis):
        analysis = ""
    return Finding(
        summary=" ".join(
            filter(
                None,
                [
                    analysis,
                    conflict,
                    recommendations[result.recommendation],
                    uncertainties[result.uncertainty],
                ],
            )
        ),
        claims=quotes,
        citations=list(dict.fromkeys(c.citations[0] for c in quotes)),
        contradictions=[conflict] if conflict else [],
        insufficient=abstained,
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


def _value(metric, value):
    return f"{value:.2%}" if metric == "margin" else f"{value:,.2f}"


async def interpret_sales(p, goal, data):
    metrics = data["metrics"]
    if not metrics or not all(m["rows"] for m in metrics):
        return Finding(summary="Insufficient period data.", insufficient=True)
    if all(len(m["rows"]) == 1 for m in metrics):
        # A single period has no trend to interpret; render the computed values directly.
        lines = [
            f"{m['metric'].capitalize()} in {m['rows'][0]['month']}: "
            f"{_value(m['metric'], m['rows'][0]['value'])}."
            for m in metrics
            if m["rows"][0]["value"] is not None
        ]
        if not lines:
            return Finding(summary="Insufficient period data.", insufficient=True)
        return Finding(summary=" ".join(lines) + " A single period does not establish a trend.")
    if not all(m["absolute_change"] is not None for m in metrics):
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
        if m["metric"] == "margin":
            change = f"{delta:+.2%} points"
        else:
            pct = f"{m['growth']:+.2%}" if m["growth"] is not None else "undefined relative change"
            change = f"{delta:+,.2f}, {pct}"
        lines.append(
            f"{m['metric'].capitalize()} from {first['month']} to {last['month']}: "
            f"{_value(m['metric'], first['value'])} to {_value(m['metric'], last['value'])} "
            f"({change})."
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


INVOICE_STATUS = re.compile(
    r"\b(?:overdue|past[- ]due|late|delinquent|outstanding|unpaid|collections?)\b", re.I
)


class InventoryReading(StrictModel):
    criterion: Literal["below_threshold", "at_or_below_threshold", "all_items"]


async def interpret_inventory(p, goal, data):
    """The model chooses which stock condition was asked about; the host applies it."""
    reading = await p.structured(
        InventoryReading,
        "Choose the stock condition the request asks about. 'below' means quantity less than "
        "the reorder threshold; 'at or below' includes equality; all_items lists everything.",
        json.dumps({"request": goal}),
    )
    rows = data.get("rows", [])
    test = {
        "below_threshold": lambda r: r["quantity"] < r["threshold"],
        "at_or_below_threshold": lambda r: r["quantity"] <= r["threshold"],
        "all_items": lambda r: True,
    }[reading.criterion]
    label = {
        "below_threshold": "Below reorder threshold (quantity < threshold)",
        "at_or_below_threshold": "At or below reorder threshold (quantity <= threshold)",
        "all_items": "Current stock",
    }[reading.criterion]
    selected = [r for r in rows if test(r)]
    listing = (
        ", ".join(f"{r['sku']} ({r['quantity']} of {r['threshold']})" for r in selected) or "none"
    )
    summary = f"{label}: {listing}."
    equal = [r for r in rows if r["quantity"] == r["threshold"]]
    if reading.criterion == "below_threshold" and equal:
        summary += (
            " Exactly at threshold and therefore excluded: "
            + ", ".join(r["sku"] for r in equal)
            + "."
        )
    return Finding(summary=summary)
