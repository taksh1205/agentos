# AgentOS V3

**Evidence-grounded agent orchestration, restricted business tools, and measurable retrieval.**

AgentOS is an AI engineering portfolio project by **Taksh Pathak**. It accepts a natural-language goal, builds a dependency-aware agent plan, retrieves document evidence, computes approved business metrics, proposes local actions for review, and verifies the results. The interface exposes plans, tool traces, citations, approvals, and actual evaluation records.

The same request can cross three different boundaries. A model can propose a question, the analytics service can establish a number, and only a person with the appropriate workspace role can authorize a write. AgentOS keeps the evidence and the approval attached to that run. It is designed for reviewing those decisions in a local engineering environment.

**Local model verification.** All three original workflows passed. Three unfamiliar tasks also passed twice each in fresh workspaces using Qwen2.5-1.5B-Instruct, neural document retrieval where applicable, and real MCP tools. The backend suite passed 124 tests with PostgreSQL and neural checks enabled. The [hardening report](docs/HARDENING.md) links each result to its fixture, checks and trace. These small synthetic evaluations measure the listed tasks.

![AgentOS console showing an actual deterministic execution](docs/screenshots/workspace.png)

## What problem this solves

Combining business records with unstructured policies and approved actions requires different trust boundaries. Analytics must compute from database rows, research must cite documents, and mutations must wait for a person. AgentOS separates these responsibilities so failures and permissions are inspectable rather than buried in one unrestricted prompt.

Multi-agent orchestration is useful here because retrieval and analytics can run independently, actions depend on their outputs, and verification can request a bounded correction. A single model call is still the better choice for simple questions; the platform does not claim that five agents automatically improve accuracy.

## Run the local offline baseline

Python 3.12, Node 22+, and npm are recommended. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-lock.txt
pip install --no-deps -e backend
cd backend
uvicorn agentos.api:app --port 8000
```

In a second terminal, from the root:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Go to **Knowledge → Load synthetic demo dataset**. The local token is `local-demo-token`. Default mode uses deterministic agent rules and hashing, costs no inference money, and requires no model download. Keep **Auto · capability planning** selected; the legacy workflow choices exist only for V1 regression demonstrations.

## Enable the intended neural retrieval experience

Install the optional ML dependencies. CPU-only PyTorch avoids unnecessary GPU packages:

```bash
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
pip install -e 'backend[ml]' -c backend/neural-constraints.txt
export EMBEDDING_BACKEND=neural
export EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
export RETRIEVAL_METHOD=dense
# Optional reranking: set RETRIEVAL_METHOD=rerank and
# export RERANK_MODEL=cross-encoder/ms-marco-TinyBERT-L-2-v2
cd backend
uvicorn agentos.api:app --port 8000
```

The encoder normalizes vectors. The cross-encoder jointly scores query/passage pairs after candidate retrieval. Both use actual local Transformer inference through Sentence Transformers. No custom model training is claimed. Pin `EMBEDDING_REVISION` and `RERANK_REVISION` for reproducibility; the encoder also resolves the cached model commit into its namespace. Changing encoder/revision/dimension requires `POST /documents/reindex` as admin. Model downloads need network access.

To use a real reasoning model, export `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` securely before starting the backend, then choose that provider and a supported model ID in the console. Do not paste keys into chat or source files. `OPENAI_BASE_URL` supports a host-configured compatible endpoint. Hosted OpenAI and Anthropic were tested with mocked transport. Real local inference used the OpenAI-compatible adapter with Qwen GGUF weights and llama.cpp. See the review report for results by configuration.

## Architecture

```mermaid
flowchart TD
    Console[Next.js console] --> API[FastAPI identity and durable jobs]
    API --> Planner[Planner agent]
    Planner --> Scheduler[Dependency scheduler]
    Scheduler --> Research[Research agent]
    Scheduler --> Data[Data analysis agent]
    Research --> Scheduler
    Data --> Scheduler
    Verification -->|Evidence accepted| Action[Action agent]
    Action --> Approval[Exact-argument approval]
    Approval --> Action
    Action --> Scheduler
    Scheduler --> Verification[Verification agent]
    Verification -->|One correction| Planner
    Verification --> Result[Report and scoped memory]
