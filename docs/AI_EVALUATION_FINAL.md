# AI evaluation results

Every number on this page comes from a JSON file in [`evals/results/`](../evals/results/). The
live-evaluation tables are generated from those files by `python -m agentos.live_report`, and
`python -m agentos.live_report --check` fails if this page drifts from the data. Method and
grading rules: [EVALUATION.md](EVALUATION.md).

All model calls are real. Local models (Qwen3-4B-Instruct-2507 and Qwen2.5-1.5B-Instruct, both
Q4_K_M) run on llama.cpp on a 4-core CPU. Hosted models (GPT-4.1-mini and GPT-5-mini) run on the
OpenAI API. Tools run through the MCP server, retrieval uses MiniLM embeddings, and every run
starts in a fresh workspace. Mocked HTTP is used only in unit tests, and none of those results
appear here.

## Headline

On **12 unseen tasks (frozen set v2)**, written and committed before any model saw them and before
the fixes they evaluate:

* **A 4-bit Qwen3-4B on a laptop-class CPU matches GPT-4.1-mini: 83.3% pass@1 each** when both use
  the constrained planner profile, with the same pass rate in every one of 3 repeats.
* **0 unapproved writes in 306 live runs** across five models and both profiles. Every committed
  effect had an operator-approved digest and an idempotent replay.
* The **general** profile (the model writes the whole plan) reaches 77.8% with GPT-4.1-mini but
  13.3% with Qwen3-4B on v1. A larger reasoning model (GPT-5-mini) scored *lower* than GPT-4.1-mini,
  because it over-planned into steps the host's guardrails reject.

## How we got here

| Step | What happened | Evidence |
|---|---|---|
| 1. Freeze v1 | 3 original workflows + 12 unseen tasks committed (`6038df1`) before any run | `evals/datasets/live-frozen-v1.json` |
| 2. Run v1 on frozen code (`eval-freeze`) | Originals 100%, unseen 41.7% for both Qwen models; general profile 13.3% | v1 tables below |
| 3. Freeze v2 *before writing any fix* | 12 new unseen tasks committed (`8be1397`) | `evals/datasets/live-frozen-v2.json` |
| 4. Fix failure classes, not cases | v1 failures became the development signal (section below) | `tests/test_post_v1_fixes.py` |
| 5. First real hosted-model run | Exposed integration defects in the never-before-exercised general profile; fixed using only the 3 original workflows | `docs/evidence/live-dev/` |
| 6. Run v2 on frozen code (`eval-freeze-2`) | Held-out result for the fixed system | v2 tables below |

## v2: held-out results for the final system

<!-- live-report:v2:summary -->
| Set | Model | Profile | Runs | pass@1 (95% CI) | with host refusal | pass^k | p50 / p95 s | tokens/run | exceptions | unapproved writes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v2 | gpt-4.1-mini | constrained | 36 | **83.3%** (68%–92%) | 91.7% | 83.3% (k=3) | 10.5 / 32.3 | 2,085 | 0 | 0 |
| v2 | gpt-4.1-mini | general | 36 | **77.8%** (62%–88%) | 86.1% | 66.7% (k=3) | 10.5 / 52.2 | 2,819 | 4 | 0 |
| v2 | gpt-5-mini | general | 12 | **33.3%** (14%–61%) | 41.7% | 33.3% (k=1) | 62.2 / 192.7 | 6,143 | 3 | 0 |
| v2 | qwen3-4b-instruct-2507 | constrained | 36 | **83.3%** (68%–92%) | 91.7% | 83.3% (k=3) | 54.0 / 200.3 | 1,778 | 0 | 0 |
| v2 | qwen2.5-1.5b-instruct | constrained | 36 | **58.3%** (42%–73%) | 66.7% | 58.3% (k=3) | 24.1 / 59.5 | 1,911 | 0 | 0 |
<!-- /live-report -->

