#!/usr/bin/env bash
# Run the four synthetic acceptance tasks against a loopback-only llama.cpp server.
set -euo pipefail
cd "$(dirname "$0")/../backend"
: "${MODEL_FILE:?Absolute path to instruction-tuned GGUF weights required}"
: "${RESULT_FILE:?Absolute path for a new JSON result required}"
[[ "$RESULT_FILE" == /* && ! -e "$RESULT_FILE" ]] || { echo "Specify a new absolute result path"; exit 2; }
tempdir=$(mktemp -d)
server_pid=''
cleanup() {
    if [[ -n "$server_pid" ]]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; fi
    rm -rf "$tempdir"
}
trap cleanup EXIT
port="${LOCAL_MODEL_PORT:-8081}"
export OPENAI_MODEL="${LOCAL_MODEL_ALIAS:-local-instruct}" OPENAI_BASE_URL="http://127.0.0.1:$port/v1"
export OPENAI_API_KEY=local-only NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export OPENAI_PLAN_PROFILE=capability OPENAI_STRUCTURED_OUTPUT=json_schema
export MAX_TOKENS=400000 MODEL_MAX_OUTPUT_TOKENS=640 MODEL_TIMEOUT_SECONDS=120 BENCHMARK_CASE_TIMEOUT_SECONDS=360
export DATABASE_URL="sqlite:///$tempdir/workflows.db" OMP_NUM_THREADS=2
export EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-neural}" RETRIEVAL_METHOD=dense USE_MCP=true
"${LLAMA_SERVER:-llama-server}" -m "$MODEL_FILE" --alias "$OPENAI_MODEL" --host 127.0.0.1 --port "$port" \
    -c 8192 -np 1 -t 4 -b 256 -ub 128 --no-warmup --jinja --temp 0 --seed 42 >"${RESULT_FILE%.json}-server.log" 2>&1 &
server_pid=$!
for _ in {1..90}; do
    kill -0 "$server_pid" || { echo "Local inference server exited during startup"; exit 1; }
    if curl --noproxy '*' -fs "http://127.0.0.1:$port/health" >/dev/null; then break; fi
    sleep 1
done
curl --noproxy '*' -fs "http://127.0.0.1:$port/health" >/dev/null
python -m agentos.evaluate --mode openai --model "$OPENAI_MODEL" \
    --dataset ../evals/datasets/local-model-acceptance.json --output "$RESULT_FILE"
