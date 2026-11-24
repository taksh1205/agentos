# Demonstrations and reproducible browser check

Start backend/frontend using README instructions and load the synthetic dataset in Knowledge. Keep Auto selected. Use demo for no-credential regression behavior or a configured real provider for model-driven planning. Select neural embedding/reranker configuration on the backend independently of the reasoning provider.

## 1. Business analysis

“Analyze our revenue and operating costs, explain the biggest changes, retrieve relevant policy documents, and prepare an evidence-based report.”

Live planning selects analytics/research and a dependent report action. The offline baseline explicitly recognizes these capabilities through rules. Actual synthetic totals are revenue 370000, operating costs 238000, profit 132000; January-to-March revenue growth is 50%. Analytics computes from SQL records, rather than asking a model to invent totals. Inspect metric intent, computed data, citations, and approval arguments before approving report storage.

## 2. Multi-document research

Upload two text files:

- `January travel policy`: “Domestic hotel reimbursement was 150 dollars per night before July.”
- `July travel policy`: “Domestic hotel reimbursement is 180 dollars per night from July, superseding January.”

Ask: “Compare the January and July lodging policies and explain which allowance applies to August, citing both sources.”

Neural graph integration tests exercise the retrieval path with both policies. A live provider synthesizes the answer; offline mode returns excerpts and does not claim to reconcile evidence intelligently. For contradictory bulletins with no supersession, a live finding should explicitly list the conflict and avoid guessing which one governs.

## 3. Approved operational automation

“Analyze revenue and export sales to CSV.”

Inspect the pending proposal's exact tool and arguments, approve, then inspect the stored effect receipt. `/inbox` returns the CSV content. Try declining a second operation: no effect is written. The suite also tests report, follow-up, email draft, inventory update, and local notification tools. Nothing sends external messages.

## Automated browser test

With a fresh local database, run one evaluation so the experiment table has actual rows:

```bash
cd backend
python -m agentos.evaluate --n 2 --output ../evals/browser-setup-results.json
uvicorn agentos.api:app --port 8000
```

In separate terminals, start `npm run dev` from frontend, then:

```bash
cd frontend
npx playwright install chromium-headless-shell
npm run test:browser
```

The test drives the real Next.js UI and FastAPI service: seed data, submit/inspect a completed workflow, submit an action, inspect/approve it, and view experiments. It also checks browser exceptions and writes screenshots under docs/screenshots. `BASE_URL` can override the frontend URL; `NEXT_PUBLIC_API_URL` must be set at frontend build time if changing the API URL. Set FRONTEND_ORIGIN on the backend to the actual frontend origin.

The build environment used permitted local TCP ports and Chromium Headless Shell. Initial system Chromium startup was blocked by Unix-socket restrictions; the headless-shell workflow succeeded. Screenshots contain synthetic local executions only. No live-provider screenshot is implied.
