# Evaluation methodology and evidence boundaries

## Four separate result classes

1. `evals/historical-v1/`: retained historical deterministic results and repetitive generated cases; not V2 intelligence evidence.
2. `evals/agent-results.json`: actual execution of 24 human-authored synthetic agent cases, using the offline rule baseline. Outcomes compare against independent labels in `datasets/agents.json`.
3. `evals/retrieval-results.json`: actual ranked retrieval measurements across five configurations using 32 documents and 22 authored queries.
4. `evals/memory-results.json` and `memory-neural-results.json`: 16 two-turn fact-recall trials per embedding configuration (32 total), eight with memory and eight without in each. The first-turn memory contains the decision fact, not a copy of the later question. Offline answers use explicit extraction. This is information-availability evidence, not live-model reasoning evidence.

`generated-scenarios.jsonl` contains 1,200 distinct controlled parameter/context/action combinations. They were generated, not executed. They do not represent 1,200 independently sourced reasoning problems. Browser setup may run two extra deterministic warm-up cases; that raw file is kept separately and not counted in the curated 24-case score.

## Agent labels

Categories include single-source retrieval, multi-document comparison, contradictions, absent facts, analytic totals, period intent, multi-tool plans, approval denial, retry recovery, injection, unsupported requests, and attempted workspace crossing. Source labels and expected numbers are authored separately from execution. Independent cases disable shared memory by default. Live-model evaluations should keep the same corpus, configuration, and randomization protocol; do not allow earlier cases to leak answer context through shared memory.

Measured fields include planning validity, expected route agreement, tool selection, argument correctness when labeled, computed-value correctness, task success, recovery, retries, p50/p95 latency, reported tokens, errors, and configured cost. Overall report completion is distinct from task success: a workflow can finish with the wrong intent or miss contradictory evidence. Missing values are not silently marked correct.

Contradiction and evidence-sufficiency labels score the typed finding fields for the relevant cases. Citation-ID membership verifies provenance identity only. Claim-level groundedness, semantic citation correctness, and answer completeness remain null without independently adjudicated claim labels. `metrics.py` can aggregate such labels once supplied. An LLM verifier is never treated as evaluation ground truth.

## Retrieval metrics

Each query has graded relevant source IDs (1 or 2); other sources are unjudged/non-relevant for this small authored set. Rankings are deduplicated by source. Recall@1 and Recall@5 divide retrieved relevant sources by all labeled relevant sources. Precision@5 always divides by 5; queries with only one relevant source cannot exceed 0.2. MRR measures the first relevant source within five. nDCG@5 uses gains `2^grade-1` and an ideal labeled ranking.

Lexical uses BM25 in the measured SQLite comparison; PostgreSQL full-text behavior is integration-tested separately and should be benchmarked separately before claiming the same scores. Hashing is a baseline. Neural dense/hybrid/rerank use actual Sentence Transformers models. Model loading and indexing are timed separately from queries. CPU latency includes local SQL tracing and is not a production throughput estimate. Reranking latency is not free; dense performed slightly better on nDCG in this corpus.

Chunking supports fixed overlapping windows and paragraph-aware packing. Tests verify size limits and content coverage. The retrieval corpus mostly has short documents, so these scores do not establish that one chunking strategy is superior on long PDFs.

## Credentialed configurations

No real provider credentials were present. Official OpenAI and Anthropic SDK paths were exercised using HTTP mock transports, including forced structured tool responses, token usage, a rate-limit retry, invalid output, timeout retries, and a configured model fallback. Those are adapter tests, not live inference logs.

When credentials and supported model IDs are available:

```bash
cd backend
python -m agentos.evaluate --n 24 --mode openai --model "$MODEL_A" --output ../evals/live_a.json
python -m agentos.evaluate --n 24 --mode openai --model "$MODEL_B" --output ../evals/live_b.json
python -m agentos.evaluate --n 24 --mode anthropic --model "$MODEL_C" --output ../evals/live_c.json
```

Run three repeats per configuration. Preserve every row and report variance, not only the best result. Use a fresh benchmark workspace each time. Configure the same embedding revisions, corpus, retrieval settings, and scopes. Record current provider prices explicitly in MODEL_PRICES if estimating cost; otherwise leave cost null. MAX_COST_USD refuses calls without prices, rather than silently ignoring a dollar budget.

Semantic faithfulness still requires claim adjudication or a separately validated judge. Transport success and a passing model review do not establish answer accuracy. Live model evaluations may spend money and send the synthetic/source corpus to the configured provider.

## V3 held-out results

Use the V3 commands, labels and raw measurements in the [engineering report](ENGINEERING_REPORT.md). The nine agent tasks, fourteen retrieval queries, twelve verifier challenges and eight two-turn memory tasks have different units of analysis. Repetitions measure reproducibility. They do not increase the number of distinct questions. The verifier challenge measures decisions on supplied claims. Semantic live-model answer quality is unmeasured.
