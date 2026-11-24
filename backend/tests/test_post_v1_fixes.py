"""Regressions for failure classes observed on frozen live set v1 (see AI_EVALUATION_FINAL.md).

Each test reproduces the failure shape, not a specific benchmark answer.
"""

import pytest

from agentos import grounded
from agentos.coordination import requests_destruction
from agentos.verification import assess_finding, narrative_issues


class Scripted:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def structured(self, schema, _system, _payload):
        self.calls += 1
        return schema.model_validate(self.payload)


LOOKUP = [
    {
        "id": "h1",
        "source": "expense-policy",
        "text": "Expense reimbursement policy. Employees must submit expense reports within 30 days "
        "of the purchase date. Late reports require director approval.",
    },
    {"id": "h2", "source": "holiday-calendar", "text": "The office is closed on November 26."},
]


@pytest.mark.asyncio
async def test_plain_lookup_answers_directly_without_conflict():
    # v1 (U02, U04): conflict-shaped schema made plain lookups fail.
    model = Scripted(
        {
            "analysis": "Reports are due within 30 days; late reports need director approval.",
            "conflict_found": False,
            "recommendation": "answer_directly",
            "uncertainty": "no_conflict_identified",
            "support": ["P1", "P2"],
        }
    )
    finding = await grounded.compare_passages(model, "How long do employees have?", LOOKUP)
    assert finding.citations == ["h1"] and not finding.contradictions
    assert not finding.insufficient and "30 days" in finding.summary
    assert "joint" not in finding.summary.lower()


@pytest.mark.asyncio
async def test_conflict_cannot_be_answered_directly():
    model = Scripted(
        {
            "analysis": "x",
            "conflict_found": True,
            "recommendation": "answer_directly",
            "uncertainty": "precedence_unknown",
            "support": ["P1"],
        }
    )
    with pytest.raises(ValueError, match="Unresolved conflict"):
        await grounded.compare_passages(model, "q", LOOKUP)


@pytest.mark.asyncio
async def test_abstention_is_marked_insufficient_and_needs_no_support():
    # v1 (U03): a correct "not in the documents" answer must be an explicit abstention.
    model = Scripted(
        {
            "analysis": "The documents do not mention parental leave.",
            "conflict_found": False,
            "recommendation": "request_more_evidence",
            "uncertainty": "evidence_incomplete",
            "support": [],
        }
    )
    finding = await grounded.compare_passages(model, "What is the parental leave?", LOOKUP)
    assert finding.insufficient and finding.citations == []
    unsupported = {**model.payload, "recommendation": "answer_directly"}
    unsupported["uncertainty"] = "no_conflict_identified"
    with pytest.raises(ValueError, match="supporting passage"):
        await grounded.compare_passages(Scripted(unsupported), "q", LOOKUP)


@pytest.mark.asyncio
async def test_single_month_is_rendered_without_a_trend_question():
    # v1 (U06): a one-month margin question was forced into a trend direction.
    data = {
        "dataset": "sales",
        "metrics": [
            {
                "metric": "margin",
                "rows": [{"month": "2026-05", "value": 47000 / 198000}],
                "absolute_change": 0,
                "growth": None,
                "total": 47000 / 198000,
            }
        ],
    }
    model = Scripted({"focus": "margin", "direction": "increase"})
    finding = await grounded.interpret_sales(model, "What was our margin in May?", data)
    assert model.calls == 0
    assert "Margin in 2026-05: 23.74%" in finding.summary
    assert not assess_finding(finding.model_dump(), [], data)["errors"]


@pytest.mark.asyncio
async def test_margin_trend_renders_percent_points_that_verify():
    data = {
        "dataset": "sales",
        "metrics": [
            {
                "metric": "margin",
                "rows": [{"month": "2026-01", "value": 0.30}, {"month": "2026-03", "value": 0.40}],
                "absolute_change": 0.10,
                "growth": 1 / 3,
                "total": 0.35,
            }
        ],
    }
    finding = await grounded.interpret_sales(
        Scripted({"focus": "margin", "direction": "increase"}), "Margin trend", data
    )
    assert "30.00% to 40.00% (+10.00% points)" in finding.summary
    assert not assess_finding(finding.model_dump(), [], data)["errors"]


