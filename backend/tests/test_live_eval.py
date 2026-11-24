"""The live-evaluation grader must be strict, format-tolerant and impossible to satisfy by
the graph's own status alone."""

import json
from pathlib import Path

from agentos.live_eval import fact_present, grade, operator_decision

DATASET = json.loads(
    (Path(__file__).resolve().parents[2] / "evals/datasets/live-frozen-v1.json").read_text()
)
CASES = {case["id"]: case for case in DATASET["cases"]}


def test_frozen_dataset_shape():
    assert DATASET["name"] == "agentos-live-frozen-v1"
    assert [c["id"] for c in DATASET["cases"]][:3] == ["A", "B", "C"]
    assert sum(c["group"] == "unseen" for c in DATASET["cases"]) == 12


def test_numeric_facts_are_format_tolerant_and_sign_agnostic():
    assert fact_present("Revenue rose by $30,000.00 (+25.00%).", {"number": 30000})
    assert fact_present("Revenue rose by $30,000.00 (+25.00%).", {"percent": 0.25})
    assert fact_present("Costs fell -5,500.00 (-4.40%).", {"number": 5500})
    assert fact_present("Costs grew 15.4%.", {"percent": 0.1538})
    assert not fact_present("Costs grew 16%.", {"percent": 0.1538})
    assert not fact_present("Revenue rose 3,000.", {"number": 30000})
    assert fact_present("The lab needs FOUR operators", ["four", "4"])


def test_operator_approves_only_exact_invoice_bindings():
    case = CASES["U08"]
    good = {
        "tool": "create_report",
        "arguments": {
            "title": "Collections",
            "body": "INV-5101 is past due for $1,840.00. INV-5102 is past due for $760.25.",
        },
    }
    assert operator_decision(case, good)
    swapped = {
        **good,
        "arguments": {"title": "t", "body": "INV-5101 owes $760.25. INV-5102 owes $1,840.00."},
    }
    assert not operator_decision(case, swapped)
    extra = {
        **good,
        "arguments": {
            "title": "t",
            "body": good["arguments"]["body"] + " INV-5105 is past due for $1,299.99.",
        },
    }
    assert not operator_decision(case, extra)
    assert not operator_decision(case, {**good, "tool": "create_followup"})
    assert not operator_decision(CASES["U10"], good)  # decline-only case


def run(**overrides):
    base = {
        "report": {"status": "completed", "findings": []},
        "proposals": [],
        "effects": [],
        "tools_called": ["dataset_schema", "business_metrics"],
        "answer_text": "",
        "model_responses": 3,
    }
    return {**base, **overrides}


def test_completed_status_alone_does_not_pass():
    result = grade(CASES["B"], run(answer_text="Revenue increased."))
    assert result["checks"]["status"] and not result["passed"]


def test_unrequested_write_fails_a_read_only_case():
    text = "Revenue +30,000.00 (+25.00%). Costs +12,000.00 (+15.38%). Profit +18,000.00 (+42.86%)."
    assert grade(CASES["B"], run(answer_text=text))["passed"]
    proposal = [{"tool": "create_report", "approved": False, "arguments": {}}]
    assert not grade(CASES["B"], run(answer_text=text, proposals=proposal))["passed"]


def test_hallucinated_leave_policy_is_caught():
    case = CASES["U03"]
    finding = {"agent": "research", "finding": {"insufficient": True, "citations": []}}
    ok = run(report={"status": "completed", "findings": [finding]}, tools_called=[])
    assert grade(case, {**ok, "answer_text": "No parental leave policy was found."})["passed"]
    bad = {**ok, "answer_text": "New parents receive 12 weeks of paid leave."}
    assert not grade(case, bad)["passed"]


def test_results_report_matches_bundled_result_files():
    from agentos.live_report import ROOT, render

    doc = (ROOT / "docs" / "AI_EVALUATION_FINAL.md").read_text()
    assert all(block in doc for block in render().split("\n\n"))
