"""Render the live-evaluation tables in docs/AI_EVALUATION_FINAL.md from bundled results.

    python -m agentos.live_report            # print Markdown tables
    python -m agentos.live_report --check    # fail if docs differ from the result files

Pass rates use the frozen grader exactly. The "host refusal" column additionally counts a
run as passing when its *only* failed check is ``live_inference`` and the host refused the
request before any model call (the correct outcome for a destructive request; the frozen
grader requires a model response in every run). Both are reported; neither replaces the other.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results" / "live"


def wilson(passed, total, z=1.96):
    if not total:
        return (0.0, 0.0)
    p = passed / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    denom = 1 + z * z / total
    return ((centre - spread) / denom, (centre + spread) / denom)


def host_refusal(run):
    failed = [k for k, ok in run["grade"]["checks"].items() if not ok]
    return failed == ["live_inference"] and (run.get("report") or {}).get("status") == "refused"


def load(name):
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def row(name, data):
    runs = data["runs"]
    passed = sum(r["grade"]["passed"] for r in runs)
    adjusted = sum(r["grade"]["passed"] or host_refusal(r) for r in runs)
    low, high = wilson(passed, len(runs))
    cfg, s = data["configuration"], data["summary"]
    k = cfg["repeats"]
    tokens = s["mean_tokens_per_run"]
    return (
        f"| {cfg['dataset'].replace('agentos-live-frozen-', '')}{' post-fix' if 'postfix' in name else ''} "
        f"| {cfg['model']} | {cfg['planner_profile']} | {len(runs)} "
        f"| **{passed / len(runs):.1%}** ({low:.0%}–{high:.0%}) | {adjusted / len(runs):.1%} "
        f"| {s.get(f'pass_all_{k}', 0):.1%} (k={k}) | {s['p50_seconds']:.1f} / {s['p95_seconds']:.1f} "
        f"| {round(tokens):,} | {s['exceptions']} | {s['unapproved_effects']} |"
    )


HEADER = (
    "| Set | Model | Profile | Runs | pass@1 (95% CI) | with host refusal | pass^k | p50 / p95 s "
    "| tokens/run | exceptions | unapproved writes |\n"
    "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def table(names):
    rows = [row(n, d) for n in names if (d := load(n))]
    return HEADER + "\n" + "\n".join(rows)


def cases(names):
    loaded = [(n, d) for n in names if (d := load(n))]
    ids = list(loaded[0][1]["summary"]["cases"]) if loaded else []
    head = (
        "| Case | "
        + " | ".join(
            d["configuration"]["model"] + " · " + d["configuration"]["planner_profile"]
            for _, d in loaded
        )
        + " |"
    )
    lines = [head, "|---|" + "---:|" * len(loaded)]
    for case in ids:
        cells = []
        for _, d in loaded:
            c = d["summary"]["cases"].get(case)
            cells.append(f"{c['passed']}/{c['runs']}" if c else "—")
        lines.append(f"| {case} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


SECTIONS = {
    "v2": [
        "v2-gpt-4.1-mini-constrained",
        "v2-gpt-4.1-mini-general",
        "v2-gpt-5-mini-general",
        "v2-qwen3-4b-constrained",
        "v2-qwen2.5-1.5b-constrained",
    ],
    "v1": ["v1-qwen3-4b-constrained", "v1-qwen2.5-1.5b-constrained", "v1-qwen3-4b-general"],
    "v1-postfix": [
        "v1-postfix-gpt-4.1-mini-general",
        "v1-postfix-qwen3-4b-constrained",
        "v1-postfix-qwen2.5-1.5b-constrained",
    ],
}


def render():
    out = []
    for key, names in SECTIONS.items():
        out.append(f"<!-- live-report:{key}:summary -->\n{table(names)}\n<!-- /live-report -->")
        out.append(f"<!-- live-report:{key}:cases -->\n{cases(names)}\n<!-- /live-report -->")
    return "\n\n".join(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true", help="Fill the marked blocks in docs")
    args = parser.parse_args()
    text = render()
    if args.write:
        import re

        doc_path = ROOT / "docs" / "AI_EVALUATION_FINAL.md"
        doc = doc_path.read_text()
        for block in text.split("\n\n"):
            marker = block.split("\n", 1)[0]
            pattern = re.escape(marker) + r"\n.*?<!-- /live-report -->"
            doc = re.sub(pattern, lambda _: block, doc, count=1, flags=re.S)
        doc_path.write_text(doc)
        print("updated", doc_path)
    elif args.check:
        doc = (ROOT / "docs" / "AI_EVALUATION_FINAL.md").read_text()
        missing = [block for block in text.split("\n\n") if block not in doc]
        if missing:
            raise SystemExit(f"{len(missing)} generated tables differ from docs; rerun live_report")
        print("docs match bundled results")
    else:
        print(text)
