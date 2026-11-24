import json

import httpx
import pytest

from agentos.coordination import context_packet
from agentos.models import Plan, Provider, ProviderError
from agentos.tools import ToolService


def test_explicit_empty_scopes_deny_access():
    with pytest.raises(PermissionError):
        ToolService(None, None).invoke("tenant", "dataset_schema", {}, scopes=[])


def test_dependency_packet_excludes_siblings_and_failed_results():
    plan = [
        {"id": "lookup", "dependencies": []},
        {"id": "analysis", "dependencies": ["lookup"]},
        {"id": "other", "dependencies": []},
    ]
    state = {
        "plan": plan,
        "results": [
            {"step": r["id"], "agent": "research", "ok": r["id"] != "analysis"} for r in plan
        ],
    }
    assert [row["step"] for row in context_packet(state, {"dependencies": ["analysis"]})] == [
        "lookup"
    ]


@pytest.mark.asyncio
async def test_malformed_billed_response_is_counted(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-only")
    monkeypatch.setenv("MODEL_PRICES", json.dumps({"metered": {"input": 1, "output": 2}}))
    data = {
        "id": "mock",
        "object": "chat.completion",
        "created": 1,
        "model": "metered",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "no tool call"}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    ) as client:
        p = Provider("openai", "metered", http_client=client)
        with pytest.raises(ProviderError):
            await p.structured(Plan, "Plan", "Read supplied data")
        assert p.tokens == 12 and p.calls == 1
        assert p.records[0]["estimated_cost_usd"] == pytest.approx(0.000016)


