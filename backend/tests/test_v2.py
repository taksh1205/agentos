import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agentos.budget import Ledger
from agentos.graph import build_graph, merge_results
from agentos.ingestion import extract
from agentos.models import AnalyticsIntent, BudgetExceeded, Plan, Step
from agentos.rag import Retrieval, chunk_text
from agentos.store import Store
from agentos.tools import ToolService, approve_proposal, propose


@pytest.fixture
def services(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "data"))
    store.seed("tenant")
    rag = Retrieval(store)
    rag.ingest(
        "tenant",
        "policy",
        "Enterprise subscriptions improved revenue. Reports need manager approval.",
    )
    return store, rag, ToolService(store, rag)


@pytest.mark.parametrize(
    "steps",
    [
        [dict(id="a", agent="research", instruction="x", dependencies=["missing"])],
        [
            dict(id="a", agent="research", instruction="x", dependencies=["b"]),
            dict(id="b", agent="data", instruction="x", dependencies=["a"]),
        ],
        [
            dict(id="a", agent="research", instruction="x"),
            dict(id="a", agent="research", instruction="x"),
        ],
    ],
)
def test_invalid_plans(steps):
    with pytest.raises(ValueError):
        Plan(steps=steps)


def test_replay_safe_reducer():
    result = merge_results(
        [{"step": "a", "ok": False}], [{"step": "a", "ok": True}, {"step": "b", "ok": True}]
    )
    assert len(result) == 2 and result[0]["ok"]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("create_report", {"title": "Revenue report", "body": "Computed results"}),
        ("export_csv", {"dataset": "sales"}),
        ("create_followup", {"title": "Review costs", "description": "Discuss March costs"}),
        ("draft_email", {"to": "internal@example.test", "subject": "Review", "body": "Draft only"}),
        ("update_inventory", {"sku": "WIDGET-A", "quantity": 25}),
        ("create_notification", {"message": "Review required"}),
    ],
)
def test_all_mutations_exact_approval(services, tool, args):
    store, rag, tools = services
    with pytest.raises(PermissionError):
        tools.invoke("tenant", tool, args, scopes=["action:write"])
    proposal = propose(store, "tenant", "run", tool, tool, args)
    approve_proposal(store, "tenant", proposal["id"], True)
    result = tools.invoke("tenant", tool, args, scopes=["action:write"], approval_id=proposal["id"])
    assert result == tools.invoke(
        "tenant", tool, args, scopes=["action:write"], approval_id=proposal["id"]
    )
    assert result["external_message_sent"] is False
    assert len(store.execute("SELECT * FROM effects")) == 1
    with pytest.raises(PermissionError):
        tools.invoke("other", tool, args, scopes=["action:write"], approval_id=proposal["id"])
    if tool == "export_csv":
        assert "month,revenue,costs" in result["payload"]["content"]
    if tool == "update_inventory":
        assert result["payload"]["verified_quantity"] == 25


def test_changed_action_arguments_rejected(services):
    store, _, tools = services
    p = propose(
        store, "tenant", "run", "step", "update_inventory", {"sku": "WIDGET-A", "quantity": 20}
    )
    approve_proposal(store, "tenant", p["id"], True)
    with pytest.raises(PermissionError):
        tools.invoke(
            "tenant",
            "update_inventory",
            {"sku": "WIDGET-A", "quantity": 900},
            scopes=["action:write"],
            approval_id=p["id"],
        )


def test_budget_concurrency_and_unknown_prices(services, monkeypatch):
    store, _, _ = services
    monkeypatch.setenv("MAX_TOKENS", "100")
    ledger = Ledger(store, "tenant", "budget")

    def reserve(_):
        try:
            ledger.reserve(40, None)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 2
    monkeypatch.setenv("MAX_COST_USD", ".01")
    with pytest.raises(BudgetExceeded):
        Ledger(store, "tenant", "priced").reserve(1, None)


def test_analytics_filters_and_weighted_margin(services):
    store, _, _ = services
    result = store.analyze(
        "tenant",
        AnalyticsIntent(
            metrics=["revenue", "costs", "profit", "margin"], start="2026-02", end="2026-03"
        ),
    )
    assert [m["total"] for m in result["metrics"][:3]] == [270000, 168000, 102000]
    assert result["metrics"][3]["total"] == pytest.approx(102000 / 270000)
    assert store.analyze("other", AnalyticsIntent())["raw_rows"] == []
    with pytest.raises(ValueError):
        store.analyze("tenant", AnalyticsIntent(start="2026-04", end="2026-01"))


def test_incremental_update_delete_and_reindex(services, monkeypatch):
    store, rag, _ = services
    first = rag.ingest("tenant", "notes", "Sensor batteries need replacement", {"team": "ops"})
    assert first == rag.ingest(
        "tenant", "notes", "Sensor batteries need replacement", {"team": "ops"}
    )
    second = rag.ingest("tenant", "notes", "Sensor batteries last six months", {"team": "ops"})
    assert first != second
    assert rag.search("tenant", "batteries", metadata={"team": "other"}) == []
    assert rag.search("tenant", "batteries", metadata={"team": "ops"})[0]["id"] in second
    monkeypatch.setenv("HASH_DIMENSION", "256")
    changed = Retrieval(store)
    with pytest.raises(ValueError, match="reindex"):
        changed.search("tenant", "sensor")
    changed.reindex("tenant")
    assert changed.dimension == 256
    assert changed.search("tenant", "sensor")
    changed.delete("tenant", "notes")
    assert not changed.search("tenant", "sensor", source="notes")


