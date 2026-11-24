# AI evaluation

**Historical review.** See the [latest acceptance and verification report](ACCEPTANCE_REPAIR.md) for the repaired release.

Actual local inference used llama.cpp b12498 with quantized Qwen3-4B-Instruct-2507 and Qwen2.5-1.5B-Instruct. No hosted OpenAI or Anthropic requests were made. The OpenAI-compatible client records response tokens when available. A timeout can leave server-side work unmetered. API cost and local compute cost are unavailable.

| Attempt / case | Model | Responses / client attempts | Known tokens | Attempts missing usage | Wall time (s) | Terminal outcome |
|---|---|---:|---:|---:|---:|---|
| live/A | qwen3-4b-local | 0 / 3 | 0 | 3 | 51.3 | ProviderError |
| live/B | qwen3-4b-local | 1 / 1 | 435 | 0 | 32.0 | ValueError |
| live/C | qwen3-4b-local | 1 / 1 | 464 | 0 | 20.5 | ValueError |
| acceptance/A | qwen3-4b-local | 0 / 3 | 0 | 3 | 13.5 | ProviderError |
| acceptance/B | qwen3-4b-local | 1 / 1 | 563 | 0 | 37.2 | PermissionError |
| acceptance/C | qwen3-4b-local | 2 / 5 | 1092 | 3 | 420.1 | interrupted |
| small/A | qwen2.5-1.5b-local | 6 / 6 | 3248 | 0 | 160.6 | failed |
| resumed/B | qwen2.5-1.5b-local | 10 / 10 | 9303 | 0 | 180.4 | failed |
| resumed/C | qwen2.5-1.5b-local | 6 / 6 | 4024 | 0 | 98.2 | failed |
| cited/A | qwen2.5-1.5b-local | 12 / 13 | 9710 | 1 | 300.0 | TimeoutOrCancellation |
| records/C | qwen2.5-1.5b-local | 10 / 10 | 14066 | 0 | 247.1 | failed |
| ledger/B | qwen2.5-1.5b-local | 4 / 4 | 4884 | 0 | 99.1 | completed |
| periods/B | qwen2.5-1.5b-local | 6 / 6 | 5221 | 0 | 125.8 | failed |

Raw case files contain tool traces and results. Each row is one workflow execution. Development attempts use different code revisions and share the same authored fixtures. They do not support a general model-accuracy estimate. Additional server launch failures are preserved in the revised, followup and scored log directories. The earlier small/B log ends without a terminal JSON artifact and is excluded from workflow totals.

## Retrieval

46 synthetic documents and 14 held-out queries. Values are macro averages. Each configuration used the same labels. Latencies cover retrieval only.

| Configuration | Recall@1 | Recall@5 | P@5 | MRR | nDCG@5 | Mean ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 0.607 | 0.679 | 0.171 | 0.714 | 0.678 | 7.2 | 9.1 |
| hashing_dense | 0.286 | 0.714 | 0.171 | 0.520 | 0.545 | 6.7 | 7.8 |
| neural_dense | 0.786 | 1.000 | 0.257 | 0.964 | 0.974 | 20.1 | 23.9 |
| neural_hybrid | 0.643 | 0.964 | 0.243 | 0.850 | 0.850 | 20.4 | 30.1 |
| neural_weighted_rrf | 0.643 | 1.000 | 0.257 | 0.893 | 0.921 | 18.0 | 21.7 |
| neural_hybrid_rerank | 0.786 | 0.929 | 0.243 | 0.929 | 0.920 | 43.0 | 86.1 |

Dense MiniLM led this corpus. Weighted fusion partially recovered the loss from equal-weight fusion. TinyBERT reranking improved on plain hybrid ranking, added latency, and missed some relevant sources in the top five. See retrieval.json for each ranked list.

## Offline measurements

| Corpus | Expected outcomes matched | Tool-selection accuracy | p50 / p95 seconds | Recovered injected failures |
|---|---:|---:|---:|---:|
| curated | 24/24 | 1.000 | 0.027 / 0.066 | 1 |
| heldout | 9/9 | 1.000 | 0.023 / 0.171 | 1 |
| transfer | 8/8 | 1.000 | 0.020 / 0.040 | 0 |

The offline verifier matched 12/12 authored claim labels. Only one accepted citation case entered the citation-support precision denominator. The two-turn hashing-memory ablation recovered the labeled fact on 8/8 tasks with memory and 0/8 without it. These tasks measured deterministic recall. See claims.json, memory.json, heldout.json and transfer.json.

The arithmetic oracle, source quotes and approval-replay checks are reproducible with agentos.release_score. Semantic review of the final narrative is separate. See ACCEPTANCE.md for the release decision.

## Failure analysis

Research recognized the policy conflict at an intermediate checkpoint. Its broader plan included unrelated records and failed to finish by the deadline. The analytics evaluator identified an incorrect baseline even when the graph declared success. After a calendar-binding fix, the verifier rejected the numerical interpretation on both attempts. The invoice model proposed a report that contradicted the overdue ledger. The approval test declined that proposal. Inspect the acceptance matrix before using these workflows in an interview. The measured retrieval result and tested approval boundary are stronger claims than open-ended reasoning reliability.
