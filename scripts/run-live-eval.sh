#!/usr/bin/env bash
# Run the frozen live evaluation against a loopback-only llama.cpp server.
#
#   MODEL_FILE=/abs/qwen.gguf LLAMA_SERVER=/abs/llama-server MODEL_ALIAS=qwen3-4b \
#   PLANNER_PROFILE=constrained REPEATS=3 OUTPUT=/abs/out.json [DATASET=/abs/set.json] \
#   scripts/run-live-eval.sh [CASE ...]
#
# For a hosted model, skip this script and run `python -m agentos.live_eval` directly with
# OPENAI_API_KEY or ANTHROPIC_API_KEY set and PLANNER_PROFILE=general.
set -euo pipefail
cd "$(dirname "$0")/../backend"
: "${MODEL_FILE:?Absolute path to GGUF weights required}"
: "${OUTPUT:?Absolute path for the result JSON required}"
alias_name="${MODEL_ALIAS:-local-instruct}"
port="${LOCAL_MODEL_PORT:-8081}"
log="${OUTPUT%.json}.server.log"
"${LLAMA_SERVER:-llama-server}" -m "$MODEL_FILE" --alias "$alias_name" --host 127.0.0.1 \
    --port "$port" -c "${LOCAL_CONTEXT:-8192}" -np 1 -t "${LOCAL_THREADS:-4}" --jinja \
    --temp 0 --seed 42 >"$log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 180); do
    kill -0 "$server_pid" || { echo "llama-server exited during startup; see $log"; exit 1; }
    curl --noproxy '*' -fs "http://127.0.0.1:$port/health" >/dev/null && break
    sleep 1
done
export OPENAI_BASE_URL="http://127.0.0.1:$port/v1" OPENAI_API_KEY=local-only
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export OPENAI_STRUCTURED_OUTPUT="${OPENAI_STRUCTURED_OUTPUT:-json_schema}"
export PLANNER_PROFILE="${PLANNER_PROFILE:-constrained}"
export MAX_TOKENS="${MAX_TOKENS:-400000}" MODEL_MAX_OUTPUT_TOKENS="${MODEL_MAX_OUTPUT_TOKENS:-768}"
export MODEL_TIMEOUT_SECONDS="${MODEL_TIMEOUT_SECONDS:-180}" USE_MCP=true
export EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-neural}" RETRIEVAL_METHOD="${RETRIEVAL_METHOD:-dense}"
export MODEL_SHA256="${MODEL_SHA256:-$(sha256sum "$MODEL_FILE" | cut -d' ' -f1)}"
export INFERENCE_SERVER="llama.cpp $("${LLAMA_SERVER:-llama-server}" --version 2>&1 | grep -o 'commit [0-9a-f]*' | head -1)"
tmp=$(mktemp -d)
export DATABASE_URL="sqlite:///$tmp/live.db"
cases=()
if (( $# > 0 )); then cases=(--cases "$@"); fi
dataset=(); if [[ -n "${DATASET:-}" ]]; then dataset=(--dataset "$DATASET"); fi
python -m agentos.live_eval --mode openai --model "$alias_name" --repeats "${REPEATS:-1}" \
    --output "$OUTPUT" "${dataset[@]}" "${cases[@]}"
rm -rf "$tmp"