def test_memory_dedup_provenance_delete(services):
    store, rag, _ = services
    first = rag.remember(
        "tenant", "Project Cedar deadline is Friday", {"document": "project-cedar"}
    )
    assert first == rag.remember(
        "tenant", "Project Cedar deadline is Friday", {"document": "project-cedar"}
    )
    rows = rag.memory_records("tenant", "Cedar deadline")
    assert len(rows) == 1 and rows[0]["provenance"]["document"] == "project-cedar"
    assert not rag.memory("other", "Cedar deadline")
    rag.forget("tenant", first)
    assert not rag.memory("tenant", "Cedar deadline")


@pytest.mark.parametrize(
    "filename,data",
    [
        ("bad.pdf", b"not pdf"),
        ("broken.pdf", b"%PDF-1.4 invalid"),
        ("empty.txt", b" "),
        ("invalid.txt", b"\xff"),
        ("exec.exe", b"hello"),
    ],
)
def test_malformed_documents(filename, data):
    with pytest.raises(ValueError):
        extract(filename, data)


class ScriptedProvider:
    """Deterministic structured responses for orchestration tests, not inference evidence."""

    def __init__(self, *args):
        self.tokens = 0
        self.calls = 0
        self.records = []

    async def structured(self, schema, system, payload):
        value = json.loads(payload)
        self.calls += 1
        if schema.__name__ == "Plan":
            return Plan(
                steps=[
                    Step(id="research-A", agent="research", instruction="enterprise policy"),
                    Step(id="data-B", agent="data", instruction="revenue and costs"),
                    Step(
                        id="action-C",
                        agent="action",
                        instruction="export sales",
                        tool="export_csv",
                        arguments={"dataset": "sales"},
                        dependencies=["research-A", "data-B"],
                        requires_approval=True,
                    ),
                ]
            )
        if schema.__name__ == "SearchQuery":
            return schema(query="enterprise", alternatives=["subscriptions"])
        if schema.__name__ == "AnalyticsIntent":
            return AnalyticsIntent(metrics=["revenue", "costs"])
        if schema.__name__ == "Review":
            return schema(supported=True, issues=[])
        if schema.__name__ == "CitedFinding":
            source = value["sources"][0]
            return schema(
                summary="Evidence-backed finding",
                claims=[
                    {"text": source["text"], "quote": source["text"], "citations": [source["id"]]}
                ],
                contradictions=[],
                insufficient=False,
            )
        if schema.__name__ == "LedgerReading":
            return schema(focus="revenue", direction="increase")
        raise AssertionError(schema)


@pytest.mark.asyncio
async def test_model_driven_auto_graph_and_multiple_tools(services, tmp_path):
    store, rag, _ = services
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        graph = build_graph(store, rag, cp, provider_factory=ScriptedProvider)
        cfg = {"configurable": {"thread_id": "dynamic"}}
        result = await graph.ainvoke(
            dict(
                goal="Analyze revenue and costs using policies and export sales CSV",
                workflow="auto",
                workspace="tenant",
                run_id="dynamic",
                mode="openai",
                results=[],
                events=[],
            ),
            cfg,
        )
        assert "__interrupt__" in result
        assert not store.execute("SELECT * FROM effects")
        result = await graph.ainvoke(Command(resume=True), cfg)
        assert result["report"]["status"] == "completed"
        assert [r["agent"] for r in result["results"]] == ["research", "data", "action"]
        assert result["results"][-1]["effect"]["tool"] == "export_csv"
        assert result["results"][1]["computed"]["metrics"][1]["total"] == 238000


@pytest.mark.asyncio
async def test_graph_mcp_integration(services, tmp_path, monkeypatch):
    store, rag, _ = services
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    monkeypatch.setenv("USE_MCP", "true")
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        graph = build_graph(store, rag, cp)
        cfg = {"configurable": {"thread_id": "mcp-graph"}}
        out = await graph.ainvoke(
            dict(
                goal="Analyze inventory and export a CSV",
                workflow="auto",
                workspace="tenant",
                run_id="mcp-graph",
                mode="demo",
                results=[],
                events=[],
            ),
            cfg,
        )
        out = await graph.ainvoke(Command(resume=True), cfg)
        assert out["report"]["status"] == "completed"
        assert out["results"][0]["analytics"]["rows"]
        assert out["results"][-1]["effect"]["stored"]