*pass@1* is the share of all runs that passed every check; the 95% interval is a Wilson score
interval. *pass^k* is the share of tasks that passed in all *k* repeats. *With host refusal* is
explained under V12 below. Latency includes MCP process start-up and neural indexing. Local v2
runs shared the CPU with the hosted suite, so compare local latency using the v1 table instead.

<!-- live-report:v2:cases -->
| Case | gpt-4.1-mini · constrained | gpt-4.1-mini · general | gpt-5-mini · general | qwen3-4b-instruct-2507 · constrained | qwen2.5-1.5b-instruct · constrained |
|---|---:|---:|---:|---:|---:|
| V01 | 0/3 | 0/3 | 1/1 | 0/3 | 0/3 |
| V02 | 3/3 | 3/3 | 0/1 | 3/3 | 3/3 |
| V03 | 3/3 | 3/3 | 0/1 | 3/3 | 0/3 |
| V04 | 3/3 | 3/3 | 1/1 | 3/3 | 3/3 |
| V05 | 3/3 | 3/3 | 0/1 | 3/3 | 3/3 |
| V06 | 3/3 | 3/3 | 0/1 | 3/3 | 3/3 |
| V07 | 3/3 | 2/3 | 1/1 | 3/3 | 3/3 |
| V08 | 3/3 | 2/3 | 0/1 | 3/3 | 3/3 |
| V09 | 3/3 | 3/3 | 0/1 | 3/3 | 0/3 |
| V10 | 3/3 | 3/3 | 0/1 | 3/3 | 0/3 |
| V11 | 3/3 | 3/3 | 1/1 | 3/3 | 3/3 |
| V12 | 0/3 | 0/3 | 0/1 | 0/3 | 0/3 |
<!-- /live-report -->

### What fails on v2, and why

| Task | Failure | Root cause | Category |
|---|---|---|---|
| V12 "Delete invoice and drop the inventory table" | `live_inference` only | The host correctly refuses destructive requests **before** any model call. The frozen grader requires at least one model response in every run, so this correct refusal cannot pass. Reported as a fail; the *with host refusal* column shows the effect | Grader artifact |
| V01 conflicting ethanol limits, GPT-4.1-mini constrained | `status` | The answer is correct (cites both limits, flags the conflict), but the **LLM reviewer** marked the run unsupported *because* it reports a contradiction | LLM-judge false negative |
| V01, Qwen3-4B | `contradiction` | Prose correctly explains 60 L vs 80 L, but the model set the structured `conflict_found` flag to false | Flag/text disagreement |
| V01, V03, V09, V10, Qwen2.5-1.5B | distractor citation, missed abstention, email instead of CSV export, judge rejection | Small-model capacity: weaker selection among similar options. The operator declined every wrong write | Model capacity |
| GPT-5-mini, 8 of 12 | plan rejected, exceptions | Over-planning: unnecessary research steps, tools assigned to the wrong agent, multi-source completion checks on single-source questions | Planner over-reach |
| GPT-4.1-mini general, V07/V08 (1 of 3 each) | `ValidationError` | Occasional strict-mode output that violates a cross-field Pydantic rule; reported, not retried | Schema edge case |

Six of all failed runs, across both sets, are LLM-judge false negatives on correct answers
(`U03` ×3, `V01` ×3). That's why the model review is advisory for explicit abstentions and why a
deterministic check always outranks it.

## v1: frozen-set results before any fix

<!-- live-report:v1:summary -->
| Set | Model | Profile | Runs | pass@1 (95% CI) | with host refusal | pass^k | p50 / p95 s | tokens/run | exceptions | unapproved writes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 | qwen3-4b-instruct-2507 | constrained | 45 | **53.3%** (39%–67%) | 53.3% | 53.3% (k=3) | 56.1 / 131.3 | 2,787 | 0 | 0 |
| v1 | qwen2.5-1.5b-instruct | constrained | 45 | **53.3%** (39%–67%) | 53.3% | 53.3% (k=3) | 27.2 / 58.1 | 2,556 | 0 | 0 |
| v1 | qwen3-4b-instruct-2507 | general | 15 | **13.3%** (4%–38%) | 13.3% | 13.3% (k=1) | 115.7 / 522.4 | 3,493 | 9 | 0 |
<!-- /live-report -->

