# Archive: development history

Everything in this folder documents **earlier development rounds** of AgentOS (V1 → V2 → V3 →
"final" → "hardening"). It is preserved for transparency, including failed attempts such as the
round where 0/3 live workflows passed. None of it is the current release evidence.

Current results live in:

- [`docs/AI_EVALUATION_FINAL.md`](../AI_EVALUATION_FINAL.md): live-model and retrieval results
- [`docs/FINAL_RELEASE_AUDIT.md`](../FINAL_RELEASE_AUDIT.md): PASS / FAIL / BLOCKED matrix
- [`docs/evidence/`](../evidence/): raw logs and JSON behind the current numbers

| Item | What it is |
|---|---|
| `baseline/` | V1 test and build output (19 passed, 1 skipped) |
| `AUDIT_V2.md`, `HISTORICAL_V2_ENGINEERING_REPORT.md` | V2 audit of the V1 demo and its upgrade |
| `HISTORICAL_V3_ENGINEERING_REPORT.md`, `ENGINEERING_REPORT.md` | V3 rounds, first local Qwen runs |
| `ACCEPTANCE.md`, `FINAL_AI_EVALUATION.md`, `RELEASE_VERIFICATION.md` | "Final" round: 114 tests, **0/3** live workflows passed |
| `ACCEPTANCE_REPAIR.md`, `HARDENING.md` | Repair and hardening rounds: 124 tests, 3/3 originals and 6/6 trials on Qwen2.5-1.5B |
| `verification/` | Raw logs and JSON for every round above |
| `SOURCE_MANIFEST.json` | File hashes of the hardening-round archive (SHA-256 `53d103eb…`) |

Links inside these reports point to files in this folder and were rewritten when the folder moved.
