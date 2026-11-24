# AgentOS V2 engineering report

Prepared November 17, 2026 for Taksh Pathak. This report describes the upgraded supplied repository, not a disconnected rewrite. No GitHub push or invented commit/deployment history was created.

## Verification counts and evidence

| Check | Executed | Passed | Skipped | Evidence |
|---|---:|---:|---:|---|
| V1 baseline suite | 20 | 19 | 1 PostgreSQL | `docs/baseline/v1-original-test-output.txt`; baseline rerun observed 19 passed, 1 skipped |
| V2 combined backend suite | 71 | 71 | 0 | `docs/verification/backend-tests.txt` |
| Separate PostgreSQL diagnostic suite | 3 | 3 | 0 | `docs/verification/postgres-tests.txt`; included again in the 71, not additional unique tests |
| Frontend DOM interactions, mocked API | 2 | 2 | 0 | `docs/verification/frontend-interactions.txt` |
| Real Chromium browser workflow script | 1 | 1 | 0 | `docs/verification/browser-test.txt` and screenshots |
| Production frontend compilation/TypeScript | 1 build | passed | 0 | `docs/verification/frontend-build.txt` |
| Python formatting/lint | repository checks | passed | 0 | `docs/verification/lint.txt`, `format.txt` |

The final period-validation edit also received seven targeted backend checks; their raw output is `docs/verification/final-targeted-checks.txt`. These are repeated checks of existing tests, not seven extra unique cases. A final source/header/API export check is recorded separately. Failed diagnostic attempts were used to fix defects, not counted as passing tests.

## Feature status

| Feature | Implemented | Tested | Evidence | Limitations |
|---|---|---|---|---|
| Existing-codebase upgrade | Yes | Exact input digest checked, V1 tests retained | `AUDIT_V2.md`; baseline evidence | No remote repository or commit history generated |
| Model-driven planning/tool selection | Yes | Scripted structured-plan graph integration | `test_v2.py`; provider tests | No live inference credentials; intelligence quality unverified |
| OpenAI provider | Official async SDK, typed tool responses, retry/fallback/usage | HTTP mock transport | `test_providers.py` | **0 live OpenAI calls** |
| Anthropic provider | Official async SDK, typed tool responses and usage | HTTP mock transport using SDK-compatible transport | `test_providers.py` | **0 live Anthropic calls** |
| Dependency-aware five-agent graph | Yes | Invalid DAGs, Send parallelism, replay-safe aggregation, correction bounds | `test_system.py`, `test_v2.py` | No large-scale concurrent load test |
| Research synthesis/contradictions | Typed live path and multi-query search | Scripted synthesis and citation validation; real neural retrieval | Graph tests, `test_neural.py` | No live semantic groundedness or contradiction-quality score |
| Analytics | Schema discovery, approved metrics, filtering, trend/period comparison, numeric checks | Actual SQLite and PostgreSQL records | Analytics, numeric and integration tests | Fixed curated datasets; offline intent rules miss some requests |
| Six local actions | Reports, CSV, follow-ups, email drafts, inventory updates, notifications | Each action exercised with exact approvals and replay | `test_all_mutations_exact_approval`; PostgreSQL update check | Local artifacts only; no external messages sent |
| Approval safety | Persisted canonical proposal, argument digest, interrupt/resume, unique effect receipt | Denial, changed arguments, restart, same-ID tenants, cached proposal | Graph/tool/API tests | Approval UI is not an identity-provider login |
| MCP | 11 scoped tools and validated timeout-bound client | Independent round trips and integrated graph | MCP tests and trace records | Stdio host trust; no network MCP authentication mode |
| Neural embeddings | Actual Sentence Transformers CPU inference | Normalization, retrieval, graph integration | Neural tests, retrieval raw results | One encoder evaluated; no custom training |
| Hybrid/RRF/reranking | BM25/PG lexical, dense candidates, RRF, real cross-encoder | Five independent configurations executed | `evals/retrieval-results.json` | Small synthetic corpus; PostgreSQL ranking not benchmarked against SQLite ranking |
| Document lifecycle | Hash-idempotent upsert, replace, delete, metadata, reindex, dimension/model namespace | Real local lifecycle and PG dimension change | RAG and migration tests | Reindex is document-transactional; hostile PDF isolation remains limited |
| Semantic memory | Embeddings, workspace, TTL, deduplication, provenance, bounded compaction | Memory tests and 32 two-turn trials across hashing/neural encoders | `memory-results.json`, tests | Offline answer extraction; no live-model memory score or comprehensive erasure |
| Durable execution | Persisted jobs, restart recovery, cancellation, single-worker guard | Queue recovery and API tests | `test_security_jobs.py` | One scheduler per database; no horizontal worker guarantee |
| Checkpoint persistence | SQLite and PostgreSQL savers | Restart approval with both backends | Original restart test and PG checkpoint test | No prolonged outage/chaos campaign |
| Budgets/retries | Atomic shared reservations, conservative unknown usage, explicit price table | Reservation concurrency, retry/rate-limit/fallback tests | Budget/provider tests | Dollar accuracy depends on configured prices; no live billing validation |
| Authentication/security | Local/RS256 OIDC split, claims, scope intersection, rate limiting, tenant predicates | Signed-token, access, injection, scope, rate-limit tests | `test_security_jobs.py`, adversarial tests | External issuer/JWKS deployment, SSO UI, TLS/RLS and public-load defense unverified |
| Observability | Persisted plan/tool/model/retrieval traces; optional metadata-only OTel | Local traces/API and browser inspection | API tests, screenshots | External OTel collector export not exercised |
| Dashboard | Natural-language auto mode, dependencies, traces, evidence, exact approvals, metrics | DOM tests and real Chromium | Screenshots and browser log | Real screenshots show offline agent execution |
| Docker/CI | Compose local/neural/OIDC profiles, migrations, CI jobs | Configuration/code reviewed; CI commands exercised locally where possible | Configurations and local logs | Docker unavailable; images/Compose and GitHub CI were not run |

