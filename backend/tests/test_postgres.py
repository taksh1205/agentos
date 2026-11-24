import os
import uuid

import pytest

from agentos.rag import Retrieval
from agentos.store import Store


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="PostgreSQL unavailable; CI service runs this test"
)
def test_pgvector_index_and_isolation():
    store = Store(os.environ["TEST_POSTGRES_URL"])
    rag = Retrieval(store)
    w = str(uuid.uuid4())
    ids = rag.ingest(w, "pg-test", "Enterprise recurring revenue and subscriptions")
    assert rag.search(w, "enterprise revenue")[0]["id"] == ids[0]
    assert not rag.search(w + "other", "enterprise")
    store.execute("DELETE FROM documents WHERE workspace=:w", {"w": w})


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="Real PostgreSQL connection required"
)
def test_postgres_dimension_change_and_approved_effect(monkeypatch):
    from agentos.tools import ToolService, approve_proposal, propose

    store = Store(os.environ["TEST_POSTGRES_URL"])
    w = "pg-" + str(uuid.uuid4())
    store.seed(w)
    rag = Retrieval(store)
    rag.ingest(w, "policy", "Reports need manager approval")
    monkeypatch.setenv("HASH_DIMENSION", "256")
    changed = Retrieval(store)
    with pytest.raises(ValueError, match="reindex"):
        changed.search(w, "report")
    changed.reindex(w)
    assert changed.search(w, "manager approval")
    tools = ToolService(store, changed)
    args = {"sku": "WIDGET-A", "quantity": 33}
    proposal = propose(store, w, "run", "step", "update_inventory", args)
    approve_proposal(store, w, proposal["id"], True)
    result = tools.invoke(
        w, "update_inventory", args, scopes=["action:write"], approval_id=proposal["id"]
    )
    assert result["payload"]["verified_quantity"] == 33
    assert result == tools.invoke(
        w, "update_inventory", args, scopes=["action:write"], approval_id=proposal["id"]
    )
    print(
        "PostgreSQL/pgvector:",
        store.execute(
            "SELECT version() AS server, (SELECT extversion FROM pg_extension WHERE extname='vector') AS pgvector"
        ),
    )
    changed.delete(w, "policy")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="Real PostgreSQL connection required"
)
async def test_postgres_graph_checkpoint_restart():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.types import Command

    from agentos.graph import build_graph

    url = os.environ["TEST_POSTGRES_URL"]
    w = "checkpoint-" + str(uuid.uuid4())
    store = Store(url)
    store.seed(w)
    rag = Retrieval(store)
    rag.ingest(w, "policy", "CSV reports require approval")
    cfg = {"configurable": {"thread_id": w}}
    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(dsn) as cp:
        await cp.setup()
        graph = build_graph(store, rag, cp)
        out = await graph.ainvoke(
            dict(
                goal="Analyze revenue and export CSV",
                workspace=w,
                run_id=w,
                workflow="auto",
                mode="demo",
                results=[],
                events=[],
            ),
            cfg,
        )
        assert "__interrupt__" in out
    async with AsyncPostgresSaver.from_conn_string(dsn) as cp:
        out = await build_graph(store, rag, cp).ainvoke(Command(resume=True), cfg)
        assert out["report"]["status"] == "completed"
        assert out["results"][-1]["effect"]["tool"] == "export_csv"
