"""Opt-in real local encoder/reranker tests; never substitute fake embeddings."""

import os

import numpy as np
import pytest

from agentos.rag import Retrieval
from agentos.store import Store


@pytest.mark.skipif(
    os.getenv("RUN_NEURAL_TESTS") != "1",
    reason="Set RUN_NEURAL_TESTS=1 after downloading neural models",
)
def test_real_neural_retrieval_and_reranking(tmp_path):
    rag = Retrieval(
        Store("sqlite:///" + str(tmp_path / "neural")),
        backend="neural",
        rerank="cross-encoder/ms-marco-TinyBERT-L-2-v2",
    )
    rag.ingest("a", "vacation", "Staff receive twenty paid days of annual leave.")
    rag.ingest("a", "noise", "The warehouse stocks blue cables and robot motors.")
    vec = rag.embed(["How many paid days off do employees get?"])[0]
    assert np.linalg.norm(vec) == pytest.approx(1, abs=1e-5)
    hits = rag.search("a", "How much vacation time can an employee take?", method="rerank")
    assert hits[0]["source"] == "vacation"
    assert hits[0]["rerank_score"] is not None
    assert rag.search("b", "vacation") == []


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_NEURAL_TESTS") != "1", reason="Opt-in downloaded neural models")
async def test_neural_rag_through_langgraph(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from agentos.graph import build_graph

    store = Store("sqlite:///" + str(tmp_path / "graph"))
    rag = Retrieval(store, backend="neural", rerank="cross-encoder/ms-marco-TinyBERT-L-2-v2")
    a = rag.ingest("tenant", "old-policy", "January travel allowance is 150 dollars per night.")
    b = rag.ingest(
        "tenant",
        "new-policy",
        "July travel allowance is 180 dollars per night and supersedes January.",
    )
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp")) as cp:
        out = await build_graph(store, rag, cp).ainvoke(
            dict(
                goal="Research and compare travel allowances across the January and July documents",
                workspace="tenant",
                run_id="neural-graph",
                workflow="auto",
                mode="demo",
                results=[],
                events=[],
            ),
            {"configurable": {"thread_id": "neural"}},
        )
    assert out["report"]["status"] == "completed"
    assert {h["id"] for h in out["report"]["citations"]} >= set(a + b)
    assert all(h["rerank_score"] is not None for h in out["report"]["citations"])
