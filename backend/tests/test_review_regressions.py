import pytest

from agentos.graph import offline_action, offline_intent, offline_plan
from agentos.offline import extractive_finding, period_bounds


@pytest.mark.parametrize(
    "goal, expected",
    [
        ("February 2027 costs", ("2027-02", "2027-02")),
        ("costs from 2027-02 through 2027-05", ("2027-02", "2027-05")),
        ("Revenue through Mar", (None, "2028-03")),
        ("February profit", ("2028-02", "2028-02")),
        ("Revenue since 2029-12", ("2029-12", None)),
    ],
)
def test_ground_period_from_request_or_workspace(goal, expected):
    assert period_bounds(goal, ["2028-02", "2028-03"]) == expected


def test_ambiguous_year_never_broadens_query():
    with pytest.raises(ValueError, match="calendar year"):
        offline_intent("March costs", ["2025-03", "2026-03"])
    with pytest.raises(ValueError, match="contiguous"):
        offline_intent("January and March costs", ["2025-01", "2025-03"])


def test_report_write_depends_on_analysis():
    plan = offline_plan({"goal": "Compute costs and store the outcome in a memo"})
    assert [s.agent for s in plan.steps] == ["data", "action"]
    assert plan.steps[-1].dependencies == [plan.steps[0].id]
    assert offline_action("Export invoices to CSV").arguments["dataset"] == "invoices"


def evidence(i, body):
    return {"id": str(i), "source": f"Bulletin {i}", "text": body}


def test_conflict_requires_matching_subject_date_unit_and_distinct_sources():
    a = evidence(1, "The North office limit is 60 seats, dated June 2.")
    b = evidence(2, "The North office limit is 45 seats, dated June 2.")
    conflict = extractive_finding(
        "What is the North office limit?", [a, b, evidence(3, "Unrelated passage.")]
    )
    assert (
        conflict.insufficient and conflict.contradictions and set(conflict.citations) == {"1", "2"}
    )
    for changed in [
        b["text"].replace("June 2", "June 3"),
        b["text"].replace("North", "South"),
        b["text"].replace("seats", "hours"),
        a["text"],
    ]:
        assert not extractive_finding(
            "North office limit?", [a, evidence(2, changed)]
        ).contradictions


def test_explicit_missing_fact_is_qualified():
    finding = extractive_finding(
        "What is the renewal surcharge?",
        [evidence(1, "This schedule does not specify a renewal surcharge.")],
    )
    assert finding.insufficient and finding.citations == ["1"]


def test_invalid_postcondition_is_rejected_before_a_proposal():
    from agentos.coordination import validate_capabilities
    from agentos.models import Plan

    plan = Plan(
        steps=[
            dict(
                id="one",
                agent="action",
                tool="create_notification",
                instruction="Notify the team",
                checks=[dict(kind="metric", metric="profit", expected=900)],
            )
        ]
    )
    with pytest.raises(ValueError, match="cannot be established"):
        validate_capabilities(plan)


def test_compact_plan_validates_dependencies_and_derives_tool_ownership():
    from agentos.coordination import expand_capability_plan
    from agentos.models import CapabilityPlan

    plan = CapabilityPlan(
        tasks=[
            dict(capability="invoice_analysis", instruction="Check pending balances"),
            dict(capability="create_followup", instruction="Log a follow-up", after=[0]),
        ]
    )
    result = expand_capability_plan(plan)
    assert [s.agent for s in result.steps] == ["data", "action"]
    assert result.steps[-1].dependencies == ["0"] and result.steps[-1].requires_approval
    plan.tasks[0].after = [1]
    with pytest.raises(ValueError, match="earlier"):
        expand_capability_plan(plan)


@pytest.mark.asyncio
async def test_final_veto_preserves_receipt_without_reopening_action(tmp_path):
    import json

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    from agentos.graph import build_graph
    from agentos.models import Plan, Review
    from agentos.rag import Retrieval
    from agentos.store import Store

    class Judge:
        tokens = calls = 0
        records = []

        async def structured(self, schema, system, payload):
            if schema is Plan:
                return Plan(
                    steps=[
                        dict(
                            id="action",
                            agent="action",
                            instruction="Notify",
                            tool="create_notification",
                            arguments={"message": "Review ready"},
                        )
                    ]
                )
            assert schema is Review
            return Review(
                supported=json.loads(payload)["phase"] == "pre_action", issues=["needs review"]
            )

    store = Store("sqlite:///" + str(tmp_path / "db"))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        graph = build_graph(store, Retrieval(store), cp, provider_factory=lambda *_: Judge())
        config = {"configurable": {"thread_id": "failed-review"}}
        out = await graph.ainvoke(
            dict(goal="Notify", mode="openai", workspace="a", run_id="x", results=[], events=[]),
            config,
        )
        assert "__interrupt__" in out
        out = await graph.ainvoke(Command(resume=True), config)
        assert "__interrupt__" not in out and out["report"]["status"] == "failed"
        assert len(store.execute("SELECT * FROM effects")) == 1


async def test_compatible_json_protocol_uses_real_sdk_and_validates_content(monkeypatch):
    import json

    import httpx

    from agentos.models import Provider, SearchQuery

    monkeypatch.setenv("OPENAI_API_KEY", "mock-only")
    monkeypatch.setenv("OPENAI_STRUCTURED_OUTPUT", "json_schema")

    def respond(request):
        packet = json.loads(request.content)
        assert "tools" not in packet
        assert packet["response_format"]["json_schema"]["schema"]["title"] == "SearchQuery"
        return httpx.Response(
            200,
            json={
                "id": "r",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"query": "renewal date"}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = Provider("openai", "test", http_client=client)
        assert (await provider.structured(SearchQuery, "Rewrite", "term?")).query == "renewal date"
        assert provider.records[-1]["protocol"] == "json_schema" and provider.tokens == 13
