"""Multi-turn context recall benchmark, distinct from unverified answer intelligence."""

import argparse
import json
import re
import statistics
import tempfile
import time
from pathlib import Path

from .models import Provider, StrictModel
from .rag import Retrieval
from .store import Store


class MemoryAnswer(StrictModel):
    answer: str
    insufficient: bool


async def evaluate(output, mode="demo", model=None, backend="hashing"):
    cases = json.loads(
        (Path(__file__).resolve().parents[2] / "evals/datasets/memory.json").read_text()
    )
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        rag = Retrieval(Store("sqlite:///" + str(Path(temp) / "memory")), backend=backend)
        for enabled in [False, True]:
            for case in cases:
                # Each task is an isolated two-turn conversation, no cross-case hints.
                w = f"memory-{enabled}-{case['id']}"
                rag.remember(w, case["stored_fact"], {"conversation": case["id"], "turn": 1})
                start = time.perf_counter()
                context = rag.memory_records(w, case["turns"][1]) if enabled else []
                p = Provider(mode, model) if mode != "demo" else None
                if p:
                    answer = await p.structured(
                        MemoryAnswer,
                        "Answer the follow-up using prior conversation context only. If missing, return insufficient=true; never guess.",
                        json.dumps({"question": case["turns"][1], "memory": context}),
                    )
                    value = answer.answer
                    insufficient = answer.insufficient
                else:
                    # Deterministic extraction demonstrates information availability,
                    # not general language understanding. Explicitly labeled in output.
                    match = (
                        re.search(r"Decision:\s*(.+?)\.", context[0]["content"])
                        if context
                        else None
                    )
                    value = match.group(1) if match else ""
                    insufficient = not bool(match)
                rows.append(
                    {
                        "id": case["id"],
                        "memory_enabled": enabled,
                        "correct": value.strip().lower() == case["expected_value"].lower(),
                        "insufficient": insufficient,
                        "retrieved_memory_ids": [r["id"] for r in context],
                        "seconds": time.perf_counter() - start,
                        "tokens": p.tokens if p else 0,
                        "error": None,
                    }
                )
    summary = {
        "mode": mode,
        "model": model,
        "embedding_backend": backend,
        "measurement": "two-turn fact recall; offline answers use explicit extraction, not inference",
        "groups": [
            {
                "memory_enabled": enabled,
                "cases": len(cases),
                "accuracy": statistics.mean(
                    r["correct"] for r in rows if r["memory_enabled"] == enabled
                ),
                "mean_seconds": statistics.mean(
                    r["seconds"] for r in rows if r["memory_enabled"] == enabled
                ),
                "tokens": sum(r["tokens"] for r in rows if r["memory_enabled"] == enabled),
                "error_rate": statistics.mean(
                    r["error"] is not None for r in rows if r["memory_enabled"] == enabled
                ),
            }
            for enabled in [False, True]
        ],
        "rows": rows,
    }
    Path(output).write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    import asyncio

    p = argparse.ArgumentParser()
    p.add_argument("--output", default="../evals/results/memory/memory-hashing.json")
    p.add_argument("--mode", default="demo")
    p.add_argument("--model")
    p.add_argument("--backend", default="hashing")
    a = p.parse_args()
    asyncio.run(evaluate(a.output, a.mode, a.model, a.backend))
