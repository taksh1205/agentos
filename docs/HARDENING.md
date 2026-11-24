# AgentOS final hardening review

The source ZIP upgrades baseline SHA-256 `9ed34ed18738a4fbac3b5320b88013c414637c0f1cefa3d662dc4a2b22aac3d3`. Both archives remain independently identifiable. The final package includes the source manifest and raw results. All model-backed measurements below used a local Qwen2.5-1.5B-Instruct Q4_K_M model through llama.cpp b12498 with the OpenAI-compatible structured-output adapter. [Weights and server checksums](verification/repair/model-hashes.txt).

## Original acceptance matrix

| Workflow | Result | Responses | Tokens | Seconds | Evidence |
|---|---|---:|---:|---:|---|
| Depot policy comparison | PASS | 3 | 2,178 | 44.6 | [raw run](verification/hardening/signoff/A.json) |
| February–March ledger | PASS | 5 | 3,012 | 42.3 | [raw run](verification/hardening/signoff/B.json) |
| Approved overdue report | PASS | 5 | 2,777 | 30.2 | [raw run](verification/hardening/signoff/C.json) |

Each run started with a fresh workspace. The research result identified both incompatible pallet thresholds and cited their operative clauses. The ledger calculation matched the database for all three metrics. The approval workflow reopened its checkpoint and verified the persisted report and idempotent replay. See the [per-condition checks](verification/hardening/signoff-scores.json) and the [initial run](verification/hardening/original-scores.json). The original release also passed all three tasks before this pass.

## Generalization trials

The new fixtures, distractors and expected outcomes were written before running inference. Only the user question, workspace evidence and permitted tools were available to the graph. Each case ran twice on fresh data with the same model and fixed seed. Repetition tests execution consistency. The three distinct tasks provide the evidence for generalization. No hosted model calls were made and compute cost was unmetered.

| Unfamiliar task | Passed / executed | Median seconds | p95 seconds | Total tokens |
|---|---:|---:|---:|---:|
| Orion retention rules | 2/2 | 48.3 | 50.7 | 5,084 |
| July–August costs and profit | 2/2 | 32.2 | 46.1 | 4,444 |
| September collections report | 2/2 | 40.2 | 55.3 | 5,981 |

With two observations per case, nearest-rank p95 equals the slower run. Latency includes the graph, tokenizer/model requests, MCP startup and, for research, document indexing. Runs on the same host could compete for CPU. The recorded durations should be used for reproduction context only. [Independent labels](../evals/datasets/live-hardening.json) · [Individual checks, tokens and timings](verification/hardening/trial-scores.json) · [All six original traces](verification/hardening/trials/).

- **Research** compared a nine-month minimum retention period for inspection images with a four-month deletion deadline. Both runs cited the clauses, excluded the cafeteria document and recommended joint review where precedence was unclear. The model also repeated a source heading. This added no substantive information.
- **Analytics** selected costs and profit. Costs rose from $60,000 to $64,500 (+7.50%). Profit fell from $36,000 to $33,000 (−8.33%). Each expected value and change was checked against the labeled row and its own metric sentence.
- **Automation** identified two overdue invoices for $615.50 and $220.00. The paid invoice and the one due on the cutoff date were excluded. Both runs waited for the synthetic test operator, stored the approved $835.50 report, and returned its original receipt on replay. The human-facing approval path was tested separately in Chromium.

All six new trials matched their labeled expectations. There were zero observed task failures. The observed 6/6 does not estimate success on arbitrary requests or other model configurations. Golden values and expected tool sequences live in evaluation code and data. The application uses the existing planner and tool interfaces.

## Reliability changes

- Report titles use the first sentence of the request and a word boundary with a visible ellipsis for a long title. The two-invoice run produced “Review overdue invoices as of 2026-09-15”. The body retains the complete verified result.
- The approval test operator previously compared unordered sets of invoice identifiers and amounts. That could accept two valid amounts attached to the wrong invoices. A regression reproduces the swap and checks the correct mapping as well. This check is additional to the application’s workspace, role, digest, committed-receipt and replay checks.
- `grounding.fully_checked` concerns the structured claims. `grounding.requires_review` can still be true when the summary contains additional interpretation. The UI explains this distinction. An automatic model endorsement is separate from a human review. A regression covers a supported quote followed by an unsupported inference.
- The runner now retains a separate file for repeated cases. The scorer records the distinct workspace for each run and rejects duplicate workspaces. Missing trials have a zero executed count and unavailable latency.
- Three new backend tests joined the 121-test baseline. The deployed application gained no new service or framework.

## Retrieval comparison

The original labeled corpus uses 46 documents and 14 queries. All six configurations ran again. Dense MiniLM retained its top rank. Lexical evidence improved some individual matches while reducing aggregate ranking quality when fused equally. The cross-encoder recovered part of that loss at additional inference cost. [Per-query results](verification/hardening/retrieval.json).