@pytest.mark.asyncio
async def test_mcp_scope_and_all_read_tools(services, monkeypatch):
    from agentos.mcp_client import call_tool

    store, _, _ = services
    monkeypatch.setenv("DATABASE_URL", str(store.engine.url))
    for name, key in [
        ("dataset_schema", "datasets"),
        ("inventory_retrieval", "rows"),
        ("invoice_analysis", "rows"),
        ("document_search", "sources"),
    ]:
        args = {"query": "enterprise"} if name == "document_search" else {}
        assert key in await call_tool("tenant", name, args)
    with pytest.raises(PermissionError):
        await call_tool("tenant", "create_notification", {"message": "bypass"})


def test_chunking_boundaries_and_validation():
    text = "\n\n".join(
        [" ".join(["policy"] * 60), " ".join(["cost"] * 60), " ".join(["revenue"] * 60)]
    )
    for strategy in ["fixed", "paragraph"]:
        chunks = chunk_text(text, 80, 15, strategy)
        assert all(len(c.split()) <= 80 for c in chunks)
        assert {"policy", "cost", "revenue"} <= set(" ".join(chunks).split())
    with pytest.raises(ValueError):
        chunk_text(text, 20, 20)


@pytest.mark.asyncio
async def test_prepared_action_stays_identical_after_resume(services, tmp_path):
    from agentos.models import ToolChoice

    calls = []

    class ActionProvider(ScriptedProvider):
        async def structured(self, schema, system, payload):
            if schema is Plan:
                return Plan(
                    steps=[
                        Step(id="act", agent="action", instruction="Create a local notification")
                    ]
                )
            if schema is ToolChoice:
                return ToolChoice(tool="create_notification")
            if schema.__name__ == "NoticeArgs":
                calls.append(1)
                return schema(
                    message="reviewed message" if len(calls) == 1 else "UNREVIEWED MESSAGE"
                )
            return await super().structured(schema, system, payload)

    store, rag, _ = services
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        graph = build_graph(store, rag, cp, provider_factory=ActionProvider)
        cfg = {"configurable": {"thread_id": "stable"}}
        out = await graph.ainvoke(
            dict(
                goal="Notify team",
                workspace="tenant",
                run_id="stable",
                mode="openai",
                results=[],
                events=[],
            ),
            cfg,
        )
        assert (
            out["__interrupt__"][0].value["proposal"]["arguments"]["message"] == "reviewed message"
        )
        out = await graph.ainvoke(Command(resume=True), cfg)
        assert len(calls) == 1
        assert out["results"][-1]["effect"]["payload"]["message"] == "reviewed message"


@pytest.mark.asyncio
async def test_model_cannot_route_mutation_through_research(services, tmp_path):
    class UnsafePlanner(ScriptedProvider):
        async def structured(self, schema, system, payload):
            return Plan(
                steps=[
                    Step(
                        id="x",
                        agent="research",
                        instruction="malicious tool response",
                        tool="update_inventory",
                        arguments={"sku": "WIDGET-A", "quantity": 999},
                    )
                ]
            )

    store, rag, _ = services
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        graph = build_graph(store, rag, cp, provider_factory=UnsafePlanner)
        with pytest.raises(PermissionError):
            await graph.ainvoke(
                dict(
                    goal="Read policy",
                    workspace="tenant",
                    run_id="unsafe",
                    mode="openai",
                    results=[],
                    events=[],
                ),
                {"configurable": {"thread_id": "unsafe"}},
            )
    assert not store.execute("SELECT * FROM effects")


def test_replanning_duplicate_action_has_same_effect_identity(services):
    store, _, tools = services
    args = {"message": "do this once"}
    first = propose(store, "tenant", "run", "step-1", "create_notification", args)
    second = propose(store, "tenant", "run", "step-1-correction", "create_notification", args)
    assert first["id"] == second["id"]
    approve_proposal(store, "tenant", first["id"], True)
    result = tools.invoke(
        "tenant", "create_notification", args, scopes=["action:write"], approval_id=first["id"]
    )
    assert result == tools.invoke(
        "tenant", "create_notification", args, scopes=["action:write"], approval_id=second["id"]
    )


def test_previous_period_comparison(services):
    result = services[0].analyze(
        "tenant",
        AnalyticsIntent(metrics=["revenue"], start="2026-02", end="2026-02", compare_previous=True),
    )
    assert result["comparison"] == [
        {
            "metric": "revenue",
            "previous_total": 100000,
            "current_total": 120000,
            "absolute_change": 20000,
        }
    ]


def test_deterministic_numeric_verification():
    from agentos.verification import unsupported_numbers

    computed = {"revenue": 370000, "growth": 0.5, "month": "2026-03"}
    assert not unsupported_numbers("Revenue was 370,000 and growth 50%.", computed)
    assert unsupported_numbers("Revenue was 999999.", computed) == [999999]


def test_semantic_memory_expiration_and_bounded_compaction(services, monkeypatch):
    store, rag, _ = services
    monkeypatch.setenv("MEMORY_TTL_DAYS", "0")
    ident = rag.remember("tenant", "Repeated context " * 1000, {"source": "test"})
    row = store.execute("SELECT content FROM semantic_memory WHERE id=:id", {"id": ident})[0]
    assert len(row["content"]) <= 3000
    assert not rag.memory("tenant", "Repeated context")
    assert not store.execute("SELECT id FROM semantic_memory WHERE id=:id", {"id": ident})
