# AgentOS V3 · independent review build

**Historical review.** See the [latest acceptance and verification report](ACCEPTANCE_REPAIR.md) for the repaired release.

This update starts from the previously delivered V3 ZIP, SHA-256 `288e7542189e378d935088bc18e1f8aee2b729d1e5de778a7379da719d23905a`. Earlier measurements remain in [the previous handoff](HISTORICAL_V3_ENGINEERING_REPORT.md). New evidence lives in [verification/v3-review](verification/v3-review/).

## What changed

| Previously missed behavior | Root cause and correction |
|---|---|
| February totals and March profit | The offline analytics parser ignored periods. It now resolves ISO periods and named months against workspace-scoped sales records, supports contiguous intervals, and rejects ambiguous or disjoint requests. |
| Two contradictory capacity bulletins | Retrieval found both. The offline synthesis copied them without comparing values. It now compares explicit quantities with matching subjects, units and temporal qualifiers across distinct sources, cites the disagreement and reports uncertainty. Coverage is limited to the supported sentence forms. |
| Recording a result in an internal report | The action detector missed report-writing verbs. A report write now depends on the analytical read, presents the exact proposal, and preserves the committed receipt. |
| An impossible postcondition on an action | A real Qwen run attached a profit target to a notification. The graph now rejects checks outside the agent's responsibility. A failed review after a committed write terminates with the receipt instead of opening another write plan. |
| Provider compatibility and accounting | The adapter supports required tool selection or schema-constrained JSON, configurable bounded timeouts and a compact capability planner. Benchmark rows now retain model attempts and known usage even when execution fails. Unreported usage remains null. |

## Verification

| Area | Execution and result |
|---|---|
| Offline agent behavior | Reproduced 5/9 before changes. After repair, 9/9 on the same cases, 24/24 original regression cases, 8/8 additional authored tasks. These are deterministic behavioral checks. |
| Neural retrieval | Reran six retrieval configurations on the 32-document development corpus and 46-document review corpus. Dense MiniLM achieved 0.974 nDCG@5 and 1.000 Recall@5 on the 14 review queries. TinyBERT reranking reached 0.920 nDCG@5. |
| Memory and verifier | Both neural and hashing memory evaluations ran. The eight two-turn facts use a deterministic extractor; the verifier challenge evaluates checks on supplied claims. See the standalone JSON results. |
| Application | Three HTTP workflows passed with PostgreSQL, pgvector, neural retrieval and MCP. All three survived an API restart. The operational scenario checked both policies and totals and exactly one approved effect. |
| Frontend | Two interaction tests, TypeScript, Next.js production build and a Chromium execution/approval journey passed. |
| Hosted services | No OpenAI or Anthropic service credentials were configured. Both official SDKs have transport-mocked tests. Docker Compose and hosted CI remain unexecuted in this environment. |

## Local language-model evidence

Qwen2.5-1.5B-Instruct Q4_K_M ran locally with llama.cpp b12498. Named tool selection failed all three initial tasks. Switching to required tool selection returned seven structured model responses (8,086 reported tokens) on three tasks. None met all acceptance criteria. The notification reached a local tool after approval but final verification failed. Additional development runs encountered timeouts and local server termination. In particular, `local-q4.json` contains connection failures, and the earlier four-case `qwen3-acceptance-server.log` has no complete scorecard. These artifacts cannot establish end-to-end success.

The exact model digests are `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` (Qwen2.5-1.5B) and `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` (Qwen3-4B-Instruct-2507). No remote API fee was incurred; hardware and electricity costs were not measured.

## Reproduce and review

Run the README setup and `scripts/verify.sh`. For full backend coverage set `TEST_POSTGRES_URL` to a disposable pgvector database, set `RUN_NEURAL_TESTS=1`, and run `python -m pytest -q -ra` from backend. For the offline comparisons run `python -m agentos.evaluate --dataset ../evals/datasets/agents-heldout.json --output /tmp/repaired.json` and repeat with `review-transfer.json`. For real model comparisons see `scripts/evaluate-local-model.sh` and the dataset and provider settings recorded in each result.

Start independent review with the failing and repaired h02 and h05 traces, then compare the model plans with actual tool receipts. The synthetic benchmark is small and author-labeled. Broader language understanding, hosted model quality and a public deployment require separate verification. This build is for source review and private demonstrations.

## Final release checks

**102 backend tests passed, 0 failed, 0 skipped.** The portable run passed 97 and skipped the five optional infrastructure checks. Raw outputs are in `final-full.txt` and `final-portable.txt`.

The final Qwen3-4B local notification check produced 4 model responses over 4 recorded attempts. It used 1341 reported tokens in 49.9 seconds. Graph status was completed; all benchmark expectations matched: True. Approval interrupts: 1. Exact requested message verified against one persisted effect: True. See `local-smoke.json` and `local-smoke-effects.json`. This single task does not establish multi-document or broad model reasoning accuracy.
