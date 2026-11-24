"""Regressions for defects found during the GitHub release review."""

import json

import httpx
import pytest

from agentos import grounded
from agentos.graph import constrained, planner_profile
from agentos.models import Provider, ProviderError, SearchQuery
from agentos.verification import narrative_issues

INVOICES = {
    "rows": [
        {"number": "INV-001", "amount": 2500.0, "paid": 0, "due": "2026-03-01"},
        {"number": "INV-002", "amount": 900.0, "paid": 1, "due": "2026-03-10"},
    ],
    "overdue_rows": [{"number": "INV-001", "amount": 2500.0, "paid": 0, "due": "2026-03-01"}],
    "as_of": "2026-04-01",
    "overdue_total": 2500.0,
    "unpaid_total": 2500.0,
}


@pytest.mark.parametrize(
    "text",
    [
        # Verbatim from the rejected Qwen2.5-1.5B proposal in docs/archive (records/C.json).
        "Overdue Invoices: There were no overdue invoices identified as of 2026-04-01.",
        "No action is required as there are no overdue invoices.",
        "None are overdue.",
        "All invoices are paid.",
    ],
)
def test_blanket_no_overdue_claim_is_rejected_when_records_are_overdue(text):
    assert "invoice_overdue_status_mismatch" in narrative_issues(text, INVOICES)


@pytest.mark.parametrize(
    "text",
    [
        "INV-001 is overdue for $2,500.00.",
        "No other invoices are overdue besides INV-001.",
    ],
)
def test_correct_invoice_statements_are_not_flagged(text):
    assert narrative_issues(text, INVOICES) == []


def test_blanket_claim_is_accepted_when_nothing_is_overdue():
    clear = {**INVOICES, "overdue_rows": [], "overdue_total": 0.0}
    assert narrative_issues("There are no overdue invoices.", clear) == []


def test_title_lines_are_not_selectable_support():
    assert grounded.is_heading("Orion privacy schedule.")
    assert grounded.is_heading("East depot inventory policy.")
    assert not grounded.is_heading("The cafeteria serves rice at lunchtime.")
    assert not grounded.is_heading("The lab must delete images within four months.")


class Scripted:
    def __init__(self, payload):
        self.payload = payload
        self.seen = None

    async def structured(self, schema, _system, payload):
        self.seen = json.loads(payload)
        return schema.model_validate(self.payload)


@pytest.mark.asyncio
async def test_research_summary_drops_headings_and_echoed_question():
    goal = (
        "Compare the retention requirements for Orion inspection images in the quality "
        "manual and the privacy schedule."
    )
    shown = [
        {
            "id": "quality",
            "source": "quality-manual",
            "text": "Orion quality manual. The lab must retain Orion inspection images for "
            "at least nine months to support audit appeals.",
        },
        {
            "id": "privacy",
            "source": "privacy-schedule",
            "text": "Orion privacy schedule. The lab must delete Orion inspection images within "
            "four months to limit personal data exposure.",
        },
    ]
    model = Scripted(
        {
            "analysis": goal,  # the failure mode: the model restates the request
            "conflict": "Retention minimum exceeds deletion deadline.",
            "recommendation": "seek_joint_review",
            "uncertainty": "precedence_unknown",
            "support": ["P1", "P2"],
        }
    )
    finding = await grounded.compare_passages(model, goal, shown)
    assert "Orion privacy schedule." not in finding.summary
    assert "Orion quality manual." not in finding.summary
    assert not finding.summary.startswith("Compare the retention")
    assert 'privacy-schedule says "The lab must delete' in finding.summary
    assert 'quality-manual says "The lab must retain' in finding.summary
    assert all(not grounded.is_heading(text) for _, text in model.seen["passages"].values())
    assert finding.citations == ["quality", "privacy"]


def test_planner_profile_is_explicit(monkeypatch):
    monkeypatch.delenv("PLANNER_PROFILE", raising=False)
    monkeypatch.delenv("OPENAI_PLAN_PROFILE", raising=False)
    assert planner_profile() == "general"
    monkeypatch.setenv("OPENAI_PLAN_PROFILE", "capability")
    assert planner_profile() == "constrained"
    monkeypatch.setenv("PLANNER_PROFILE", "general")
    assert planner_profile() == "general"
    # The constrained profile is provider-neutral and never applies to offline rules.
    monkeypatch.setenv("PLANNER_PROFILE", "constrained")
    assert constrained({"mode": "anthropic"}) and constrained({"mode": "openai"})
    assert not constrained({"mode": "demo"})
    monkeypatch.setenv("PLANNER_PROFILE", "autonomous")
    with pytest.raises(ValueError):
        planner_profile()


