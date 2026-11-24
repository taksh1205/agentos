# Release acceptance

**Historical review.** See the [latest acceptance and verification report](ACCEPTANCE_REPAIR.md) for the repaired release.

Each live workflow is judged against the specified user outcome. The graph's own status is one input. A valid returned JSON object, a successful retrieval, or an approved write alone is insufficient.

## Supporting requirements

| Requirement | Verdict | Evidence under `docs/verification/final/` | Scope |
|---|---|---|---|
| Real inference and structured orchestration | PASS | Local model traces in workflow JSON, llama.cpp server logs | Model selected tools and the graph invoked MCP. Workflow quality is graded separately. |
| Neural retrieval and reranking | PASS | `retrieval.json`, backend JUnit neural tests | Six configurations, 46 documents, 14 labeled queries |
| Grounding verifier and offline evaluation | PASS | `claims.json`, `heldout.json`, `transfer.json` | Supplied labels and deterministic checks. General entailment remains open. |
| Workspace isolation, role enforcement, injection controls, approval gates | PASS | Backend JUnit security, system, release and provider tests | Tested scenarios only, including untrusted content and unauthorized operations |
| PostgreSQL persistence, cancellation, retries, idempotency | PASS | Backend JUnit, workflow and restart records | Disposable database, real pgvector, reopened graph/checkpoint and API |
| Clean backend/frontend install, migrations and local startup | PASS | `install.log`, `npm-ci.log`, migration log, `browser-api-retry.log` | Local environment |
| Frontend build, interactions and browser approval | PASS | `frontend-tests.log`, `frontend-local-build.log`, `browser-retry.log` | Chromium with local backend |
| Hosted OpenAI or Anthropic inference | BLOCKED | `environment.json` | No credentials configured. Local compatible-server requests are separate. |
| Docker Compose execution and hosted CI | BLOCKED | `environment.json`, CI workflow and Compose scripts | Docker unavailable. Remote CI was not triggered. |
| Documentation and reproducibility | PASS | Root README, architecture diagrams, commands, manifest and raw outputs | Model weights must be obtained separately. |

The independent reviewer should compare each generated sentence with its quoted policy or ledger rows, inspect correction paths, and replay an approved payload with both identical and changed arguments. The source and evidence can be reviewed privately. Publication awaits the owner's decision.

## Core workflows with actual local language-model inference

| Workflow | Verdict | What the recorded run establishes | Evidence under `docs/verification/final/` |
|---|---|---|---|
| A. Multi-document research | FAIL | Neural search returned the policies. Intermediate synthesis recognized the twenty-pallet minimum and twelve-pallet maximum. The model also selected unrelated records, and the 300-second deadline expired before a verified final recommendation. The earlier run produced unknown citations. | `cited/A.json`, `cited/A.log`, `small/A.json` |
| C. Approved invoice report | FAIL | The model proposed a report claiming no invoices were overdue. INV-001 was overdue for 2,500. The synthetic reviewer declined the incorrect report and the database contained zero effects. No successful receipt or replay can be credited for this case. | `records/C.json`, `resumed/C.json` |
| B. February–March analytics | FAIL | The initial completed report used January as its baseline. After binding the requested months, MCP executed business metrics, but both model interpretations failed numeric verification. No accepted final report matched the independent ledger oracle. | `periods/B.json`, `ledger/B.json`, `scores.json` |

**Core live outcome: 0/3 passed.** This build is suitable for independent engineering review. The evidence does not support claiming reliable end-to-end completion of these three tasks on the tested local models.
