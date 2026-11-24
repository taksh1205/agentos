# AgentOS V3 engineering handoff

**Taksh Pathak · Independent review copy**

AgentOS combines document evidence, computed business metrics and approval-controlled local actions in a checkpointed LangGraph workflow. This release upgrades the supplied V2 archive with SHA-256 `5f8ad9d945b311d6b93b3fd720f4aa70e5786b193e44658b60c00f5c8cbc6596`. The final source manifest hashes each packaged file except the manifest itself.

## A. Changes made

| Location | Change and consequence |
|---|---|
| `backend/agentos/models.py` | The planner can request clarification and define structured completion checks. Claims bind metrics, comparison periods, quotes and receipts. The provider accounts for billed invalid responses, distinguishes unknown usage and prices fallbacks by actual model. |
| `coordination.py`, `graph.py` | Validate capability ownership and plan arguments. Pass transitive predecessor evidence into dependent agents, check a ready action's evidence before requesting approval, return correction issues to the planner, and verify committed results. Reports in offline mode now include their evidence. |
| `verification.py` | Check directions, period bases, metric bindings, numeric values, cited quotations and receipts. Preserve a separate review state for paraphrases and causation. |
| `rag.py`, `retrieval_eval.py` | Compare a dense-weighted fusion configuration with the existing ranking methods. Apply PostgreSQL metadata filters before candidate limits. Pin the neural profile's model revisions and select its search method explicitly. |
| `api.py`, `tools.py`, `mcp_client.py`, `mcp_server.py` | Write a job and its run-state transition atomically. Bind approval jobs to the pending proposal at replay. Check read scopes, deny empty permission sets, restrict subprocess environment, and load the MCP encoder only on search. |
| `ingestion.py` | Run PDF extraction in a killable subprocess with bounded input, page count, output and wall time. Linux applies CPU and memory limits inside the worker. |
| `evaluate.py`, `claim_eval.py`, `workflow_check.py` | Execute separate authored cases, score observable labels, and capture the complete HTTP research, analytics and approved-action exercise. |
| `frontend/app/page.tsx` | Send the displayed proposal ID, show clarification and grounding review status, distinguish unreported tokens, and label output as a workflow result. |
| `scripts/verify-compose.sh`, CI, fixtures, tests | Add repeatable container verification and include it in CI. Expand provider, coordination, grounding, job replay and permission tests. Application schema version 2 remains compatible with V2; the changes require no new table or destructive migration. |

## B. Verification matrix

Evidence paths below are relative to `docs/verification/v3/`.

| Feature | Implemented | Actually executed | Evidence | Remaining limitations |
|---|---|---|---|---|
| Structured LLM plans, handoffs, analytical interpretation, synthesis and review | Yes | OpenAI and Anthropic official SDKs with HTTP mocks, each through the graph and approval | `backend-junit.xml`, `tests/test_release.py` in backend | Live instruction following, token use and API cost have no measurements. |
| Neural retrieval and cross-encoder | Yes | CPU inference, 2 corpora, 6 configurations per corpus | `retrieval-development.json`, `retrieval-heldout.json` | Small synthetic corpora. Retrieval-only timings include the common pipeline and differ from server throughput. |
| MCP business tools and exact local effects | Yes, 11 tools | Real stdio calls through FastAPI and LangGraph, including search, analytics and report creation | `workflows.json`, `integrated-server.txt` | Local synthetic records. Each MCP invocation starts a subprocess. |
| Approvals, recovery and persistence | Yes | Preflight veto, two dependent approvals, stale decision rejection, PostgreSQL checkpoint reopen and API restart | `backend-junit.xml`, `restart.txt` | A single scheduler owns the database. Restart checks do not simulate a host or disk failure. |
| Workspace access, OIDC, input safeguards | Yes | Signed test tokens, claim rejection, tenant isolation, tool scope checks, PDF worker and representative injection cases | `backend-junit.xml` | No external identity-provider or comprehensive adversarial evaluation. |
| Persistent semantic memory | Yes | Neural lookup plus deterministic answer extraction on eight two-turn tasks | `memory.json` | Exact fact recall. General conversational reasoning unmeasured. |
| Browser and frontend | Yes | Two DOM tests, production build, TypeScript, one Chromium run covering execution, approval and experiments | `frontend-tests.txt`, `frontend-build.txt`, `frontend-typecheck.txt`, `browser.txt` | One local browser and synthetic user journey. |
| PostgreSQL and pgvector | Yes | Three dedicated tests included in full suite, plus integrated workflows | `final-postgres.txt`, `backend-junit.xml`, `workflows.json` | No managed cloud database, load testing or multi-worker certification. |
| Docker Compose and hosted CI | Configured | Compose verifier passed shell syntax checking. Docker executable unavailable. Hosted CI has not run for this release. | `environment.json`, `scripts/verify-compose.sh`, CI workflow | Requires a Docker host. |
| External LLM service | Official adapters implemented | 0 live OpenAI requests, 0 live Anthropic requests | `environment.json` | No secure provider credentials in the environment. |

