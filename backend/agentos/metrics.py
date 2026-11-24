"""Metrics for externally labeled evaluation records. Never infer labels from prose."""

import statistics
from collections import defaultdict


def retrieval_metrics(retrieved: list[str], relevant: set[str], k: int = 5):
    if not relevant:
        return {"recall_at_k": None, "mrr": None}
    hits = [i + 1 for i, item in enumerate(retrieved[:k]) if item in relevant]
    return {
        "recall_at_k": len(set(retrieved[:k]) & relevant) / len(relevant),
        "mrr": 1 / min(hits) if hits else 0.0,
    }


def labeled_metrics(records: list[dict]):
    """Each bool label must come from dataset ground truth or human adjudication.

    Expected fields: task_id, completed, actual_tools, expected_tools,
    actual_agents, expected_agents, claims=[{supported:bool,citation_correct:bool}],
    injected_failure, recovered, seconds, input_tokens, output_tokens,
    input_price_per_million, output_price_per_million.
    Missing labels produce null metrics rather than guessed outcomes.
    """

    def avg(xs):
        return statistics.mean(xs) if xs else None

    claims = [c for r in records for c in r.get("claims", [])]
    labeled = [c for c in claims if isinstance(c.get("supported"), bool)]
    costs = [
        (
            r["input_tokens"] * r["input_price_per_million"]
            + r["output_tokens"] * r["output_price_per_million"]
        )
        / 1e6
        for r in records
        if all(
            k in r
            for k in [
                "input_tokens",
                "output_tokens",
                "input_price_per_million",
                "output_price_per_million",
            ]
        )
    ]
    groups = defaultdict(list)
    for r in records:
        if isinstance(r.get("completed"), bool):
            groups[r["task_id"]].append(r["completed"])
    return {
        "task_completion_accuracy": avg(
            [r["completed"] for r in records if isinstance(r.get("completed"), bool)]
        ),
        "tool_call_correctness": avg(
            [
                r["actual_tools"] == r["expected_tools"]
                for r in records
                if "actual_tools" in r and "expected_tools" in r
            ]
        ),
        "routing_accuracy": avg(
            [
                set(r["actual_agents"]) == set(r["expected_agents"])
                for r in records
                if "actual_agents" in r and "expected_agents" in r
            ]
        ),
        "answer_faithfulness": avg([c["supported"] for c in labeled]),
        "hallucination_frequency": avg([not c["supported"] for c in labeled]),
        "citation_correctness": avg(
            [c["citation_correct"] for c in claims if isinstance(c.get("citation_correct"), bool)]
        ),
        "error_recovery_rate": avg(
            [
                r["recovered"]
                for r in records
                if r.get("injected_failure") and isinstance(r.get("recovered"), bool)
            ]
        ),
        "mean_seconds": avg([r["seconds"] for r in records if "seconds" in r]),
        "total_tokens": sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in records),
        "estimated_cost_usd": sum(costs) if len(costs) == len(records) and records else None,
        "repeated_task_all_success_rate": avg([all(v) for v in groups.values() if len(v) > 1]),
        "claim_label_count": len(labeled),
    }