def openai_reply(body):
    return httpx.Response(
        200,
        json={
            "id": "r",
            "object": "chat.completion",
            "created": 1,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c",
                                "type": "function",
                                "function": {
                                    "name": "emit_result",
                                    "arguments": json.dumps({"query": "q"}),
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 40,
                "total_tokens": 50,
                "completion_tokens_details": {"reasoning_tokens": 32},
            },
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,base_url,expected",
    [
        ("gpt-5-mini", None, {"max_completion_tokens", "reasoning_effort"}),
        ("gpt-4.1-mini", None, {"max_completion_tokens"}),
        ("qwen-local", "http://127.0.0.1:9/v1", {"max_tokens"}),
    ],
)
async def test_openai_token_parameters_match_endpoint(model, base_url, expected, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-transport-only")
    if base_url:
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    else:
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return openai_reply(bodies[-1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = Provider("openai", model, http_client=client)
        await provider.structured(SearchQuery, "s", "p")
    keys = {"max_tokens", "max_completion_tokens", "reasoning_effort"}
    assert keys & set(bodies[0]) == expected
    if "reasoning_effort" in expected:
        assert provider.records[0]["reasoning_tokens"] == 32


@pytest.mark.asyncio
async def test_anthropic_required_tool_choice_uses_any(monkeypatch):
    import httpx2

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-transport-only")
    monkeypatch.setenv("MODEL_TOOL_CHOICE", "required")
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [
                    {"type": "tool_use", "id": "c", "name": "emit_result", "input": {"query": "q"}}
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 5, "output_tokens": 5},
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        await Provider("anthropic", "test-model", http_client=client).structured(
            SearchQuery, "s", "p"
        )
    assert bodies[0]["tool_choice"] == {"type": "any"}


@pytest.mark.asyncio
async def test_exhausted_quota_is_not_retried(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-transport-only")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    calls = []

    def respond(request):
        calls.append(1)
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "You exceeded your current quota.",
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderError):
            await Provider("openai", "gpt-4.1-mini", http_client=client).structured(
                SearchQuery, "s", "p"
            )
    assert len(calls) == 1


def test_unrequested_writes_are_removed_from_auto_plans():
    from agentos.coordination import drop_unrequested_writes, requests_write
    from agentos.models import Plan, Step

    plan = Plan(
        steps=[
            Step(id="0", agent="data", instruction="i", tool="business_metrics"),
            Step(id="w", agent="action", instruction="i", tool="create_report", dependencies=["0"]),
            Step(
                id="n",
                agent="action",
                instruction="i",
                tool="create_notification",
                dependencies=["w"],
            ),
        ]
    )
    goal = "Analyze February and March 2026 revenue month over month."
    assert not requests_write(goal)
    kept, dropped = drop_unrequested_writes(plan, goal)
    assert [s.id for s in kept.steps] == ["0"] and dropped == ["n", "w"]
    # An explicit request keeps the write.
    kept, dropped = drop_unrequested_writes(plan, goal + " Save the report after approval.")
    assert len(kept.steps) == 3 and dropped == []
    # A plan made only of unrequested writes becomes an explicit refusal, never a mutation.
    only = Plan(steps=[Step(id="x", agent="action", instruction="i", tool="update_inventory")])
    refused, _ = drop_unrequested_writes(only, "Wipe the database")
    assert refused.refusal and not refused.steps


def test_explicit_periods_bind_only_unambiguous_text():
    from agentos.graph import explicit_periods

    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert explicit_periods("February and March 2026", months) == ("2026-02", "2026-03")
    assert explicit_periods("from April through June 2026", months) == ("2026-04", "2026-06")
    assert explicit_periods("margin in May 2026", months) == ("2026-05", "2026-05")
    assert explicit_periods("Analyze revenue", months) is None
    assert explicit_periods("Compare January and March", months) is None  # not contiguous


def test_client_model_choice_requires_operator_allowlist(monkeypatch):
    from fastapi import HTTPException

    from agentos.api import check_model_choice

    monkeypatch.delenv("ALLOWED_MODELS", raising=False)
    monkeypatch.setenv("DEPLOYMENT", "local")
    check_model_choice("openai", "any-local-model")  # permissive local demo
    check_model_choice("demo", "ignored")
    monkeypatch.setenv("DEPLOYMENT", "shared")
    with pytest.raises(HTTPException) as denied:
        check_model_choice("openai", "gpt-expensive")
    assert denied.value.status_code == 403
    check_model_choice("openai", None)  # server default model is always allowed
    monkeypatch.setenv("ALLOWED_MODELS", "gpt-4.1-mini, claude-haiku-4-5")
    check_model_choice("openai", "gpt-4.1-mini")
    with pytest.raises(HTTPException):
        check_model_choice("anthropic", "claude-opus-4-1")