```

| Agent | Live provider path | Deterministic boundaries |
|---|---|---|
| Planner | Typed goal interpretation, capability/tool selection, completion criteria, dependency DAG | Reject unknown tools, cycles, missing dependencies, and mutations routed through read agents |
| Research | Query rewriting, multiple searches, claim-level cited synthesis, contradictions and insufficient evidence | Tenant-scoped retrieval, bounded context, known citation IDs, required citations for live claims |
| Data Analysis | Structured dataset/metric/period intent and interpretation of computed results | Discover schemas; allowlisted SQL templates; source-row recomputation; numeric assertion checks |
| Action | Select and prepare one typed local operation using available evidence | Persist exact proposal; interrupt; require authorized approval; transaction and idempotent receipt |
| Verification | Review completion, factual support, contradictions, and corrections | Check step completion, citation IDs, recomputed data, and committed effect records |

An LLM judge is one fallible check, not ground truth. The offline mode uses explicit planning/intent rules and extractive passages, not model reasoning. Structured-response orchestration tests use scripted responses and are labeled accordingly.

## Tools and MCP

A real stdio MCP server/client exposes **11 allowlisted tools**: document search, dataset schema, business metrics, inventory retrieval, invoice analysis, report creation, CSV export, follow-up creation, email drafting, inventory update, and local notification creation.

Set `USE_MCP=true` before starting the backend to route graph tool calls through the client. The parent process binds workspace and scopes; model arguments cannot choose tenant identity. Arguments are Pydantic validated, outputs are bounded/checked, and communication has a timeout. Read tools need `data:read`; mutations need `action:write` plus an exact persisted approval. Independent round trips and MCP-through-graph workflows are tested.

Local actions store reports, exports, tasks, drafts, and inbox records in the database. CSV content is returned in its effect receipt. Email tools **never send external messages**. `/inbox` exposes tenant-owned action artifacts. The inventory update is a real local SQL mutation with a verified resulting quantity.

## Retrieval and ingestion

Text/PDF ingestion validates format, size, page count, extractable text, and UTF-8. Paragraph-aware or fixed overlapping chunks are embedded and transactionally upserted by source/content hash. Repeating unchanged ingestion does not duplicate chunks. Updates replace a source's chunks; deletion and reindex are explicit APIs. Original V1 documents can be imported with `python -m agentos.migrate --legacy-documents` without deleting legacy records.

SQLite uses BM25 and dense cosine rankings. PostgreSQL uses full-text lexical candidates plus pgvector dense candidates, then candidate-only fetching and reciprocal rank fusion. Optional cross-encoder scoring reranks the candidate set. Metadata filters, workspace isolation, model namespaces, and dimension-specific HNSW expression indexes prevent accidental mixing of vector spaces. V1's fixed 384-dimensional index remains only for legacy records; V2 chunk vectors support the configured dimensions.

### Measured retrieval quality

Fourteen new questions cover fourteen new policy documents alongside thirty-two existing distractors. Several questions require two sources. Every method indexed the same 46 documents and answered the same 14 queries. Scores use document-level relevance. Recall@1 gives half credit when one of two relevant documents is returned first.

| Method | Recall@1 | Recall@5 | Precision@5 | MRR@5 | nDCG@5 | Mean query (ms) |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 0.607 | 0.679 | 0.171 | 0.714 | 0.678 | 4.8 |
| hashing_dense | 0.286 | 0.714 | 0.171 | 0.520 | 0.545 | 4.5 |
| neural_dense | 0.786 | 1.000 | 0.257 | 0.964 | 0.974 | 27.9 |
| neural_hybrid | 0.643 | 0.964 | 0.243 | 0.850 | 0.850 | 28.5 |
| neural_weighted_rrf | 0.643 | 1.000 | 0.257 | 0.893 | 0.921 | 18.9 |
| neural_hybrid_rerank | 0.786 | 0.929 | 0.243 | 0.929 | 0.920 | 40.3 |

On the original 22 questions, dense retrieval also led on nDCG@5 (0.983). Equal-weight reciprocal rank fusion gives a passage a second contribution for a lexical match, even when the match is weak. On the chilled-delivery question, dense retrieval ranked the release and receiving policies first and second. Equal-weight fusion kept the release policy but dropped receiving from the first five. Reducing the lexical contribution to one quarter recovered held-out Recall@5; rank order still lagged dense search. The ablation held chunking, corpus and labels fixed. It cannot isolate annotation quality or predict performance on a different organization's documents. The neural Compose profile therefore selects dense retrieval. [Per-query results and indexing times](evals/retrieval-heldout-results.json)

## Memory and context

Short-term conversation turns are bounded in graph state. Checkpoints preserve task state. Long-term semantic memory stores normalized embeddings, workspace identity, source/run provenance, TTL, and exact-content deduplication. Context compaction normalizes whitespace and bounds stored summaries; it is lossy and is not claimed to be an advanced semantic compressor.

The separate two-turn recall benchmark has eight authored conversations. With hashing and with the actual neural encoder, offline extraction accuracy was 0/8 without memory and 8/8 with memory (16 trials per embedding configuration). This demonstrates retained information becoming available to the follow-up; the answer extractor is deterministic, so this is **not an LLM memory-accuracy claim**. The runner also supports a live provider when credentials are supplied.

## Evaluation and verification

```bash
cd backend
pytest -q
python -m agentos.evaluate --n 24 --output /tmp/agent-regression.json
python -m agentos.evaluate --dataset ../evals/datasets/agents-heldout.json --output /tmp/agent-heldout.json
python -m agentos.claim_eval --output /tmp/claims.json
python -m agentos.retrieval_eval --neural --dataset ../evals/datasets/retrieval-heldout.json --output /tmp/retrieval.json
python -m agentos.memory_eval --backend neural --output /tmp/memory.json
python -m agentos.evaluate --n 1200 --generate ../evals/generated-scenarios.jsonl
```

The curated agent set covers retrieval, multi-document work, contradictions, missing information, analytics, tools, parameter extraction, approval denial, transient failure, injection, and unsupported/cross-workspace requests. The offline baseline intentionally fails several intelligence-dependent expectations. The 1,200 generated parameter/context/action combinations are generated cases, not 1,200 executed independent reasoning evaluations.

Semantic groundedness, claim entailment, and answer completeness need adjudicated labels; unmeasured metrics remain null. No three-model comparison is bundled. [EVALUATION.md](docs/EVALUATION.md) provides the commands for three credentialed configurations and how to preserve raw results.

Run optional infrastructure tests:

```bash
pip install -e 'backend[test,postgres,ml]'
cd backend
TEST_POSTGRES_URL=postgresql+psycopg://user:password@localhost/agentos RUN_NEURAL_TESTS=1 pytest -q
```

From `frontend`: `npm test` runs mocked-API DOM interaction tests; `npm run build` validates TypeScript and production compilation. For a real browser, install `npx playwright install chromium-headless-shell`, start backend/frontend, populate experiments, then run `npm run test:browser`. [DEMO.md](docs/DEMO.md) gives exact steps. Browser test screenshots are from actual local deterministic runs.

## Persistence, budgets, and failure recovery

Jobs are written before dispatch. A single supported scheduler resumes queued/interrupted work after restart; a process/database lock rejects a second scheduler. SQLite or PostgreSQL graph checkpoints preserve interruptions. Results merge by logical step ID rather than appending duplicates. Exact action proposals survive interrupt replay; canonical argument fingerprints prevent duplicate effects during replanning. Transactions bind approval consumption, mutation, receipt, and audit writes.

Retries, request timeouts, overall run timeout, plan/depth bounds, one correction, cancellation, and shared token reservations limit runaway execution. Dollar limits require an explicit per-model price table and fail closed without one. Unknown provider usage retains its reservation conservatively. Cancellation cannot undo an already committed effect. This is a durable single-worker design, not a distributed queue.

Model/agent/tool traces persist locally with IDs, schemas, prompt versions, latency, usage, errors, retrieval candidates, and reranking scores. The console exposes run traces. Optional OpenTelemetry exports metadata only. Install `backend[telemetry]` and set `OTEL_ENABLED=true`; configure an OTLP collector if desired. External collector connectivity was not exercised.

## Authentication and deployment

Local demo identity is a server-side role-token registry. Shared mode requires signed RS256 OIDC tokens with issuer, audience, expiry, subject, workspace, and role claims; scopes are intersected with role rights. Demo authentication is rejected when `DEPLOYMENT` is not `local`. A configured public key or HTTPS JWKS endpoint verifies tokens. Signed-token tests cover invalid issuer, audience, expiry, and roles. This integrates token verification, not an identity-provider signup/login interface.

```bash
docker compose up --build
# Neural local profile:
docker compose -f compose.yaml -f compose.neural.yaml up --build
# Shared authentication profile, after exporting OIDC settings:
docker compose -f compose.yaml -f compose.oidc.yaml up --build
```

Compose persists PostgreSQL application state and PostgreSQL graph checkpoints. Ports bind to localhost. Docker was unavailable during this build, so image/Compose execution is not claimed. Add your own TLS ingress and trusted identity provider before shared hosting. API rate limiting, scoped tools, safe templates, upload validation, and audit records are implemented; [security boundaries](docs/SECURITY.md) describe residual risks.

## Reproduce the integrated demonstration

Start the API with a fresh private synthetic workspace. Set `USE_MCP=true` before starting it to exercise subprocess tools. From `backend/`, run the checker below. It seeds local records, indexes two policy documents, runs three tasks, checks period totals and tests one approval. The automated approval applies only to the local synthetic report. Use the console for an interactive approval.

```bash
python -m agentos.workflow_check --output /tmp/demo-workflows.json
# On an API already configured with a secure provider key:
python -m agentos.workflow_check --mode openai --model "$OPENAI_MODEL" --output /tmp/openai-workflows.json
# For Anthropic, use --mode anthropic --model "$ANTHROPIC_MODEL".
```

On a Docker host, run `scripts/verify-compose.sh` from the repository root. Set `NEURAL=1` for the neural overlay. The script builds, checks both services, validates the workflows, restarts PostgreSQL and the backend, and checks stored run results. It leaves the review volumes intact.

## Documentation and limitations

- [Current acceptance, measurements and reproduction commands](docs/HARDENING.md)
- [Previous acceptance baseline](docs/ACCEPTANCE_REPAIR.md)
- [Previous V3 engineering review](docs/ENGINEERING_REPORT.md)
- [Architecture and state transitions](docs/ARCHITECTURE.md)
- [Evaluation methodology](docs/EVALUATION.md)
- [Security and threat boundaries](docs/SECURITY.md)
- [Demo walkthrough and browser instructions](docs/DEMO.md)
- [Baseline audit](docs/AUDIT_V2.md)

Remaining work includes hosted-provider evaluation, a larger independently judged corpus, production identity-provider integration, independent sandboxing for untrusted uploads, comprehensive data-retention deletion, horizontal workers, real external connectors, and Docker verification. No external customer messages or GitHub pushes were performed.


## Reproduce local model evaluation

Use a loopback llama.cpp server binary and a separately downloaded instruction model. The acceptance repair used build b12498 with Qwen2.5-1.5B-Instruct Q4_K_M. Historical attempts also tested Qwen3-4B-Instruct-2507. Model weights are excluded from the source archive. Activate the backend virtual environment before running the script. First cache the encoder as described above.

```bash
MODEL_FILE=/absolute/path/to/model.gguf LLAMA_SERVER=/absolute/path/to/llama-server \
RESULT_FILE=/tmp/agentos-local-evaluation.json scripts/evaluate-local-model.sh
```

The runner uses a temporary workspace database, calls the real model for structured decisions, routes tools through MCP and approves only expected synthetic mutations. The capability planner maps each model-selected tool to its owning agent and compiles declared evidence dependencies into validated graph edges before dispatch. The ordinary hosted-provider configuration retains the full plan schema and named tool calls.


## Reproduce the three release workflows

Activate the environment described above. Provide the local llama.cpp server executable, a compatible instruction model and the cached encoder. The runner binds the model server to loopback, uses an isolated SQLite database and invokes MCP subprocesses. The research case ingests three UTF-8 sources. The analytics case compares February and March. The invoice case uses April 1 as the cutoff and reopens the checkpoint before a synthetic operator approves a matching report. The regression suite separately tests role enforcement and the HTTP approval endpoint. Source artifacts contain synthetic data.

```bash
MODEL_FILE=/absolute/path/to/qwen.gguf LLAMA_SERVER=/absolute/path/to/llama-server \
HF_HUB_OFFLINE=1 LOCAL_CONTEXT=4096 LOCAL_MODEL_ALIAS=qwen15-local RESULT_DIR=/tmp/agentos-release-run \
scripts/check-local-workflows.sh
(cd backend && python -m agentos.release_score /tmp/agentos-release-run)
```

Pass `A`, `B`, or `C` as script arguments to rerun individual workflows in a fresh directory. Supply result directories in chronological order to the scorer. A machine pass still requires reading the resulting explanation and checking its claims against the sources. Launching the console without credentials starts the deterministic demonstration.