## C. Test report and reproduction

The exact V2 backend passed 71/71 after repairing the CPU runtime. The first portable run passed 66 and skipped five optional checks. An initial full run passed 69 and failed two neural imports with PyTorch 2.5.1. CPU PyTorch 2.6.0 resolved the incompatibility; the untouched baseline then passed all 71. V3 passed **89/89 backend tests, 0 failed, 0 skipped**. The 3 PostgreSQL and 2 dedicated neural tests are included in 89. A fresh extraction of the release source independently passed all 84 portable backend tests, with the five opt-in PostgreSQL/neural tests skipped in that second run. See `clean-extraction-smoke.txt`. The separate frontend suite passed **2/2**. Chromium passed **1/1** end-to-end workflow test. The three additional HTTP acceptance scenarios all passed and all three results survived restarting the API. A transient validation-harness PostgreSQL lock caused three connection failures in an intermediate rerun. A fresh UTF-8 cluster resolved the conflict. Initial and final logs are both retained.

Reproduce the backend and evaluation checks from `backend/` with a disposable database, the dependencies from the README, and the two neural models cached or downloadable. For PostgreSQL, set `TEST_POSTGRES_URL` to a database on which the test user can install pgvector. Set `HF_HUB_OFFLINE=1` only after caching weights.

```bash
python -m compileall -q agentos tests
ruff check agentos tests
ruff format --check agentos tests
RUN_NEURAL_TESTS=1 OMP_NUM_THREADS=2 python -m pytest -q -ra --junitxml=/tmp/agentos-junit.xml
python -m agentos.evaluate --n 24 --output /tmp/agent-regression.json
for i in 1 2 3; do
  python -m agentos.evaluate --dataset ../evals/datasets/agents-heldout.json --output "/tmp/agent-heldout-$i.json"
done
python -m agentos.retrieval_eval --neural --output /tmp/retrieval-development.json
python -m agentos.retrieval_eval --neural --dataset ../evals/datasets/retrieval-heldout.json --output /tmp/retrieval-heldout.json
python -m agentos.memory_eval --backend neural --output /tmp/memory.json
python -m agentos.claim_eval --output /tmp/claims.json
```

From `frontend/`, run `npm ci`, `npm test`, `npm run build`, and `npm run typecheck`. Start the frontend and API, install Chromium with `npx playwright install chromium-headless-shell`, then run `npm run test:browser`. Browser screenshots in this release come from that run. For the integrated HTTP acceptance test, the runner used PostgreSQL for application data and checkpoints, `USE_MCP=true`, `EMBEDDING_BACKEND=neural`, `RETRIEVAL_METHOD=rerank`, and the TinyBERT reranker. Run `python -m agentos.workflow_check --output /tmp/workflows.json` from backend against that local API. Full command and service details appear in the validation transcript script next to the logs.

