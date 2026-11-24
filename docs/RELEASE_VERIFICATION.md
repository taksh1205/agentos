# Release verification

**Historical review.** See the [latest acceptance and verification report](ACCEPTANCE_REPAIR.md) for the repaired release.

This review uses the existing V3 repository and its synthetic business records. Evidence from this review lives in `docs/verification/final/`. Prior review artifacts remain under `docs/verification/v3-review/`. Each live workflow has an independently checked result in [the acceptance matrix](ACCEPTANCE.md). The model and retrieval measurements are in [the AI evaluation report](FINAL_AI_EVALUATION.md).

## Engineering changes

- The invoice MCP tool accepts a calendar cutoff. Its result preserves all invoices and the unpaid total and also returns the strictly overdue unpaid records, their total and the effective date. The reporting cutoff propagates through the data agent, MCP argument validation and the server. An invoice due on the cutoff becomes overdue the following day.
- The compact planner asks the model to choose capabilities and declare which tasks need prior evidence. The host compiles those choices into an acyclic graph. Read-only sessions constrain the model's decoded capability choices and still enforce authorization on the server. The general plan adapter retains its explicit dependency DAG.
- The compact action agent decodes the schema of the chosen business tool. The model supplies the actual report arguments. The server still binds workspace, exact payload and approval digest, and verifies the stored receipt.
- The local model has separate evidence formats for cited synthesis and analytics interpretation. The former keeps source references with exact quotes. The latter binds directions to a metric and two reporting periods. Both enter the existing verifier. Rejected semantic output goes to bounded correction.
- Full-period and filtered analytics now use the same aggregation logic. Zero-revenue months return an undefined monthly margin, while the period margin uses total revenue and total profit. Verification compares the full tool response with a fresh calculation, including rows and changes.
- Tests exercise deadline boundaries, scopes, excluded mutation capabilities, dependency barriers, source misquotation, calendar years, fabricated invoice amounts, zero-revenue margin and reversed trends. The evaluation workflow captures live model attempts, timing, actual tools, checkpoint state, operator decisions and persisted effects.

## Reproduce the engineering checks

Activate the backend environment from the repository root. For the complete database checks, provide a disposable PostgreSQL database with the vector extension available. The recorded run started a fresh PostgreSQL 16.2 cluster with `initdb -U agent -A trust --no-locale -E UTF8` and bound it to loopback only. The trust configuration applies only to this disposable test cluster.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-lock.txt
pip install --no-deps -e backend
pip check
# Install the optional CPU ML dependencies and cache encoder/reranker as described in README.
export TEST_POSTGRES_URL='postgresql+psycopg://agent@127.0.0.1:42735/postgres'
cd backend
DATABASE_URL="$TEST_POSTGRES_URL" python -m agentos.migrate --legacy-documents
python -m compileall -q agentos tests
ruff check agentos tests
ruff format --check agentos tests
RUN_NEURAL_TESTS=1 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2 python -m pytest -q --junitxml=/tmp/agentos-junit.xml
```

```bash
cd frontend
npm ci --no-audit --no-fund
npm test
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run build
npm run typecheck
npx playwright install chromium-headless-shell
```

For the browser check, start Uvicorn on 127.0.0.1:8000 with a fresh SQLite database, `FRONTEND_ORIGIN=http://127.0.0.1:3000`, and start the built Next.js app on 127.0.0.1:3000. Wait for both services. Run `BASE_URL=http://127.0.0.1:3000 npm run test:browser` from the frontend directory. The first browser attempt timed out waiting for the result heading; its API log recorded no requests. Specifying the same loopback address at build time and runtime and waiting for both endpoints produced a passing run. Both sets of logs are retained.

## Infrastructure and public review

Backend install used a fresh virtual environment and the locked dependencies. The dependency check and application import succeeded. The browser-tested backend used SQLite. Dedicated integration tests used real PostgreSQL, pgvector and PostgreSQL graph checkpointing. The API, browser and model acceptance runs are separate evidence streams.

