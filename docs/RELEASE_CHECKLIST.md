# Release checklist

## Recommendation

**Ready to publish as a public portfolio repository.** Every check that could run in the
release environment was executed and is recorded in [FINAL_RELEASE_AUDIT.md](FINAL_RELEASE_AUDIT.md),
including one regression found late, patched and re-verified. Hosted GitHub Actions run automatically on the first push.

Claims to make: a 4-bit 4B local model matching GPT-4.1-mini (83.3% each) on a frozen held-out
set; 0 unapproved writes in 333 live runs; measured retrieval quality; approval-gated,
idempotent writes; Docker and CI reproducibility.

Claims **not** to make: production readiness, general autonomous reasoning, accuracy on
arbitrary business questions, or Claude results. OpenAI results are measured; the Anthropic
adapter is transport-tested only.

## Publish

1. Create an empty GitHub repository named `agentos` (no README, license or .gitignore).
2. From the repository root:

   ```bash
   git remote add origin https://github.com/<you>/agentos.git
   git push -u origin main --tags
   ```

3. Open **Actions** and confirm all five CI jobs pass: `security`, `backend`, `frontend`,
   `neural`, `compose`. If one fails, the job log names the step. Fix it and push again.
4. Replace the commented CI badge line at the top of `README.md` with your URL and commit.
5. Repository settings → About: add the description *"Five-agent LLM system with verified tool
   use, human-approved actions and a frozen live evaluation"*, and the topics `llm`, `agents`,
   `langgraph`, `rag`, `mcp`, `fastapi`, `pgvector`, `evaluation`.
6. Pin the repository on your GitHub profile.

To add another model, run the command in [EVALUATION.md](EVALUATION.md#reproduce), save the
JSON under `evals/results/live/`, add its name to `SECTIONS` in `agentos/live_report.py` and run
`python -m agentos.live_report --write`. The console's Experiments tab picks it up automatically.

## Reproduce this release

```bash
# Backend: full suite with PostgreSQL + pgvector and neural models
docker run -d --name agentos-pg -e POSTGRES_USER=agentos -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=agentos -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-lock.txt && pip install --no-deps -e backend
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
pip install -e 'backend[ml]' -c backend/neural-constraints.txt
cd backend && TEST_POSTGRES_URL=postgresql+psycopg://agentos:test@127.0.0.1:55432/agentos \
  RUN_NEURAL_TESTS=1 pytest -q && cd ..

# Frontend
(cd frontend && npm ci && npx prettier --check app tests && npm test && npm run typecheck && npm run build)

# Docker Compose, default and neural (restart-survival check included)
bash scripts/verify-compose.sh
NEURAL=1 bash scripts/verify-compose.sh

# Frozen live evaluation on a local model (see EVALUATION.md for the GGUF files)
MODEL_FILE=/abs/Qwen3-4B-Instruct-2507-Q4_K_M.gguf LLAMA_SERVER=/abs/llama-server \
  MODEL_ALIAS=qwen3-4b-instruct-2507 REPEATS=3 OUTPUT=/abs/qwen3-4b.json scripts/run-live-eval.sh

# Security scans
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.24.3 git /repo --config /repo/.gitleaks.toml --redact
pip install pip-audit && pip-audit -r backend/requirements-lock.txt
(cd frontend && npm audit)
```

Behind a TLS-inspecting proxy, give the image builds your CA as a BuildKit secret (both
Dockerfiles accept an optional `extra_ca` secret) and pass `COMPOSE_OVERRIDES=` a file that
mounts it at runtime. The release environment needed this; the override is not part of the repo.

## Known gaps

| Gap | Why it remains | Next step |
|---|---|---|
| Hosted GitHub Actions not yet run | Needs the repository to exist on GitHub | First push (step 3 above) |
| No Anthropic live run | No Anthropic key in the release environment | `--mode anthropic` with the same harness |
| Small author-labeled live set | Labels are written by hand and every case needs its own fixtures | Grow the set with a versioned `live-frozen-v2.json` |
| One scheduler per database | Correct restart semantics without distributed leases | Lease and heartbeat job claims for horizontal workers |
| MCP starts a process per tool call | Simplest way to bind workspace identity per call | Pool long-lived sessions keyed by workspace and scopes |