## D. AI evaluation

The deterministic agent baseline met all expected conditions on **21/24** original cases and **5/9** held-out cases. Each of three held-out repetitions produced the same per-case pass/fail outcomes (27 executions, nine distinct tasks). Expected agent routing and exact tool selection each matched on 8/9 first-run cases. Median and p95 first-run latency were 17.9 and 114.0 ms. The repeated runs' p95 values were 117.5 and 197.8 ms. The graph used one retry per repetition, incurred zero model tokens and zero API charges, and raised no uncaught case exception.

**Where the baseline failed.** h01 and h09 requested specific months; the offline parser selected a broader period. h02 retrieved the two conflicting sources but did not identify the conflict. h05 recovered from the injected analytics timeout but omitted the requested report action. The labeled argument check was 0/1, the full-task recovery check was 0/1, and approval behavior matched on 1/2 labeled action cases. The earlier regression suite retains the V2 required-tool coverage criterion; the new held-out runner additionally checks for extra tools, excluding schema discovery.

On h08, all three required literal answer fragments appeared. Only 2/5 cited documents matched the source labels on each of the two source-labeled questions. Those document-precision and fragment metrics do not establish semantic entailment. The verifier's first pass on a 12-case supplied-claim challenge matched 11/12 labels. A valid spelled-out percentage was mishandled. After a unit-normalization fix and a regression test, the same set matched 12/12. This last result is a post-fix regression measurement; its citation-support precision has just one accepted citation case. Human-rated synthesis quality remains unavailable.

Neural memory retrieved the required prior fact in 8/8 memory-enabled trials versus 0/8 disabled. Mean enabled latency was 11.7 ms. Answers used a deterministic extractor. Neural retrieval executed 216 ranked query/configuration combinations across 36 distinct questions; each configuration's full ranked IDs, latency, indexing time and model descriptor are recorded.

| Held-out method | Recall@5 | MRR@5 | nDCG@5 | Mean query ms |
|---|---:|---:|---:|---:|
| lexical | 0.679 | 0.714 | 0.678 | 4.8 |
| hashing_dense | 0.714 | 0.520 | 0.545 | 4.5 |
| neural_dense | 1.000 | 0.964 | 0.974 | 27.9 |
| neural_hybrid | 0.964 | 0.850 | 0.850 | 28.5 |
| neural_weighted_rrf | 1.000 | 0.893 | 0.921 | 18.9 |
| neural_hybrid_rerank | 0.929 | 0.929 | 0.920 | 40.3 |

The same dense encoder ranked highest by nDCG on the development set. Equal-weight fusion can move weak lexical matches ahead of semantic matches. Reducing lexical weight narrowed the held-out gap; rescoring with TinyBERT did not exceed dense retrieval on this corpus. Neither benchmark involved external production documents. The separate 1,200 generated parameter combinations remain historical generation artifacts. They were not executed in V3.

## E. GitHub readiness

Suitable for public **source review and private portfolio demonstrations** with the included synthetic data. The release contains its original license, dependency specifications, setup instructions, OpenAPI schema, CI workflow, tests, examples and raw evidence. No repository was published. Before claiming live agent quality, run all three workflows with an actual configured provider and review grounded answers. Before claiming container deployment, execute the Compose verifier on a Docker host. Shared service operation also requires configured identity, TLS, secret management, retention, backups and capacity testing.

## F. Reviewer handoff

Start with the stored operational run. Match the proposal digest and receipt to the action trace, inspect the two cited policies and recompute totals from the seeded sales rows. Then run the SDK graph tests and substitute the same live provider on a private synthetic workspace. Review claim text against typed metadata, especially multi-metric sentences, ambiguous causation and conflicting policies. Check both a preflight veto and stale approval replay. Finally inspect the first and second ranked sources for held-out question hq2. The per-query comparison explains why the deployment default changed. All evidence from V2 remains under the original evaluation paths and historical report.
