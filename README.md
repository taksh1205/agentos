<div align="center">

# AgentOS

**A five-agent LLM system that plans, retrieves, computes and acts on business data, where every
number is recomputed, every quote is verified and every write waits for a human.**

![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C)
![MCP](https://img.shields.io/badge/MCP-stdio-6E56CF)
![FastAPI](https://img.shields.io/badge/FastAPI-0.16x-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs)
![pgvector](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
<!-- After publishing, add: ![CI](https://github.com/<you>/agentos/actions/workflows/ci.yml/badge.svg) -->

![AgentOS console: a live Qwen3-4B run that found two conflicting policies, with every quote machine-verified](docs/screenshots/research.png)

</div>

## Why

LLM agents rarely fail in production because they cannot write fluent text. They fail because
they **invent numbers**, **cite sources that don't say what they claim**, and **take actions nobody
approved**. AgentOS is built around one idea: let the model do what models are good at (reading
intent, choosing tools, selecting evidence, explaining) and make deterministic code
responsible for everything that must be exactly right (arithmetic, calendars, permissions,
provenance and transactions).

| Boundary | The model… | …but the host guarantees |
|---|---|---|
| **Plan** | proposes steps and tools | typed DAG, capability ownership, no unrequested writes |
| **Facts** | interprets results | numbers recomputed from source rows; quotes appear verbatim in the cited passage |
| **Actions** | prepares a write | nothing executes until an authorized person approves the exact arguments (SHA-256 digest); replay is idempotent |

## Results

All numbers below come from runs bundled in this repository ([full report](docs/AI_EVALUATION_FINAL.md)).

**Live end-to-end evaluation.** Frozen set of 15 tasks: 3 original workflows + 12 unseen tasks,
committed before any model saw them. Real local inference via llama.cpp on CPU, tools via MCP,
fresh workspace per run, programmatic grading.

| Model (4-bit, CPU) | Planner profile | Runs | pass@1 | Original | Unseen | pass^3 | p50 latency | Unapproved writes |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | constrained | {{Q4_RUNS}} | **{{Q4_P1}}** | {{Q4_ORIG}} | {{Q4_UNSEEN}} | {{Q4_PK}} | {{Q4_P50}} | **0** |
| Qwen2.5-1.5B-Instruct | constrained | {{Q15_RUNS}} | **{{Q15_P1}}** | {{Q15_ORIG}} | {{Q15_UNSEEN}} | {{Q15_PK}} | {{Q15_P50}} | **0** |
| Qwen3-4B-Instruct-2507 | general (ablation) | {{G_RUNS}} | {{G_P1}} | {{G_ORIG}} | {{G_UNSEEN}} | n/a | {{G_P50}} | **0** |

**Retrieval** (46 documents, 14 held-out queries, several needing two sources):

| Method | Recall@5 | nDCG@5 | MRR@5 |
|---|---:|---:|---:|
| BM25 lexical | 0.679 | 0.678 | 0.714 |
| MiniLM dense | **1.000** | **0.974** | **0.964** |
| MiniLM hybrid (RRF) | 0.964 | 0.850 | 0.850 |
| Hybrid + TinyBERT rerank | 0.929 | 0.920 | 0.929 |

**Engineering checks** (this release): {{BACKEND_TESTS}} backend tests (PostgreSQL + pgvector +
neural models), {{FRONTEND_TESTS}} frontend tests, a Chromium end-to-end approval journey,
Docker Compose verified for the default and neural profiles (including a restart-survival
check), gitleaks / pip-audit / npm audit clean. Matrix with evidence:
[FINAL_RELEASE_AUDIT.md](docs/FINAL_RELEASE_AUDIT.md).

## How it works

```mermaid
flowchart LR
    U[User goal] --> P[Planner]
    P -->|typed DAG| S{Scheduler}
    S -->|parallel| R[Research<br/>neural RAG]
    S -->|parallel| D[Data<br/>SQL templates]
    R & D --> V[Verifier]
    V -->|evidence OK| A[Action]
    A -->|interrupt| H((Human<br/>approval))
    H -->|exact digest| A
    A --> V
    V -->|1 bounded correction| P
    V --> Out[Report with<br/>verified claims]
    R & D & A -.->|MCP stdio| T[(11 allowlisted tools<br/>Postgres · pgvector)]
```

* **Planner** turns the goal into a typed dependency graph and assigns each step an agent and a
  tool. The host rejects cycles, unknown tools, mutations outside the action agent, and **writes
  the user never asked for**.
* **Research** and **Data** run in parallel (LangGraph `Send`). Research cites retrieved passage
  IDs; citations are constrained at decode time to passages retrieved in *this* run. Data calls
  SQL-template tools and **recomputes every result from source rows** before a model sees it.
* **Action** persists one exact proposal and interrupts the graph. On approval the write runs in
  one transaction that re-checks workspace, scope, digest and cancellation, then stores a receipt.
* **Verifier** runs before and after the action: completion, provenance, arithmetic, narrative
  checks (e.g. a report claiming "no overdue invoices" when one is overdue), receipts, then an
  optional model review. It requests at most one correction.

### Two planner profiles: right-sizing the model's job

| | `general` | `constrained` |
|---|---|---|
| For | Hosted frontier models | Small local models (1.5B–4B) |
| Model writes | Full plan, cited claims, interpretations, action arguments | Enumerated decisions: capability, supporting passage IDs, trend direction, invoice IDs |
| Host does | Validation and verification | Validation, verification, DAG compilation and templated rendering |

The constrained profile uses JSON-schema constrained decoding so that a 4-bit 1.5B model on a
laptop CPU completes real multi-step workflows. The general-profile ablation above shows why
that matters for small models. Details: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

**Docker (recommended).** Starts PostgreSQL + pgvector, the API and the console.

```bash
docker compose up --build            # http://localhost:3000, token: local-demo-token
# Neural retrieval (MiniLM embeddings, TinyBERT reranker, CPU PyTorch):
docker compose -f compose.yaml -f compose.neural.yaml up --build
```

In the console: **Knowledge → Load synthetic demo dataset**, then try the
[demo walkthrough](docs/DEMO.md). The default `demo` provider uses deterministic rules and needs no
API key.

**Local development**

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-lock.txt && pip install --no-deps -e backend
(cd backend && uvicorn agentos.api:app --port 8000)
(cd frontend && npm ci && npm run dev)
```

**Live models.** Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (general profile), or point
`OPENAI_BASE_URL` at a local `llama-server` with `PLANNER_PROFILE=constrained`. See
[EVALUATION.md → Reproduce](docs/EVALUATION.md#reproduce).

**Tests**

```bash
cd backend && pytest -q                       # add TEST_POSTGRES_URL=... RUN_NEURAL_TESTS=1 for the full suite
cd frontend && npm test && npm run build
bash scripts/verify-compose.sh                # Docker end-to-end, incl. restart survival
```

## What's interesting to read

| If you want to see… | Look at |
|---|---|
| The state machine, scheduling and approval interrupt | [`backend/agentos/graph.py`](backend/agentos/graph.py) |
| Deterministic claim and narrative verification | [`backend/agentos/verification.py`](backend/agentos/verification.py) |
| Constrained decoding for small models | [`backend/agentos/grounded.py`](backend/agentos/grounded.py) |
| Digest-bound, transactional, idempotent writes | [`backend/agentos/tools.py`](backend/agentos/tools.py) |
| Host-bound MCP server and client | [`mcp_server.py`](backend/agentos/mcp_server.py), [`mcp_client.py`](backend/agentos/mcp_client.py) |
| Namespaced hybrid retrieval on pgvector | [`backend/agentos/rag.py`](backend/agentos/rag.py) |
| Provider adapter (OpenAI, Anthropic, llama.cpp), budgets, retries | [`backend/agentos/models.py`](backend/agentos/models.py), [`budget.py`](backend/agentos/budget.py) |
| The frozen evaluation harness and grader | [`backend/agentos/live_eval.py`](backend/agentos/live_eval.py), [`evals/datasets/live-frozen-v1.json`](evals/datasets/live-frozen-v1.json) |

## Repository layout

```
backend/agentos/     FastAPI app, LangGraph agents, MCP server/client, RAG, verifier, evaluators
backend/tests/       pytest suite (unit, integration, PostgreSQL, neural, provider transport)
frontend/            Next.js console (report rendering, approvals, experiments)
evals/datasets/      Labeled datasets, including the frozen live set
evals/results/       Measured results (live, retrieval, offline, memory)
docs/                Architecture, evaluation, security, demo, release audit
docs/evidence/       Raw logs and JSON behind this release's claims
docs/archive/        Earlier development rounds, including failed attempts
migrations/ scripts/ compose*.yaml   Database, verification and deployment
```

## Limitations

* The live evaluation is **small and author-labeled** (15 tasks × 3 repeats). It shows that the
  system completes these task shapes reliably on small local models. It is not a general accuracy
  estimate.
* Hosted OpenAI and Anthropic adapters are covered by transport-level tests; this release's
  measured live runs use local Qwen models.
* All data is synthetic. Business tools are local by design: email tools create drafts and never send.
* Single scheduler process per database; horizontal workers would need leases and heartbeats.
* PDF parsing is time-boxed and resource-limited but not sandboxed in a separate service.

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Evaluation method](docs/EVALUATION.md) ·
[Results](docs/AI_EVALUATION_FINAL.md) · [Release audit](docs/FINAL_RELEASE_AUDIT.md) ·
[Security](docs/SECURITY.md) · [Demo](docs/DEMO.md) · [Release checklist](docs/RELEASE_CHECKLIST.md) ·
[Development history](docs/archive/README.md)

## License

MIT © Taksh Pathak
