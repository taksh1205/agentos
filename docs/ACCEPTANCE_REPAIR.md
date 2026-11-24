# AgentOS acceptance and engineering handoff

This review covers the repaired AgentOS source and the three specified synthetic workflows. The live model was **Qwen2.5-1.5B-Instruct Q4_K_M**, served locally through llama.cpp b12498 and the OpenAI-compatible adapter. Each case used schema-constrained generation, LangGraph checkpoints, a fresh SQLite workspace and stdio MCP. Actual hosted OpenAI and Anthropic calls in this review total **zero**. Local compute cost was unmetered. [Model and server hashes](verification/repair/model-hashes.txt).

## Workflow acceptance

| Workflow | Outcome | Model responses / attempts | Reported tokens | End-to-end seconds | Raw model and tool evidence |
|---|---|---:|---:|---:|---|
| A · Multi-document research | PASS | 3/3 | 2,175 | 61.4 | [Run](verification/repair/released-policy/A.json) |
| B · Period analytics | PASS | 5/5 | 3,012 | 66.5 | [Run](verification/repair/signoff/B.json) |
| C · Approved report | PASS | 5/5 | 2,801 | 29.6 | [Run](verification/repair/released-operation/C.json) |

**Research.** Read the final explanation alongside the cited passages in the A artifact. The inventory minimum covers supply interruptions. The capacity maximum protects fire-lane clearance. The two rules cannot both be satisfied. The report recommends joint review and explicitly leaves precedence unresolved. The corpus included an unrelated rail reimbursement policy as a distractor.

**Analytics.** The MCP results and final report agree with the underlying ledger. February and March revenue were $120,000 and $150,000 (+$30,000, +25.00%), expenses were $78,000 and $90,000 (+$12,000, +15.38%) and profit was $42,000 and $60,000 (+$18,000, +42.86%). Calculation uses the first period as the denominator. The interpretation identifies a measured direction and qualifies causal conclusions. A separately executed [transfer case](verification/repair/released-transfer/B.json) changed both the request and the underlying March records. Revenue fell 12.50%, expenses rose 3.85% and profit fell 42.86%.

**Automation.** At the April 1 cutoff the unpaid overdue invoice was INV-001 for $2,500.00. The harness acted as the approving operator after inspecting the proposed body against the fixture database. The graph reopened its checkpoint, the MCP tool wrote the approved payload, the verifier read back the receipt and replay returned the same record. An interactive approval was exercised separately in Chromium.

## Repairs and decisions

- In `backend/agentos/graph.py`, the compact planner selects an evidence capability and an optional permitted mutation. Mixed evidence requests can expand to an ordered dependency plan. This avoids extra invoice and stock calls on document-only questions. An action consuming evidence depends on the reads that produced it.
- In `backend/agentos/grounded.py`, policy synthesis uses a bounded passage-ID vocabulary, a free-text comparison and structured decisions about review and uncertainty. Exact source text is restored on the server. A weak dense-only tail candidate can be dropped from synthesis when stronger hits exist. Retrieval diagnostics retain candidate rankings. This heuristic can lose a weak but relevant passage and has only limited end-to-end coverage.
- For a single ledger request, the data agent binds enumerated metrics and explicit comparison periods. It checks each MCP result against a separate calculation from source rows. The model selects a focus and direction. Backend code renders exact values and percentage changes. This deliberately limits interpretive freedom on small local models.
- For overdue reports, the model selects invoice identifiers and a follow-up disposition. The agent validates the selection against unpaid rows at the cutoff. It reuses the checked dependency output as the report body before approval. An explicit report-storage target constrains the model’s write choices to a report or no write. This fixes a repeat attempt that misread “follow-up report” as a task. Workspace, tool and exact arguments remain bound to the approval and persisted receipt.
- In `release_check.py` the synthetic approval operator checks currency and invoice IDs against database rows. The earlier operator rejected a correct amount followed by sentence punctuation. In `release_score.py` research needs both operative threshold quotes, analytics needs the reported values and changes, and automation needs the approved payload and replayed receipt. The scorer checks observable properties. Interpretation of the final prose also requires reading the sources.
- Earlier failures are retained. The compact model cited travel reimbursements when given irrelevant passages and later assigned approval authority to the wrong owner. A title counted as a quotation in an earlier scorer. The repaired checks require operative evidence. Prior Qwen3-4B runs encountered provider, planning and resource failures. See [historical model attempts](FINAL_AI_EVALUATION.md). The configurations were changed during debugging, so these runs do not establish a model ranking.

## Independent evaluation

The authored held-out suite matched **9/9** expected outcomes in deterministic mode. One case expected a non-completion outcome. The separate transfer set matched **8/8**. Held-out tool-selection accuracy was 1.000, with 1 retries and p50/p95 latency of 0.069/0.225 s. Transfer p50/p95 was 0.067/0.122 s. The verifier matched 12/12 authored claim labels, including only one positively labeled supported citation. The two-turn offline recall task recovered the target fact 8/8 times with memory and 0/8 without. Semantic faithfulness on open-ended responses has no corpus-wide human score. [Raw evaluations](verification/repair/)

The independent retrieval experiment used 46 documents and 14 labeled queries. Times below are measured query latency and exclude model loading and indexing. The raw results report those costs separately.

| Configuration | Recall@1 | Recall@5 | Precision@5 | MRR | nDCG@5 | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 0.607 | 0.679 | 0.171 | 0.714 | 0.678 | 14.2 |
| hashing_dense | 0.286 | 0.714 | 0.171 | 0.520 | 0.545 | 5.9 |
| neural_dense | 0.786 | 1.000 | 0.257 | 0.964 | 0.974 | 241.3 |
| neural_hybrid | 0.643 | 0.964 | 0.243 | 0.850 | 0.850 | 101.3 |
| neural_weighted_rrf | 0.643 | 1.000 | 0.257 | 0.893 | 0.921 | 110.4 |
| neural_hybrid_rerank | 0.786 | 0.929 | 0.243 | 0.929 | 0.920 | 53.5 |

