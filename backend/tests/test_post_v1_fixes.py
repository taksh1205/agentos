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