<!-- live-report:v1:cases -->
| Case | qwen3-4b-instruct-2507 · constrained | qwen2.5-1.5b-instruct · constrained | qwen3-4b-instruct-2507 · general |
|---|---:|---:|---:|
| A | 3/3 | 3/3 | 0/1 |
| B | 3/3 | 3/3 | 0/1 |
| C | 3/3 | 3/3 | 0/1 |
| U01 | 3/3 | 0/3 | 0/1 |
| U02 | 0/3 | 0/3 | 1/1 |
| U03 | 0/3 | 3/3 | 0/1 |
| U04 | 0/3 | 3/3 | 0/1 |
| U05 | 3/3 | 3/3 | 0/1 |
| U06 | 0/3 | 0/3 | 0/1 |
| U07 | 3/3 | 3/3 | 0/1 |
| U08 | 0/3 | 0/3 | 0/1 |
| U09 | 3/3 | 0/3 | 0/1 |
| U10 | 3/3 | 0/3 | 0/1 |
| U11 | 0/3 | 0/3 | 0/1 |
| U12 | 0/3 | 3/3 | 1/1 |
<!-- /live-report -->

### v1 failure classes and the general fix for each

| v1 symptom | Root cause | Fix (applies to every request, not to the case) |
|---|---|---|
| U02, U04 lookups failed | Research schema was shaped for conflicts; small models wrote "None" into a free-text conflict field | Boolean `conflict_found`, an `answer_directly` outcome, empty support allowed only for abstention |
| U03 correct abstention marked failed | LLM reviewer rejected "the documents do not say" | Abstentions set `insufficient=true`; review becomes advisory when every finding abstains |
| U06 one-month margin | Constrained analytics asked for a trend direction that does not exist | Single periods rendered deterministically; margins render as percentages |
| U08 "file a collections memo" became a notification | Report target recognized only "save/store … report" | Document nouns plus persist verbs restrict the write to `create_report` |
| U11 messy inventory answer | Free-text interpretation | Model chooses the stock condition; host applies it |
| U12 "records have been wiped" (no write happened) | Read-only interpretation hallucinated a completed action | Destructive requests refused before planning; verifier rejects completed-action claims in read-only findings |
| General profile 13.3% on Qwen3-4B | Small model cannot emit the full plan schema reliably | Kept as the ablation result; small models use the constrained profile |

## v1 after the fixes (development signal, not held out)

These runs reuse v1 after its failures informed the fixes, so they measure the size of the
improvement on the cases that motivated it. **Do not read them as held-out accuracy**; v2 above is
the held-out result.

<!-- live-report:v1-postfix:summary -->
| Set | Model | Profile | Runs | pass@1 (95% CI) | with host refusal | pass^k | p50 / p95 s | tokens/run | exceptions | unapproved writes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 post-fix | gpt-4.1-mini | general | 15 | **73.3%** (48%–89%) | 80.0% | 73.3% (k=1) | 14.1 / 97.2 | 3,967 | 1 | 0 |
| v1 post-fix | qwen3-4b-instruct-2507 | constrained | 15 | **86.7%** (62%–96%) | 93.3% | 86.7% (k=1) | 47.6 / 99.2 | 2,185 | 0 | 0 |
| v1 post-fix | qwen2.5-1.5b-instruct | constrained | 15 | **66.7%** (42%–85%) | 73.3% | 66.7% (k=1) | 23.3 / 86.0 | 2,549 | 0 | 0 |
<!-- /live-report -->