Dense MiniLM ranked relevant passages best on this corpus. Adding lexical rank helped some queries but reduced overall ranking quality. The reranker recovered part of the loss. Corpus size limits extrapolation. [Per-query evidence](verification/repair/final-retrieval.json)

## Verification matrix

| Feature | Status | Executed evidence and limits |
|---|---|---|
| Backend, security, MCP, real neural retrieval, PostgreSQL and pgvector | PASS | [Backend output](verification/repair/release-validation/backend.log) and [JUnit cases](verification/repair/release-validation/junit.xml). 121 passed, 0 failed, 0 skipped. Isolated PostgreSQL cluster, neural tests enabled. |
| Checkpointed HTTP workflows and approval persistence | PASS | [Three API workflows](verification/repair/release-validation/workflows.json) and [API process restart](verification/repair/release-validation/restart.log). The same database remained running. |
| Frontend tests, Next.js compilation and TypeScript | PASS | [Two tests and production build](verification/repair/final-frontend.log). |
| Chromium console interaction | PASS | [Browser run](verification/repair/browser-retry.log). The initial attempt lacked the browser revision Playwright expected. The rerun used the installed Chromium headless executable. |
| Installation, lint, Python compilation | PASS | [Clean backend install](verification/repair/install.log), [lint and format](verification/repair/lint.log). |
| Docker Compose and remote GitHub CI | BLOCKED | No Docker CLI or socket was available. Remote CI requires a repository event. Compose scripts and the workflow are included. |
| Hosted model inference | BLOCKED | No OpenAI or Anthropic API credentials were configured. Adapter transports are covered in the backend suite. |

A cold offline backend run initially missed TinyBERT weights. After caching them, the neural tests passed. The suite also caught an accidental analytics reference to a research-only variable during the repair. The full suite was rerun after correction. Review the model traces, source snapshots, pending approval, committed effect and replay in sequence. Timing here is a single observation per released workload. These results support an interview walkthrough on the supplied fixtures. Broader live-model reliability and an external review remain open.

## Reproduce

Start with the installation and UI instructions in the [README](../README.md). Activate the virtual environment and install the optional neural and PostgreSQL dependencies. Download the two neural models once before setting offline mode. Set `LLAMA_SERVER`, `MODEL_FILE` and `PG_BIN` to your local binaries and weights. Each results directory must be new.

```bash
(cd backend && python -c 'from agentos.rag import neural_model,cross_model; neural_model("sentence-transformers/all-MiniLM-L6-v2",""); cross_model("cross-encoder/ms-marco-TinyBERT-L-2-v2","")')
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2 LOCAL_CONTEXT=4096 LOCAL_MODEL_ALIAS=qwen15-local
RESULT_DIR="$PWD/run-acceptance" bash scripts/check-local-workflows.sh A B C
RELEASE_TRANSFER=1 RESULT_DIR="$PWD/run-transfer" bash scripts/check-local-workflows.sh B
(cd backend && python -m agentos.release_score ../run-acceptance)
RUN_NEURAL_TESTS=1 OUTPUT_DIR="$PWD/run-postgres" bash scripts/review-postgres.sh
ruff check backend && ruff format --check backend && python -m compileall -q backend/agentos
(cd backend && python -m agentos.evaluate --mode demo --dataset ../evals/datasets/agents-heldout.json --output /tmp/heldout.json)
(cd backend && python -m agentos.evaluate --mode demo --dataset ../evals/datasets/review-transfer.json --output /tmp/transfer.json)
(cd backend && python -m agentos.retrieval_eval --dataset ../evals/datasets/retrieval-heldout.json --neural --output /tmp/retrieval.json)
(cd backend && python -m agentos.claim_eval --output /tmp/claims.json && python -m agentos.memory_eval --output /tmp/memory.json)
(cd frontend && npm ci && npm test && NEXT_PUBLIC_API_URL=http://127.0.0.1:36400 npm run build && npm run typecheck)
```

For the browser run, start the API at port 36400 with `FRONTEND_ORIGIN=http://127.0.0.1:36401` and the compiled frontend with `next start -H 127.0.0.1 -p 36401`. Run `BASE_URL=http://127.0.0.1:36401 npm run test:browser` from frontend. Set `CHROMIUM_PATH` when supplying an existing headless binary. On a Docker host run `bash scripts/verify-compose.sh`, then repeat with `NEURAL=1`. Prior and failed attempts remain available under `docs/verification/`.

## Attempt history and interpretation

The [attempt index](verification/repair/attempt-index.json) retains 25 distinct recorded workspaces from this repair. It includes failed iterations, inconsistent model selections and successes. Across those records there were 118 logged model attempts, 88 recorded responses and 54,111 known tokens. Attempts lacking usage have no token estimate. Code, prompts, corpora and model configurations varied during repair, so aggregating those attempts as a release success probability would be misleading.

The transfer ledger run returned 4 model responses, used 2,591 recorded tokens and took 90.4 s. The [repeat approval](verification/repair/operation-repeat/C.json) used a different synthetic workspace. The raw JSON preserves application trace events, structured findings, fixture records and exact synthetic receipts. It omits private model reasoning and secret headers. GGUF weights and runtime build products are separate downloads.

Seven focused regression tests also passed from a clean extraction of the source ZIP. These seven are included in the 121-test suite. [Archive smoke test](verification/repair/archive-smoke.log).

The package is suitable for source and portfolio review. Public deployment, external identity-provider integration and hosted-model reliability require separate acceptance.
