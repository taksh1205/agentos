# Final release audit

Every row was executed on the release commit (`git rev-parse HEAD`; tests record it in
[`evidence/tests/commit.txt`](evidence/tests/commit.txt)). **PASS** means executed and
succeeded. **BLOCKED** means it could not be executed in the release environment. Nothing is
marked PASS without a run.

## Matrix

| # | Requirement | Verdict | Evidence |
|---:|---|---|---|
| 1 | Backend suite with real PostgreSQL 16 + pgvector and neural models | **PASS**: 172 passed, 0 failed, 0 skipped | [`evidence/tests/backend.log`](evidence/tests/backend.log), [`backend-junit.xml`](evidence/tests/backend-junit.xml) |
| 2 | Python lint and format (ruff) | **PASS** | CI `backend` job; same commands in [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md) |
| 3 | Frontend: prettier, 5 interaction tests, TypeScript, production build | **PASS** | CI `frontend` job; [`evidence/tests/`](evidence/tests/) |
| 4 | Real-browser journey (Chromium): seed, run, approve, experiments, no page errors | **PASS** | [`evidence/tests/browser-demo.log`](evidence/tests/browser-demo.log), [`screenshots/demo/`](screenshots/demo/) |
| 5 | Live console screenshots from real OpenAI runs (research, approval, receipt, analytics, experiments) | **PASS** | [`screenshots/`](screenshots/), script `frontend/tests/screenshots.cjs` |
| 6 | Docker Compose, default profile: build, health, 3 HTTP workflows via MCP on PostgreSQL, restart survival | **PASS** | [`evidence/compose/default-run.log`](evidence/compose/default-run.log), [`default-workflows.json`](evidence/compose/default-workflows.json) |
| 7 | Docker Compose, neural profile (MiniLM, TinyBERT, CPU PyTorch) with the same checks | **PASS** | [`evidence/compose/neural-run.log`](evidence/compose/neural-run.log), [`neural-workflows.json`](evidence/compose/neural-workflows.json) |
| 8 | Original 3 live workflows still pass | **PARTIAL**: 9/9 for both Qwen models at `eval-freeze`; after the fixes, 3/3 for Qwen2.5-1.5B and 2/3 for Qwen3-4B (A: known regression below) | [`../evals/results/live/`](../evals/results/live/), [AI_EVALUATION_FINAL.md](AI_EVALUATION_FINAL.md#known-regression) |
| 9 | Frozen held-out live set (v2), multiple models | **PASS (measured)**: Qwen3-4B 83.3%, GPT-4.1-mini 83.3% / 77.8%, Qwen2.5-1.5B 58.3%, GPT-5-mini 33.3% | [AI_EVALUATION_FINAL.md](AI_EVALUATION_FINAL.md) |
| 10 | No unauthorized or duplicate state change | **PASS**: 0 unapproved effects in 306 live runs; every approved effect replayed idempotently | `unapproved_effects` and `replay_idempotent` in each result file |
| 11 | Hosted model inference | **PASS**: GPT-4.1-mini and GPT-5-mini on the OpenAI API | `v2-gpt-*.json`, `v1-postfix-gpt-*.json` |
| 12 | Anthropic live inference | **BLOCKED**: no Anthropic key in the release environment; adapter covered by transport tests | `tests/test_providers.py`, `tests/test_release_fixes.py` |
| 13 | Retrieval benchmark (6 configurations, 46 docs, 14 held-out queries) | **PASS** | [`../evals/results/retrieval/retrieval-heldout.json`](../evals/results/retrieval/retrieval-heldout.json) |
| 14 | Offline control plane (41 labeled cases), verifier challenge (12), memory ablation | **PASS**: 41/41, 12/12, 8/8 vs 0/8 | [`../evals/results/offline/`](../evals/results/offline/), [`../evals/results/memory/`](../evals/results/memory/) |
| 15 | Results docs match the data | **PASS**: `python -m agentos.live_report --check`, also a pytest | `backend/agentos/live_report.py` |
| 16 | Secrets in git history (gitleaks 8.24.3) | **PASS**: no leaks | [`evidence/security/gitleaks-history.json`](evidence/security/gitleaks-history.json) |
| 17 | Python advisories (pip-audit, 86 locked packages) | **PASS**: 0 known vulnerabilities | [`evidence/security/pip-audit.json`](evidence/security/pip-audit.json) |
| 18 | npm advisories | **PASS**: 0 vulnerabilities | [`evidence/security/npm-audit.json`](evidence/security/npm-audit.json) |
| 19 | Personal data or real records | **PASS**: synthetic data only; no emails, phone numbers or keys in the repo | Manual review; gitleaks |
| 20 | Unsafe defaults | **PASS**: demo auth refused when `DEPLOYMENT` is not local; model allowlist required when shared; ports bound to 127.0.0.1 | [SECURITY.md](SECURITY.md), `tests/test_release_fixes.py` |
| 21 | Hosted GitHub Actions | **BLOCKED (pending first push)**: the workflow is ready; it runs on the first push | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

## Defects found and fixed during this release

| Defect | Found by | Fix |
|---|---|---|
| Verifier missed blanket "no overdue invoices" claims | Archived failed run (records/C) | Sentence-scoped blanket-status check |
| Anthropic `tool_choice="required"` invalid | Code review | `{"type": "any"}` |
| GPT-5 family rejects `max_tokens`; quota errors retried | First hosted call | `max_completion_tokens`, `reasoning_effort`, non-retryable quota |
| Seven hidden env-var branches selected prompts | Code review | Explicit `PLANNER_PROFILE`, recorded in every trace |
| Unrequested writes in read-only analytics | Live dev run (B) | Write-intent gate |
| Period binding only for single-step plans | Live dev run (B) | Deterministic calendar binding |
| Backend image ignored the lockfile; neural profile would pull CUDA wheels | Docker review | Lockfile install, CPU PyTorch |
| Neural Compose: model cache volume not writable | First neural Compose run | Pre-created non-root cache |
| MCP child dropped proxy/CA variables, so neural search timed out behind TLS inspection | Neural Compose run | Pass network settings, never credentials (tested) |
| Clients could choose any model ID | Security review | `ALLOWED_MODELS` |
| PostCSS and Playwright advisories | npm audit | Pinned PostCSS 8.5.33, Playwright 1.65 |
| Six v1 failure classes | Frozen v1 | See [AI_EVALUATION_FINAL.md](AI_EVALUATION_FINAL.md#v1-failure-classes-and-the-general-fix-for-each) |
| General profile never exercised against a real model | First GPT-4.1-mini run | Strict structured outputs, host-rendered numbers, completeness checks |

## Release environment notes

* Builds ran behind a TLS-inspecting proxy. The images accept an optional `extra_ca` BuildKit
  secret, and the release run supplied the proxy CA through an override file that is not part of
  the repository. Docker Hub rate limits (HTTP 429) were retried with backoff.
* Local inference used llama.cpp commit `c74c71a` on 4 CPU cores. Model file SHA-256s are
  recorded in every local result file (`configuration.model_sha256`).
