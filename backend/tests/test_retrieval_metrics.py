from agentos.migrate import migrate_legacy
from agentos.rag import Retrieval
from agentos.retrieval_eval import ranking_metrics
from agentos.store import Store


def test_graded_rank_metrics():
    result = ranking_metrics(["noise", "b", "a"], {"a": 2, "b": 1})
    assert result["recall_at_1"] == 0
    assert result["recall_at_5"] == 1
    assert result["precision_at_5"] == 0.4
    assert result["mrr"] == 0.5
    assert 0 < result["ndcg_at_5"] < 1


def test_legacy_document_migration(tmp_path):
    store = Store("sqlite:///" + str(tmp_path / "old"))
    store.execute(
        "INSERT INTO documents VALUES('old','a','legacy','Policy requires approval','[]')"
    )
    rag = Retrieval(store)
    assert migrate_legacy(store, rag) == 1
    assert rag.search("a", "approval")[0]["source"] == "legacy"
    assert migrate_legacy(store, rag) == 0
    assert store.execute("SELECT id FROM documents")  # Original records retained.