@pytest.mark.parametrize("mode", ["openai", "anthropic"])
async def test_sdk_graph_handoff_approval_and_review(tmp_path, monkeypatch, mode):
    """Real SDK serialisation and graph; HTTP responses here are authored fixtures."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    from agentos.graph import build_graph
    from agentos.rag import Retrieval
    from agentos.store import Store

    if mode == "anthropic":
        import httpx2 as transport
    else:
        transport = httpx
    monkeypatch.setenv(mode.upper() + "_API_KEY", "mock-transport")
    store = Store("sqlite:///" + str(tmp_path / "db"))
    store.seed("w")
    rag = Retrieval(store)
    rag.ingest("w", "ledger rules", "Report totals in dollars.")
    phases = []

    def respond(request):
        body = json.loads(request.content)
        anthropic = mode == "anthropic"
        tool = body["tools"][0]
        schema = (tool["input_schema"] if anthropic else tool["function"]["parameters"])["title"]
        packet = json.loads(body["messages"][-1]["content"])
        if schema == "Plan":
            response = {
                "steps": [
                    {
                        "id": "measure",
                        "agent": "data",
                        "instruction": "Compute revenue",
                        "tool": "business_metrics",
                        "arguments": {"metric": "revenue"},
                    },
                    {
                        "id": "lookup",
                        "agent": "research",
                        "instruction": "Read the reporting rule",
                        "dependencies": ["measure"],
                        "checks": [{"kind": "source_count", "minimum": 1}],
                    },
                    {
                        "id": "save",
                        "agent": "action",
                        "instruction": "Prepare a report",
                        "dependencies": ["lookup"],
                    },
                ]
            }
        elif schema == "AnalyticsIntent":
            response = {"metrics": ["revenue"]}
        elif schema == "SearchQuery":
            assert packet["dependencies"][0]["computed"]["metrics"][0]["total"] == 370000
            response = {"query": "reporting rule"}
        elif schema == "Finding" and "sources" in packet:
            src = packet["sources"][0]
            response = {
                "summary": src["text"],
                "citations": [src["id"]],
                "claims": [
                    {
                        "kind": "extractive",
                        "text": src["text"],
                        "quote": src["text"],
                        "citations": [src["id"]],
                    }
                ],
            }
        elif schema == "Finding":
            response = {
                "summary": "Revenue totaled 370000.",
                "claims": [
                    {
                        "text": "Revenue totaled 370000.",
                        "kind": "numeric",
                        "operation": "total",
                        "metric": "revenue",
                        "value": 370000,
                    }
                ],
            }
        elif schema == "Review":
            phases.append(packet["phase"])
            response = {"supported": True}
        else:
            assert schema == "ActionSpec"
            assert len(packet["evidence"]) == 2
            response = {
                "tool": "create_report",
                "arguments": {
                    "title": "Revenue summary",
                    "body": "Revenue totaled 370000. Report totals in dollars.",
                },
            }
        if anthropic:
            data = {
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "fixture",
                "content": [
                    {"type": "tool_use", "id": "t", "name": "emit_result", "input": response}
                ],
                "usage": {"input_tokens": 11, "output_tokens": 3},
            }
        else:
            data = {
                "id": "m",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "id": "t",
                                    "function": {
                                        "name": "emit_result",
                                        "arguments": json.dumps(response),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            }
        return transport.Response(200, json=data)

    async with (
        transport.AsyncClient(transport=transport.MockTransport(respond)) as client,
        AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp,
    ):
        graph = build_graph(
            store, rag, cp, provider_factory=lambda m, n: Provider(m, "fixture", http_client=client)
        )
        cfg = {"configurable": {"thread_id": "sdk-graph"}}
        state = await graph.ainvoke(
            dict(
                workspace="w",
                run_id="r",
                mode=mode,
                goal="Summarize revenue with reporting policy and save",
                workflow="auto",
                results=[],
                events=[],
            ),
            cfg,
        )
        assert "__interrupt__" in state and phases == ["pre_action"]
        assert not store.execute("SELECT * FROM effects")
        result = await graph.ainvoke(Command(resume=True), cfg)
        assert result["report"]["status"] == "completed" and phases == ["pre_action", "final"]
        assert len(store.execute("SELECT * FROM effects")) == 1


@pytest.mark.asyncio
async def test_real_pdf_worker_rejects_empty_pdf():
    from io import BytesIO

    from pypdf import PdfWriter

    from agentos.ingestion import extract_upload

    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    with pytest.raises(ValueError, match="PDF extraction"):
        await extract_upload("blank.pdf", stream.getvalue())


@pytest.mark.parametrize("veto", [False, True])
async def test_dependent_actions_and_bounded_preflight_veto(tmp_path, veto):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    from agentos.graph import build_graph
    from agentos.models import Review
    from agentos.rag import Retrieval
    from agentos.store import Store

    store = Store("sqlite:///" + str(tmp_path / "db"))
    plans = []

    class ProposalProvider:
        records = []
        tokens = calls = 0

        async def structured(self, schema, system, payload):
            if schema is Plan:
                plans.append(json.loads(payload))
                return Plan(
                    steps=[
                        {
                            "id": "a",
                            "agent": "action",
                            "instruction": "Notify",
                            "tool": "create_notification",
                            "arguments": {"message": "First"},
                        },
                        {
                            "id": "b",
                            "agent": "action",
                            "instruction": "Follow up",
                            "dependencies": ["a"],
                            "tool": "create_followup",
                            "arguments": {"title": "Second"},
                        },
                    ]
                )
            assert schema is Review
            return Review(supported=not veto, issues=["evidence incomplete"] if veto else [])

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        graph = build_graph(
            store, Retrieval(store), cp, provider_factory=lambda *_: ProposalProvider()
        )
        cfg = {"configurable": {"thread_id": "two-actions"}}
        state = await graph.ainvoke(
            dict(
                workspace="w",
                run_id="r",
                mode="openai",
                goal="Notify then follow up",
                workflow="auto",
                results=[],
                events=[],
            ),
            cfg,
        )
        if veto:
            assert state["report"]["status"] == "failed" and len(plans) == 2
            assert plans[-1]["correction_issues"] == ["evidence incomplete"]
            assert not store.execute("SELECT * FROM approvals")
        else:
            for _ in range(2):
                assert "__interrupt__" in state
                state = await graph.ainvoke(Command(resume=True), cfg)
            assert state["report"]["status"] == "completed"
            assert len(store.execute("SELECT * FROM effects")) == 2


def test_structured_metadata_cannot_hide_reversed_text():
    from agentos.verification import assess_claim

    data = {
        "dataset": "sales",
        "metrics": [
            {
                "metric": "costs",
                "rows": [{"month": "2026-01", "value": 50}, {"month": "2026-02", "value": 65}],
            }
        ],
    }
    claim = {"kind": "trend", "metric": "costs", "direction": "increase", "text": "Costs declined."}
    assert assess_claim(claim, [], data)[0] == "contradicted"


def test_spelled_percent_uses_ratio_units():
    from agentos.verification import numbers

    assert numbers("The change was -12.5 percent after a 3 per cent adjustment.") == [-0.125, 0.03]
