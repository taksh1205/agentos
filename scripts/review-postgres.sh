#!/usr/bin/env bash
# Disposable loopback database and API; never touches an existing cluster.
set -euo pipefail
cd "$(dirname "$0")/../backend"
: "${PG_BIN:?Directory containing PostgreSQL binaries with pgvector installed}"
: "${OUTPUT_DIR:?New absolute directory for results}"
[[ "$OUTPUT_DIR" == /* && ! -e "$OUTPUT_DIR" ]] || exit 2
mkdir -p "$OUTPUT_DIR"
tmp=$(mktemp -d)
pg_pid=
api_pid=
cleanup() {
    if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; wait "$api_pid" 2>/dev/null || true; fi
    if [[ -n "$pg_pid" ]]; then kill "$pg_pid" 2>/dev/null || true; wait "$pg_pid" 2>/dev/null || true; fi
    rm -rf -- "$tmp"
}
trap cleanup EXIT
port=${PG_PORT:-42735}
api=${API_PORT:-36359}
"$PG_BIN/initdb" -D "$tmp/data" -U agent -A trust --no-locale -E UTF8 >"$OUTPUT_DIR/init.log" 2>&1
"$PG_BIN/postgres" -D "$tmp/data" -p "$port" -h 127.0.0.1 -k '' >"$OUTPUT_DIR/postgres.log" 2>&1 & pg_pid=$!
for _ in {1..60}; do
    kill -0 "$pg_pid" || exit 1
    "$PG_BIN/pg_isready" -U agent -d postgres -h 127.0.0.1 -p "$port" >/dev/null && break
    sleep 1
done
export TEST_POSTGRES_URL="postgresql+psycopg://agent@127.0.0.1:$port/postgres" OMP_NUM_THREADS=2
DATABASE_URL=$TEST_POSTGRES_URL python -m agentos.migrate --legacy-documents >"$OUTPUT_DIR/migration.log" 2>&1
python -m pytest -q --junitxml="$OUTPUT_DIR/junit.xml" >"$OUTPUT_DIR/backend.log" 2>&1
export DATABASE_URL=$TEST_POSTGRES_URL CHECKPOINT_DATABASE_URL="postgresql://agent@127.0.0.1:$port/postgres"
export USE_MCP=true EMBEDDING_BACKEND=hashing REQUESTS_PER_MINUTE=1000
export API_URL="http://127.0.0.1:$api"
start_api() {
    python -m uvicorn agentos.api:app --port "$api" >"$OUTPUT_DIR/$1.log" 2>&1 & api_pid=$!
    for _ in {1..60}; do
        kill -0 "$api_pid" || return 1
        curl --noproxy '*' -fs "$API_URL/health" >/dev/null && return 0
        sleep 1
    done
    return 1
}
start_api api
python -m agentos.workflow_check --url "$API_URL" --output "$OUTPUT_DIR/workflows.json" >"$OUTPUT_DIR/workflows.log" 2>&1
kill "$api_pid"; wait "$api_pid" || true; api_pid=
start_api restarted-api
python - "$OUTPUT_DIR/workflows.json" <<'PY' >"$OUTPUT_DIR/restart.log"
import json, os, sys
import httpx
rows = json.load(open(sys.argv[1]))["runs"]
with httpx.Client(base_url=os.environ["API_URL"], trust_env=False,
                  headers={"Authorization":"Bearer local-demo-token"}) as client:
    for run in rows:
        resp = client.get("/runs/" + run["id"])
        resp.raise_for_status()
        assert resp.json()["status"] == "completed"
        print(run["kind"],run["id"],"persisted")
    receipt = rows[-1]["approval"]["id"]
    inbox = client.get("/inbox")
    inbox.raise_for_status()
    assert sum(x["id"] == receipt for x in inbox.json()) == 1
    print("One matching approved receipt after API restart")
PY