## Actual experiments

### Curated agent baseline

- 24 labeled authored cases executed in **demo/offline** mode with independent-case memory disabled.
- 21/24 met all labeled task expectations (87.5%).
- Route agreement: 1.000; tool-selection agreement: 1.000.
- p50 latency: 0.0205s; p95: 0.0525s. These small local measurements are not throughput claims.
- 0 inference tokens and $0 API cost because this run was deterministic.
- The rule baseline failed `a03` (contradiction handling), `a04` (missing-fact qualification), and `a23` (February-only intent). Completed execution is distinct from correctness.
- Groundedness, claim entailment and semantic citation scores remain unlabeled/null. No live three-model comparison was executed.

### Retrieval benchmark

32 authored synthetic documents, 22 labeled queries, five actual configurations: **110 measured retrieval queries**. This is separate from answer generation.

| Configuration | Recall@1 | Recall@5 | Precision@5 | MRR | nDCG@5 | Mean query ms |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 0.727 | 0.864 | 0.209 | 0.894 | 0.852 | 2.60 |
| hashing_dense | 0.386 | 0.750 | 0.182 | 0.617 | 0.607 | 2.59 |
| neural_dense | 0.864 | 0.977 | 0.245 | 1.000 | 0.983 | 17.46 |
| neural_hybrid | 0.818 | 0.886 | 0.218 | 0.955 | 0.904 | 16.09 |
| neural_hybrid_rerank | 0.864 | 0.977 | 0.245 | 1.000 | 0.977 | 36.79 |

Neural dense had the strongest nDCG on this corpus. Hybrid fusion did not improve it; reranking recovered recall with added latency. Exact encoder revision, indexing/load timings, and raw rankings are preserved. These are not generalization or live-agent accuracy claims.

### Memory experiment

Eight two-turn authored fact-recall tasks were executed with and without memory using hashing and neural embeddings (16 trials per configuration, 32 trials total). Both configurations scored 0/8 without context and 8/8 with context using offline explicit extraction, with zero LLM tokens. The neural configuration did perform genuine local embedding inference. This measures availability of retained facts, not general language reasoning. Each task has a separate workspace to prevent cross-task hints. Live-provider answer mode exists but was not run.

### Generated scenarios and browser setup

`generated-scenarios.jsonl` contains 1,200 generated parameter/context/action combinations; **they were not executed**. Historical V1 repetitive cases are isolated under `evals/historical-v1` and are not evidence for V2 intelligence. The browser setup additionally ran two deterministic warm-up cases to populate the real experiment table; they are excluded from the 24-case headline score.

## Infrastructure actually exercised

- PostgreSQL **16.2** and pgvector **0.6.2**, local TCP, UTF-8 database.
- pgvector indexing, tenant filtering, dimension-changing reindex, actual approved update, and PostgreSQL checkpoint interrupt/restart/resume.
- SQLite application data, graph checkpoints, durable queue, API integration.
- Actual CPU Sentence Transformers encoder and cross-encoder inference.
- Next.js production server, FastAPI server, Chromium Headless Shell, real browser approvals and experiment display.
- No Docker daemon was available. No external identity provider, OTel collector, customer connector, or paid LLM endpoint was called.

Initial Unix-socket startup attempts failed under environment restrictions. A supported TCP configuration allowed actual PostgreSQL tests. An initial SQL_ASCII test cluster exposed text decoding behavior; recreating the disposable cluster as UTF-8 resolved it. Browser testing exposed an unknown-cost rendering exception; that defect was fixed and regression covered. Final passing logs supersede the diagnostic failures without hiding their causes.

## Phase acceptance

Baseline audit completed. Typed/provider workflow implementation is tested with mocks; live inference acceptance remains open. Neural RAG and independent comparison were exercised. Local tools/MCP and approval workflows were exercised. Evaluation infrastructure and offline/neural runs are delivered; live judged comparisons remain open. Single-worker reliability and shared-auth token validation are tested; external deployment validation remains open. Dashboard/browser integration is exercised. PostgreSQL validation is complete for the included tests; Docker validation remains open. Source, evidence, documentation, and review ZIP are delivered without a GitHub push.

## Remaining work before stronger claims

1. Run real credentialed planning/synthesis/verification across supported models, repeat evaluations, adjudicate claims, and inspect failures.
2. Expand beyond a small authored corpus and benchmark PostgreSQL full-text/HNSW behavior at scale.
3. Validate OIDC against a real issuer, add a login flow/TLS, sandbox public PDF parsing, and complete deletion/retention across history and memory.
4. Build/run Docker images and CI on GitHub; external business connectors and horizontal workers require separate engineering and validation.

The implemented application is substantially stronger and more measurable than V1. Evidence still does not justify claims of deployed customer operation or verified live-model intelligence.
