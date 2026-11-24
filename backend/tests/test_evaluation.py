from agentos.evaluate import scenarios


def test_generator():
    cases = list(scenarios(1200))
    assert len(cases) == 1200
    assert len({c["id"] for c in cases}) == 1200
    assert {c["workflow"] for c in cases} == {"business", "research", "operations"}


def test_metrics_missing_labels_are_not_scores():
    from agentos.metrics import labeled_metrics, retrieval_metrics

    result = labeled_metrics([{"task_id": "a", "completed": True}])
    assert result["answer_faithfulness"] is None
    assert result["hallucination_frequency"] is None
    assert result["estimated_cost_usd"] is None
    assert retrieval_metrics(["bad", "good"], {"good"}) == {"recall_at_k": 1.0, "mrr": 0.5}


def test_labeled_metrics():
    from agentos.metrics import labeled_metrics

    rows = [
        {
            "task_id": "a",
            "completed": True,
            "actual_tools": ["search"],
            "expected_tools": ["search"],
            "actual_agents": ["research"],
            "expected_agents": ["research"],
            "claims": [{"supported": True, "citation_correct": True}],
            "injected_failure": True,
            "recovered": True,
        },
        {
            "task_id": "a",
            "completed": False,
            "claims": [{"supported": False, "citation_correct": False}],
        },
    ]
    r = labeled_metrics(rows)
    assert r["answer_faithfulness"] == 0.5
    assert r["hallucination_frequency"] == 0.5
    assert r["repeated_task_all_success_rate"] == 0
