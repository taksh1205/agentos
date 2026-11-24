#!/usr/bin/env bash
# Run in a clean checkout with localhost ports 3000 and 8000 available.
# Uses a private Compose project. Its volumes remain for inspection.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -p agentos-v3-review -f compose.yaml)
if [[ "${NEURAL:-0}" == 1 ]]; then compose+=(-f compose.neural.yaml); fi
# Extra override files, colon-separated (e.g. a CA override behind a TLS-intercepting proxy).
if [[ -n "${COMPOSE_OVERRIDES:-}" ]]; then
    IFS=: read -r -a extra <<<"$COMPOSE_OVERRIDES"
    for file in "${extra[@]}"; do compose+=(-f "$file"); done
fi
out="${OUTPUT_DIR:-docs/verification/compose-local}"
mkdir -p "$out"
"${compose[@]}" up -d --build --wait
trap '"${compose[@]}" stop' EXIT
for attempt in {1..90}; do
    if curl -fsS http://localhost:8000/health >/dev/null && curl -fsS http://localhost:3000 >/dev/null; then break; fi
    sleep 2
done
"${compose[@]}" exec -T backend python -m agentos.workflow_check --output /tmp/workflow-results.json
"${compose[@]}" cp backend:/tmp/workflow-results.json "$out/workflows.json"
"${compose[@]}" stop backend
"${compose[@]}" restart postgres
"${compose[@]}" up -d --wait backend
for attempt in {1..90}; do
    if curl -fsS http://localhost:8000/health >/dev/null; then break; fi
    sleep 2
done
python - "$out/workflows.json" <<'PY'
import json, os, sys, urllib.request
data=json.load(open(sys.argv[1]))
for run in data["runs"]:
    request=urllib.request.Request("http://localhost:8000/runs/"+run["id"],headers={"Authorization":"Bearer "+os.getenv("AGENTOS_TOKEN","local-demo-token")})
    with urllib.request.urlopen(request,timeout=10) as response:
        assert json.load(response)["status"]=="completed"
print("All three stored workflow results survived restart.")
PY