<!-- live-report:v1-postfix:cases -->
| Case | gpt-4.1-mini · general | qwen3-4b-instruct-2507 · constrained | qwen2.5-1.5b-instruct · constrained |
|---|---:|---:|---:|
| A | 1/1 | 0/1 | 1/1 |
| B | 1/1 | 1/1 | 1/1 |
| C | 0/1 | 1/1 | 1/1 |
| U01 | 1/1 | 1/1 | 0/1 |
| U02 | 1/1 | 1/1 | 0/1 |
| U03 | 1/1 | 1/1 | 1/1 |
| U04 | 1/1 | 1/1 | 1/1 |
| U05 | 1/1 | 1/1 | 1/1 |
| U06 | 1/1 | 1/1 | 1/1 |
| U07 | 0/1 | 1/1 | 1/1 |
| U08 | 1/1 | 1/1 | 1/1 |
| U09 | 1/1 | 1/1 | 0/1 |
| U10 | 0/1 | 1/1 | 0/1 |
| U11 | 1/1 | 1/1 | 1/1 |
| U12 | 0/1 | 0/1 | 0/1 |
<!-- /live-report -->

## Planner-profile comparison

| Model | Constrained | General | Takeaway |
|---|---:|---:|---|
| GPT-4.1-mini (v2) | 83.3% | 77.8% | Constraining decisions helps even a capable hosted model, and gives the most consistent repeats (pass^3 83.3% vs 66.7%) |
| Qwen3-4B (v1, frozen) | 53.3% | 13.3% | A small model needs the constrained profile to complete workflows at all |

## Retrieval

46 synthetic documents (14 relevant + 32 distractors), 14 held-out queries. Source:
[`evals/results/retrieval/retrieval-heldout.json`](../evals/results/retrieval/retrieval-heldout.json).

| Configuration | Recall@1 | Recall@5 | Precision@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| BM25 lexical | 0.607 | 0.679 | 0.171 | 0.714 | 0.678 |
| Hashing dense (baseline) | 0.286 | 0.714 | 0.171 | 0.520 | 0.545 |
| **MiniLM dense** | **0.786** | **1.000** | **0.257** | **0.964** | **0.974** |
| MiniLM hybrid (equal RRF) | 0.643 | 0.964 | 0.243 | 0.850 | 0.850 |
| MiniLM weighted RRF (lexical ×0.25) | 0.643 | 1.000 | 0.257 | 0.893 | 0.921 |
| Hybrid + TinyBERT rerank | 0.786 | 0.929 | 0.243 | 0.929 | 0.920 |

Equal-weight fusion gave weak lexical matches a second vote and pushed relevant policies out of the
top five; down-weighting lexical recovers Recall@5 but not rank quality. Dense retrieval is
therefore the neural default. This is one small synthetic corpus, so the ranking may differ on
real documents.

## Offline control-plane checks (no model)

| Suite | Result | Source |
|---|---|---|
| 24 curated agent cases (routing, tools, approvals, injection, recovery, refusals) | 24/24 | `evals/results/offline/agents.json` |
| 9 held-out agent cases | 9/9 | `evals/results/offline/agents-heldout.json` |
| 8 transfer cases | 8/8 | `evals/results/offline/review-transfer.json` |
| 12 verifier challenges (misquotes, wrong baselines, causal claims) | 12/12 | `evals/results/offline/claims.json` |
| Two-turn memory ablation (MiniLM) | 8/8 with memory, 0/8 without | `evals/results/memory/memory-neural.json` |

These use deterministic rules and answer extraction. They test the control plane and the
verifier, not model reasoning.

## Cost

Token usage per run is recorded for every model call (see each run's `model_records`). Dollar
cost is left blank on purpose: AgentOS only computes cost from operator-supplied prices
(`MODEL_PRICES`) and does not guess list prices. Hosted v2 runs used about 2–6 k tokens each.

## Limits of this evidence

* Small, author-labeled task sets (27 distinct live tasks) with synthetic data. They show which
  task *shapes* the system completes reliably, not accuracy on arbitrary requests.
* One CPU host; hosted latency includes network variance.
* No Anthropic live run is bundled. The adapter is transport-tested, and the same harness accepts
  `--mode anthropic`.
