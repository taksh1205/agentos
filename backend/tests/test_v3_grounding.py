import pytest

from agentos.models import Plan
from agentos.verification import assess_claim, narrative_issues, numeric_claim

DATA = {
    "dataset": "sales",
    "metrics": [
        {
            "metric": "revenue",
            "rows": [{"month": "2026-01", "value": 100}, {"month": "2026-02", "value": 80}],
            "total": 180,
            "absolute_change": -20,
        }
    ],
}


def test_wrong_direction_with_valid_numbers():
    assert "trend_direction_contradiction" in narrative_issues(
        "Revenue increased from 100 to 80.", DATA
    )


def test_wrong_yearly_basis():
    status, reason = numeric_claim(
        {"metric": "revenue", "operation": "growth", "value": -0.2, "basis": "yoy"}, DATA
    )
    assert status == "contradicted"
    assert reason == "yoy_requires_12_month_baseline"


def test_correct_monthly_decline():
    assert (
        numeric_claim(
            {
                "metric": "revenue",
                "operation": "growth",
                "value": -0.2,
                "basis": "mom",
                "direction": "decrease",
            },
            DATA,
        )[0]
        == "supported"
    )


def test_wrong_citation_even_with_known_id():
    sources = [{"id": "a", "text": "Vacation allowance is twenty days."}]
    assert (
        assess_claim(
            {
                "kind": "source",
                "text": "Revenue increased substantially",
                "quote": "Vacation allowance is twenty days.",
                "citations": ["a"],
            },
            sources,
        )[0]
        == "unsupported"
    )


def test_action_requires_receipt():
    assert (
        assess_claim({"kind": "action", "text": "Saved successfully", "receipt": "missing"}, [])[0]
        == "unsupported"
    )


def test_unknown_paraphrase_is_not_a_passing_score():
    assert (
        assess_claim(
            {"text": "A plausible paraphrase", "citations": ["a"]},
            [{"id": "a", "text": "Evidence"}],
        )[0]
        == "needs_review"
    )


def test_refusal_cannot_execute_steps():
    with pytest.raises(ValueError):
        Plan(refusal="Denied", steps=[{"id": "a", "agent": "action", "instruction": "Do it"}])