| Configuration | Recall@5 | nDCG@5 | p95 query ms |
|---|---:|---:|---:|
| lexical | 0.679 | 0.678 | 16.4 |
| hashing_dense | 0.714 | 0.545 | 17.3 |
| neural_dense | 1.000 | 0.974 | 55.2 |
| neural_hybrid | 0.964 | 0.850 | 25.0 |
| neural_weighted_rrf | 1.000 | 0.921 | 56.0 |
| neural_hybrid_rerank | 0.929 | 0.920 | 177.7 |

The deterministic held-out suites separately matched 9/9 and 8/8 authored outcomes. The challenge verifier matched 12/12 supplied claim labels. The two-turn memory ablation recovered 8/8 labeled facts with memory enabled and 0/8 disabled. [Held-out](verification/hardening/offline-heldout.json) · [Transfer](verification/hardening/offline-transfer.json) · [Claim verifier](verification/hardening/claims.json) · [Memory](verification/hardening/memory.json).

## Integration and disclosure review

| Check | Result | Evidence and boundary |
|---|---|---|
| Backend, MCP, neural tests, security, isolation, approvals and PostgreSQL | PASS | 124 passed, 0 failed, 0 skipped. [Pytest](verification/hardening/final-postgres/backend.log) · [JUnit test names](verification/hardening/final-postgres/junit.xml) |
| Startup, schema migration, PostgreSQL-backed HTTP workflows and checkpoint recovery | PASS | Fresh cluster with pgvector. Three workflow records and one approved receipt survived the API restart. [Migration](verification/hardening/final-postgres/migration.log) · [API workflows](verification/hardening/final-postgres/workflows.json) · [Restart](verification/hardening/final-postgres/restart.log) |
| Clean Python installation | PASS | New virtual environment, locked dependencies, wheel installation, dependency check, SQLite schema bootstrap and application import outside the source tree. [Log](verification/hardening/clean-install.log) |
| Next.js and browser | PASS | Clean npm install, 2 frontend tests, build, typecheck, and 1 Chromium workflow including human approval. [Build](verification/hardening/frontend.log) · [Browser](verification/hardening/browser.log) |
| Python lint, format and compilation | PASS | [Static checks](verification/hardening/static.log) |
| Archive disclosure checks | PASS within scope | Scanned packaged text for common private keys, provider credentials, AWS access keys, signed URLs and email domains. Reviewed matches. Demo credentials are intentionally documented. Only synthetic UI screenshots are included. This is a scoped disclosure scan. [Scan record](verification/hardening/disclosure-scan.json) |
| Docker Compose runtime | BLOCKED | No Docker executable, daemon socket or Podman was available. The shell verifier passed syntax checking. [Environment](verification/hardening/infrastructure.log) |
| Hosted GitHub Actions | BLOCKED | The archive has no Git remote and the requested review precedes publication. Local tests exercised the backend, frontend and neural checks. |
| Hosted OpenAI / Anthropic | BLOCKED for live inference | The hosted adapters have transport tests. The recorded live runs used local inference. |

## Reproduce

Use the [README installation instructions](../README.md) to create the virtual environment and install the optional neural and PostgreSQL dependencies. Use the local inference binary and weights matching the published hashes. Cache both the embedding and reranking models before enabling offline mode. From the repository root, with the virtual environment activated:

```bash
(cd backend && python -c 'from agentos.rag import neural_model,cross_model; neural_model("sentence-transformers/all-MiniLM-L6-v2",""); cross_model("cross-encoder/ms-marco-TinyBERT-L-2-v2","")')
export HF_HUB_OFFLINE=1 LOCAL_CONTEXT=4096 LOCAL_MODEL_ALIAS=qwen15-local OMP_NUM_THREADS=2
# Set MODEL_FILE and LLAMA_SERVER to the local GGUF and llama-server executable.
RESULT_DIR="$PWD/originals-run" bash scripts/check-local-workflows.sh A B C
RESULT_DIR="$PWD/trials-run" bash scripts/check-local-workflows.sh L I R L I R
(cd backend && python -m agentos.release_score ../originals-run)
(cd backend && python -m agentos.hardening_eval ../trials-run)
# Set PG_BIN to the PostgreSQL binary directory with pgvector installed.
RUN_NEURAL_TESTS=1 OUTPUT_DIR="$PWD/postgres-run" bash scripts/review-postgres.sh
(cd backend && python -m agentos.retrieval_eval --dataset ../evals/datasets/retrieval-heldout.json --neural --output /tmp/retrieval.json)
(cd frontend && npm ci && npm test && NEXT_PUBLIC_API_URL=http://127.0.0.1:36400 npm run build && npm run typecheck)
```

For the browser check, serve the API at port 36400 with `FRONTEND_ORIGIN=http://127.0.0.1:36401`. Serve the compiled frontend on port 36401, then run `npx playwright install chromium-headless-shell` and `BASE_URL=http://127.0.0.1:36401 npm run test:browser` from frontend. On a Docker host, run `bash scripts/verify-compose.sh` and repeat with `NEURAL=1`. Hosted CI and publication remain pending independent approval.
