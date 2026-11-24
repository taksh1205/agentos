import pytest

from agentos import grounded
from agentos.verification import assess_finding


class Response:
    def __init__(self, payload):
        self.payload = payload

    async def structured(self, schema, *_):
        return schema.model_validate(self.payload)


@pytest.mark.asyncio
async def test_decline_with_changed_months_and_amounts():
    evidence = {
        "dataset": "sales",
        "metrics": [
            {
                "metric": "profit",
                "rows": [{"month": "2025-08", "value": 12000}, {"month": "2025-09", "value": 9000}],
                "absolute_change": -3000,
                "growth": -0.25,
            }
        ],
    }
    answer = await grounded.interpret_sales(
        Response({"focus": "profit", "direction": "decrease"}), "Compare profit", evidence
    )
    assert "-25.00%" in answer.summary and "9,000.00" in answer.summary
    assert not assess_finding(answer.model_dump(), [], evidence)["errors"]
    with pytest.raises(ValueError):
        await grounded.interpret_sales(
            Response({"focus": "profit", "direction": "increase"}), "Compare profit", evidence
        )


@pytest.mark.asyncio
async def test_invoice_selection_is_checked_before_rendering():
    row = {"number": "BILL-77", "amount": 47.5, "due": "2025-06-12", "paid": 0}
    evidence = {"as_of": "2025-06-13", "rows": [row], "overdue_rows": [row], "overdue_total": 47.5}
    report = await grounded.interpret_overdue(
        Response({"numbers": ["BILL-77"], "next_step": "review_for_followup"}),
        "Overdue bills",
        evidence,
    )
    assert "BILL-77" in report.summary and "$47.50" in report.summary
    with pytest.raises(ValueError):
        await grounded.interpret_overdue(
            Response({"numbers": [], "next_step": "no_followup_needed"}), "Overdue bills", evidence
        )


def test_requested_metrics_distinguishes_profit_from_margin():
    assert grounded.requested_metrics("Compare expenses and profit margins") == ["costs", "margin"]
    assert grounded.requested_metrics("Compare sales and expenses") == ["revenue", "costs"]
    assert grounded.requested_metrics("Assess the sales ledger") == []


def test_approval_operator_checks_all_amounts_and_identifiers():
    from agentos.release_check import approved_invoice_body

    rows = [{"number": "INV-093", "amount": 3721.50}]
    assert approved_invoice_body("INV-093 is overdue for $3,721.50.", rows)
    assert not approved_invoice_body("INV-093 is overdue for $3,721.51.", rows)
    assert not approved_invoice_body("INV-093 owes $3,721.50 plus $77.", rows)
    assert not approved_invoice_body("INV-092 owes $3,721.50.", rows)


def test_dense_only_paraphrase_survives_but_weak_unmatched_tail_is_dropped():
    primary = {"dense_score": 0.8, "lexical_score": 3}
    paraphrase = {"dense_score": 0.66, "lexical_score": 0}
    weak = {"dense_score": 0.09, "lexical_score": 0}
    assert grounded.synthesis_candidates([primary, paraphrase, weak]) == [primary, paraphrase]


@pytest.mark.asyncio
async def test_unresolved_cold_storage_conflict_cannot_authorize_implementation():
    hits = [
        {"id": "E1", "text": "The cold room must stay below four degrees."},
        {"id": "E2", "text": "The cold room must stay above six degrees."},
    ]
    selection = {
        "analysis": "The two rules cannot both be satisfied.",
        "conflict": "The minimum exceeds the maximum.",
        "recommendation": "apply_consistent_requirements",
        "uncertainty": "precedence_unknown",
        "support": ["P1", "P2"],
    }
    with pytest.raises(ValueError, match="Unresolved conflict"):
        await grounded.compare_passages(Response(selection), "Assess storage temperatures", hits)
    selection["recommendation"] = "seek_joint_review"
    finding = await grounded.compare_passages(
        Response(selection), "Assess storage temperatures", hits
    )
    assert finding.citations == ["E1", "E2"]
    assert "before changing operations" in finding.summary
    assert all(hit["text"] in finding.summary for hit in hits)


def test_named_report_target_excludes_task_writes():
    goal = "Prepare a warehouse follow-up and store the management report."
    model = grounded.selection_schema(goal, True)
    with pytest.raises(ValueError):
        model(primary="inventory_retrieval", write="create_followup")
    assert model(primary="inventory_retrieval", write="create_report").write == "create_report"
    assert grounded.selection_schema(goal, False) is grounded.ReadSelection
    assert grounded.selection_schema(goal + " Also create a task.", True) is grounded.Selection


def test_report_title_preserves_words_and_short_first_sentence():
    from agentos.graph import report_title

    assert report_title("April arrears. Save for review.") == "April arrears"
    result = report_title("Operations review " * 25)
    assert len(result) <= 160 and result.endswith(("review…", "Operations…"))


def test_operator_rejects_transposed_invoice_amounts():
    from agentos.release_check import approved_invoice_body

    expected = [{"number": "INV-14", "amount": 12}, {"number": "INV-18", "amount": 21}]
    assert not approved_invoice_body("INV-14 owes $21 and INV-18 owes $12", expected)
    assert approved_invoice_body("INV-14 owes $12 and INV-18 owes $21", expected)


def test_supported_quote_does_not_clear_review_for_extra_narrative():
    quote = "Safety permits are issued weekly."
    finding = {
        "summary": quote + " Management has endorsed this frequency.",
        "claims": [{"kind": "extractive", "citations": ["q"], "quote": quote, "text": quote}],
    }
    outcome = assess_finding(finding, [{"id": "q", "text": quote}])
    assert outcome["fully_checked"] and outcome["requires_review"]
