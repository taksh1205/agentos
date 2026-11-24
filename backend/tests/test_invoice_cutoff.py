from datetime import date

import pytest
from pydantic import ValidationError

from agentos.store import Store
from agentos.tools import ToolService


@pytest.mark.parametrize(
    "as_of,expected", [("2026-03-31", 0), ("2026-04-01", 2500), ("2026-04-16", 3300)]
)
def test_overdue_is_strictly_before_cutoff_and_unpaid(tmp_path, as_of, expected):
    store = Store("sqlite:///" + str(tmp_path / "invoice.sqlite"))
    store.seed("a")
    service = ToolService(store, None)
    assert service.invoke("other", "invoice_analysis", {"as_of": as_of})["overdue_rows"] == []
    result = service.invoke("a", "invoice_analysis", {"as_of": as_of})
    assert result["overdue_total"] == expected
    assert result["unpaid_total"] == 3300
    assert all(
        not row["paid"] and date.fromisoformat(row["due"]) < date.fromisoformat(as_of)
        for row in result["overdue_rows"]
    )
    with pytest.raises(ValidationError):
        service.invoke("a", "invoice_analysis", {"as_of": "2026-02-31"})


def test_ordered_plan_compiles_requested_barriers_and_independent_reads():
    from agentos.coordination import expand_capability_plan
    from agentos.models import OrderedPlan

    chosen = OrderedPlan.model_validate(
        {
            "tasks": [
                {
                    "capability": "document_search",
                    "instruction": "Read policies",
                    "uses_prior_results": False,
                },
                {
                    "capability": "business_metrics",
                    "instruction": "Compute changes",
                    "uses_prior_results": False,
                },
                {
                    "capability": "create_report",
                    "instruction": "Save the verified analysis",
                    "uses_prior_results": True,
                },
            ]
        }
    )
    steps = expand_capability_plan(chosen.indexed()).steps
    assert [s.dependencies for s in steps] == [[], [], ["0", "1"]]
    assert steps[2].requires_approval


def test_offline_invoice_as_of_and_report_intent():
    from agentos.graph import offline_action, offline_intent

    goal = "Review overdue invoices as of 2026-04-01 and save the follow-up report."
    assert offline_intent(goal).as_of == "2026-04-01"
    assert offline_action(goal).tool == "create_report"
    assert offline_intent("Review revenue and expenses").metrics == ["revenue", "costs"]


def test_readonly_wire_schema_excludes_mutations():
    from agentos.models import ReadOnlyPlan

    with pytest.raises(ValidationError):
        ReadOnlyPlan.model_validate(
            {
                "tasks": [
                    {
                        "capability": "create_report",
                        "instruction": "Write",
                        "uses_prior_results": False,
                    }
                ]
            }
        )
    assert "create_report" not in str(ReadOnlyPlan.model_json_schema())


def test_compact_synthesis_preserves_citations_and_rejects_a_misquote():
    from agentos.models import CitedSynthesis
    from agentos.verification import assess_finding

    synthesis = CitedSynthesis(
        summary="A disputed limit.",
        evidence=[{"source": "E1", "quote": "Maximum twelve pallets."}],
        contradictions=[],
        insufficient=False,
    )
    finding = synthesis.finding().model_dump()
    assert finding["citations"] == ["E1"]
    assert assess_finding(finding, [{"id": "E1", "text": "Maximum twelve pallets."}])[
        "fully_checked"
    ]
    assert assess_finding(finding, [{"id": "E1", "text": "Maximum twenty pallets."}])["errors"]


def test_sales_tool_returns_weighted_margin_and_handles_zero_revenue(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "sales.db"))
    store.seed("a")
    store.execute("UPDATE sales SET revenue=0 WHERE workspace='a' AND month='2026-02'")
    report = store.analytics("a", "margin")
    assert report["rows"][1]["value"] is None
    assert report["total"] == pytest.approx((250000 - 238000) / 250000)


def test_compact_model_trend_is_checked_against_source_rows(tmp_path):
    from agentos.models import ComputedInterpretation
    from agentos.verification import assess_finding

    store = Store("sqlite:///" + str(tmp_path / "sales.db"))
    store.seed("a")
    data = store.analyze("a", {"metrics": ["profit"]})
    wrong = ComputedInterpretation(
        summary="Profit fell.",
        insufficient=False,
        trends=[
            {
                "metric": "profit",
                "start": "2026-02",
                "end": "2026-03",
                "basis": "mom",
                "direction": "decrease",
            }
        ],
    )
    assert assess_finding(wrong.finding().model_dump(), [], data)["errors"]


def test_calendar_years_and_invented_invoice_amounts(tmp_path):
    from agentos.verification import narrative_issues

    store = Store("sqlite:///" + str(tmp_path / "records.db"))
    store.seed("a")
    sales = store.analyze("a", {"metrics": ["revenue"]})
    assert not narrative_issues("February 2026 revenue was 120000.", sales)
    assert narrative_issues("February 2027 revenue was 120000.", sales)
    invoice = ToolService(store, None).invoke("a", "invoice_analysis", {"as_of": "2026-04-01"})
    assert not narrative_issues("INV-001 is overdue for $2,500.", invoice)
    assert narrative_issues("INV-077 is overdue for $9,000.", invoice)


def test_two_valid_amounts_cannot_be_swapped_between_invoices(tmp_path):
    from agentos.verification import narrative_issues

    store = Store("sqlite:///" + str(tmp_path / "invoice.db"))
    store.seed("a")
    evidence = ToolService(store, None).invoke("a", "invoice_analysis", {"as_of": "2026-04-01"})
    assert "invoice_amount_mismatch" in narrative_issues(
        "INV-001 has an overdue balance of $800.", evidence
    )
    assert "invoice_overdue_status_mismatch" in narrative_issues("INV-003 is overdue.", evidence)
    assert not narrative_issues("INV-003 is not overdue. INV-001 is overdue for $2,500.", evidence)


def test_adjacent_named_months_bind_mom_without_filling_gaps():
    from agentos.offline import period_bounds

    available = ["2026-01", "2026-02", "2026-03"]
    assert period_bounds("February and March 2026 revenue", available) == ("2026-02", "2026-03")
    with pytest.raises(ValueError):
        period_bounds("January and March 2026 revenue", available)
