"""Independent ranked retrieval benchmark with labeled document relevance."""

import argparse
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from .rag import Retrieval
from .store import Store

DATA = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "retrieval.json"


def ranking_metrics(ids, relevance, k=5):
    relevant = {key for key, value in relevance.items() if value > 0}
    ranked = list(dict.fromkeys(ids))[:k]
    hits = [i + 1 for i, key in enumerate(ranked) if key in relevant]
    dcg = sum((2 ** relevance.get(key, 0) - 1) / math.log2(i + 2) for i, key in enumerate(ranked))
    ideal = sum(
        (2**value - 1) / math.log2(i + 2)
        for i, value in enumerate(sorted(relevance.values(), reverse=True)[:k])
    )
    return {
        "recall_at_1": int(bool(ranked) and ranked[0] in relevant) / len(relevant),
        "recall_at_5": len(set(ranked) & relevant) / len(relevant),
        "precision_at_5": len(set(ranked) & relevant) / k,
        "mrr": 1 / min(hits) if hits else 0,
        "ndcg_at_5": dcg / ideal if ideal else None,
    }


def evaluate(output, include_neural=False, dataset=DATA):
    corpus = json.loads(Path(dataset).read_text())
    results = []
    configurations = [
        ("lexical", "hashing", "lexical", None),
        ("hashing_dense", "hashing", "dense", None),
    ]
    if include_neural:
        configurations += [
            ("neural_dense", "neural", "dense", None),
            ("neural_hybrid", "neural", "hybrid", None),
            ("neural_weighted_rrf", "neural", "weighted", None),
            ("neural_hybrid_rerank", "neural", "rerank", "cross-encoder/ms-marco-TinyBERT-L-2-v2"),
        ]
    with tempfile.TemporaryDirectory() as temp:
        for name, backend, method, rerank in configurations:
            start = time.perf_counter()
            try:
                store = Store("sqlite:///" + str(Path(temp) / (name + ".db")))
                rag = Retrieval(store, backend=backend, rerank=rerank or "")
                loaded = time.perf_counter()
                chunk_source = {}
                for doc in corpus["documents"]:
                    for ident in rag.ingest(
                        "retrieval-eval", doc["id"], doc["title"] + "\n\n" + doc["text"]
                    ):
                        chunk_source[ident] = doc["id"]
                indexing = time.perf_counter() - loaded
                rows = []
                for query in corpus["queries"]:
                    qstart = time.perf_counter()
                    hits = rag.search("retrieval-eval", query["query"], k=5, method=method)
                    sources = [chunk_source[h["id"]] for h in hits]
                    rows.append(
                        {
                            "query_id": query["id"],
                            "ranked_sources": sources,
                            "seconds": time.perf_counter() - qstart,
                            **ranking_metrics(sources, query["relevance"]),
                        }
                    )
                results.append(
                    {
                        "configuration": name,
                        "status": "executed",
                        "embedding_descriptor": rag.descriptor,
                        "model_load_seconds": loaded - start,
                        "indexing_seconds": indexing,
                        "query_count": len(rows),
                        "metrics": {
                            key: statistics.mean(row[key] for row in rows)
                            for key in [
                                "recall_at_1",
                                "recall_at_5",
                                "precision_at_5",
                                "mrr",
                                "ndcg_at_5",
                            ]
                        },
                        "mean_query_seconds": statistics.mean(r["seconds"] for r in rows),
                        "p95_query_seconds": sorted(r["seconds"] for r in rows)[
                            math.ceil(0.95 * len(rows)) - 1
                        ],
                        "rows": rows,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "configuration": name,
                        "status": "not_executed",
                        "error_type": type(exc).__name__,
                        "reason": str(exc)[:600],
                    }
                )
    result = {
        "kind": "independent retrieval; synthetic hand-authored labels",
        "documents": len(corpus["documents"]),
        "queries": len(corpus["queries"]),
        "results": results,
        "notes": [
            "No answer generation is scored here. Small authored corpus; generalization is unproven. Neural model download failures are not replaced with hashing scores."
        ],
    }
    Path(output).write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../evals/results/retrieval/retrieval-development.json")
    parser.add_argument("--neural", action="store_true")
    parser.add_argument("--dataset", default=DATA)
    args = parser.parse_args()
    evaluate(args.output, args.neural, args.dataset)