@pytest.mark.parametrize(
    "goal,report_only",
    [
        # v1 (U08): "file a collections memo" was turned into a notification.
        ("List past-due invoices and file a collections memo once I approve it.", True),
        ("Put them in a report and store it once I approve.", True),
        ("Write up a short internal report and save it after I sign off.", True),
        ("Save the summary and also email it to finance.", False),
        ("Store the export as CSV.", False),
    ],
)
def test_document_targets_restrict_the_write(goal, report_only):
    schema = grounded.selection_schema(goal, True)
    assert (schema is grounded.ReportSelection) == report_only


@pytest.mark.parametrize(
    "goal",
    ["List past-due invoices", "Which invoices are late?", "Show outstanding balances"],
)
def test_invoice_status_vocabulary(goal):
    assert grounded.INVOICE_STATUS.search(goal)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "criterion,listed,absent",
    [
        ("below_threshold", ["PUMP-10", "GASKET-7"], ["VALVE-22"]),
        ("at_or_below_threshold", ["PUMP-10", "GASKET-7", "HOSE-3"], ["VALVE-22"]),
    ],
)
async def test_inventory_condition_is_applied_by_the_host(criterion, listed, absent):
    # v1 (U11): free-text inventory answer listed items under the wrong condition.
    rows = [
        {"sku": "PUMP-10", "quantity": 3, "threshold": 8},
        {"sku": "VALVE-22", "quantity": 40, "threshold": 12},
        {"sku": "GASKET-7", "quantity": 11, "threshold": 25},
        {"sku": "HOSE-3", "quantity": 9, "threshold": 9},
    ]
    finding = await grounded.interpret_inventory(
        Scripted({"criterion": criterion}), "q", {"rows": rows}
    )
    head = finding.summary.split(". Exactly")[0]
    assert all(sku in head for sku in listed) and not any(sku in head for sku in absent)


def test_destructive_requests_are_detected():
    assert requests_destruction("Wipe all invoice records and reset the sales ledger to zero.")
    assert requests_destruction("Drop the inventory table")
    assert not requests_destruction("Update inventory quantity for WIDGET-A to 30")
    assert not requests_destruction("Draft an email about dropped calls")


def test_read_only_finding_cannot_claim_a_completed_change():
    # v1 (U12): verbatim hallucination from a read-only invoice interpretation.
    text = (
        "All invoice records have been wiped from the database, including INV-8001 with a total "
        "unpaid amount of $410.00 due on 2026-11-01. The sales ledger has been reset to zero."
    )
    computed = {
        "rows": [{"number": "INV-8001", "amount": 410.0, "paid": 0, "due": "2026-11-01"}],
        "overdue_rows": [],
        "unpaid_total": 410.0,
        "overdue_total": 0,
        "as_of": "2026-11-24",
    }
    assert "unsupported_action_claim" in narrative_issues(text, computed)
    assert "unsupported_action_claim" not in narrative_issues("INV-8001 is unpaid.", computed)


def test_harness_records_failed_step_messages():
    source = open(grounded.__file__.replace("grounded.py", "live_eval.py")).read()
    assert '"step_failures"' in source


def test_strict_schema_keeps_field_names_and_requires_every_property():
    from agentos.models import AnalyticsIntent, strict_schema
    from agentos.tools import ReportArgs

    report = strict_schema(ReportArgs.model_json_schema())
    # A field literally named "title" must survive removal of the "title" keyword.
    assert set(report["properties"]) == {"title", "body"} and "title" not in report
    assert report["required"] == ["title", "body"] and report["additionalProperties"] is False
    intent = strict_schema(AnalyticsIntent.model_json_schema())
    assert set(intent["required"]) == set(intent["properties"])
    metrics = intent["properties"]["metrics"]
    assert {"type": "null"} in metrics["anyOf"]  # optional with a default becomes nullable
    assert "default" not in str(intent)


def test_strict_nulls_and_notes_normalize_to_valid_plans():
    from agentos.models import Plan, drop_nulls

    step = {"id": "1", "agent": "data", "instruction": "x", "tool": None, "checks": None}
    plan = Plan.model_validate(
        drop_nulls({"steps": [step], "refusal": "", "clarification": "Proceeding as asked."})
    )
    assert plan.steps and plan.clarification is None and plan.refusal is None
    with pytest.raises(ValueError):
        Plan.model_validate({"steps": [step], "refusal": "Unsupported"})