Docker CLI and daemon socket were absent. The repository includes Compose definitions and a smoke script for a Docker host. A remote GitHub Actions run and a shared OIDC identity provider were unavailable in this review. OIDC tests use test credentials. No remote publication was requested or performed. Public-facing deployment and open-ended model accuracy require separate review.

## Results from this review

| Check | Executed result | Raw evidence under `docs/verification/final/` |
|---|---|---|
| Backend suite with PostgreSQL and neural models enabled | 114 passed, 0 failed, 0 skipped | `verified/backend.log`, `verified/junit.xml` |
| Portable backend run | 107 passed, 0 failed, 5 optional integration tests skipped | `portable-suite.log` |
| Disposable PostgreSQL and schema migration | PostgreSQL 16.2 started and migration command completed | `verified/init.log`, `verified/postgres.log`, `verified/migration.log` |
| Three deterministic HTTP workflows through MCP | All three returned the expected evidence or effect | `verified/workflows.log`, `verified/workflows.json` |
| API process restart over PostgreSQL | Three completed reports survived; one matching approved report receipt | `verified/restart.log` |
| Frontend | Two interaction tests passed. Next.js production build and TypeScript check succeeded | `frontend-tests.log`, `frontend-local-build.log`, `typecheck.log` |
| Chromium | One browser workflow passed on retry, including the approval interaction and experiment dashboard | `browser.log`, `browser-retry.log`, `browser-api-retry.log` |
| Clean dependencies | Fresh backend environment passed `pip check` and imported the FastAPI application. Fresh `npm ci` succeeded | `install.log`, `npm-ci.log` |
| Static checks | Python compilation, lint and formatting completed | `static.log` |
| Hosted APIs and Docker | No hosted API keys, Docker CLI or daemon socket detected | `environment.json` |

The portable run is a subset of the 114-test suite. The earlier 105- and 108-test outputs are development snapshots. Do not add these counts together.

To recreate the PostgreSQL, MCP, FastAPI and restart checks together, run `RUN_NEURAL_TESTS=1 PG_BIN=/path/to/postgresql/bin OUTPUT_DIR=/tmp/agentos-review-pg scripts/review-postgres.sh` from the repository root. Supply a new output directory and available loopback ports. Graph restart tests close and reopen a PostgreSQL checkpointer. The HTTP exercise restarts the API process. A container or machine restart was outside this run.

### Core-workflow fixtures

| Workflow | Independent expectation |
|---|---|
| A. East depot policies | Inventory requires at least twenty reserve pallets. Capacity permits at most twelve. The same site and stock are covered. Both texts must support the answer. A supported recommendation can identify the incompatible limits, the coverage and clearance risks, and the need for owners to resolve them. Neither source grants a waiver. |
| B. February to March, 2026 | Revenue 120,000 → 150,000 (+30,000, +25.00%). Expenses 78,000 → 90,000 (+12,000, +15.38%). Profit 42,000 → 60,000 (+18,000, +42.86%). These two months do not establish an external cause. |
| C. Overdue at the start of April 1, 2026 | INV-001 for 2,500 is overdue. INV-002 was paid. INV-003 is due April 15. Only a matching local report may be saved. Compare the exact approved arguments with the persisted receipt and replay the same approved operation. |

The live harness enters the LangGraph backend and exercises MCP, persistence and the real inference server. It drives approvals as a synthetic operator. The separate browser and HTTP tests cover client interaction and authenticated approval handling. Authentication is outside the direct graph harness.

The constrained research response now restricts quotation references to the passage IDs actually retrieved in that execution. Invoice summaries use a record-specific response schema. The verifier also checks explicit invoice-to-dollar bindings and explicit overdue assertions against the selected records. Free-form implications still require semantic review.

The clean database suite ran with the final source in `verified/`. The 107-pass portable snapshot preceded the last invoice-binding regression. The regression is included in the 114-pass full suite.