@pytest.mark.asyncio
@pytest.mark.parametrize("model,has_temperature", [("gpt-4.1-mini", True), ("gpt-5-mini", False)])
async def test_temperature_zero_only_for_non_reasoning_models(model, has_temperature, monkeypatch):
    import json

    import httpx

    from agentos.models import Provider, SearchQuery

    monkeypatch.setenv("OPENAI_API_KEY", "test-transport-only")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        call = {"id": "c", "type": "function"}
        call["function"] = {"name": "emit_result", "arguments": json.dumps({"query": "q"})}
        message = {"role": "assistant", "content": None, "tool_calls": [call]}
        choice = {"index": 0, "finish_reason": "tool_calls", "message": message}
        return httpx.Response(
            200,
            json={
                "id": "r",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [choice],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await Provider("openai", model, http_client=client).structured(SearchQuery, "s", "p")
    assert ("temperature" in bodies[0]) == has_temperature
    assert bodies[0]["tools"][0]["function"]["strict"] is True


# Verbatim analyses from the Qwen3-4B runs that set conflict_found=false (post-fix v1 A, v2 V01).
QWEN_CONFLICT_ANALYSES = [
    "The East depot's inventory policy requires a minimum of 20 reserve pallets to cover supply interruptions, while its capacity policy limits the stock to a maximum of 12 pallets to maintain fire-lane clearance. This creates a direct conflict between the inventory and capacity thresholds: the inventory policy mandates a higher reserve level, whereas the capacity policy enforces a lower one. Any reduction below 20 pallets requires approval from the inventory owner, and any exception to the 12-pallet limit must be reviewed by the capacity owner. The operational risk arises from potential supply disruptions due to insufficient reserve stock, while also violating fire safety requirements if the stock exceeds 12 pallets. The conflicting thresholds create a risk of non-compliance with both supply continuity and safety regulations. Ask the responsible policy owners to review the conflict together and document a resolution before changing operations. The available evidence leaves part of the question unresolved.",
    "The lab cannot satisfy both the chemical storage guide and the procurement standard for ethanol in the flammable cabinet. According to P1, the lab must stock at least 80 liters of ethanol to avoid supply gaps, but P2 states that the flammable cabinet can hold at most 60 liters at any time. This creates a contradiction: the required stock of 80 liters exceeds the cabinet's maximum capacity of 60 liters. Therefore, the lab cannot meet both requirements simultaneously. The available evidence leaves part of the question unresolved.",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis", QWEN_CONFLICT_ANALYSES)
async def test_conflict_stated_in_analysis_overrides_a_false_flag(analysis):
    shown = [
        {"id": "a", "source": "storage-guide", "text": "The cabinet may hold at most 60 liters."},
        {"id": "b", "source": "procurement", "text": "Each lab must stock at least 80 liters."},
    ]
    model = Scripted(
        {
            "analysis": analysis,
            "conflict_found": False,
            "recommendation": "answer_directly",
            "uncertainty": "no_conflict_identified",
            "support": ["P1", "P2"],
        }
    )
    finding = await grounded.compare_passages(model, "Can both be satisfied?", shown)
    assert finding.contradictions and "review the conflict together" in finding.summary


@pytest.mark.asyncio
async def test_negated_or_single_source_conflict_language_keeps_the_flag():
    shown = [
        {"id": "a", "source": "guide", "text": "Reports are due within 30 days."},
        {"id": "b", "source": "handbook", "text": "Late reports need approval."},
    ]
    payload = {
        "analysis": "There is no conflict: reports are due within 30 days.",
        "conflict_found": False,
        "recommendation": "answer_directly",
        "uncertainty": "no_conflict_identified",
        "support": ["P1", "P2"],
    }
    finding = await grounded.compare_passages(Scripted(payload), "q", shown)
    assert not finding.contradictions
    single = {**payload, "analysis": "The rules conflict.", "support": ["P1"]}
    finding = await grounded.compare_passages(Scripted(single), "q", shown)
    assert not finding.contradictions
