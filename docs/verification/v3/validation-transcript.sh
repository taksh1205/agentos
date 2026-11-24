set -eu
root=$PWD
pg_bin=$(dirname "$(find .venv -name postgres -type f|head -1)")
export PATH="$root/.venv/bin:$PATH"
cd v3/agentos/backend
out=../docs/verification/v3
(python -m compileall -q agentos tests && ruff check agentos tests && ruff format --check agentos tests) >$out/final-static.txt 2>&1
"$root/$pg_bin/postgres" -D "$root/pg-delivery" -p 42735 -h 127.0.0.1 -k '' >$out/final-postgres.txt 2>&1 & pgpid=$!
trap 'kill "$pgpid" 2>/dev/null || true' EXIT; sleep 1
export TEST_POSTGRES_URL=postgresql+psycopg://agent@127.0.0.1:42735/postgres RUN_NEURAL_TESTS=1 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2
python -m pytest -q -ra --junitxml="$out/backend-junit.xml" >$out/backend-full.txt 2>&1
export DATABASE_URL="$TEST_POSTGRES_URL" CHECKPOINT_DATABASE_URL=postgresql://agent@127.0.0.1:42735/postgres EMBEDDING_BACKEND=neural RERANK_MODEL=cross-encoder/ms-marco-TinyBERT-L-2-v2 RETRIEVAL_METHOD=rerank USE_MCP=true REQUESTS_PER_MINUTE=1000
start_api() {
 python -m uvicorn agentos.api:app --port 36355 >"$1" 2>&1 & apipid=$!
 trap 'kill "$apipid" "$pgpid" 2>/dev/null || true' EXIT
 for i in {1..50}; do curl -fs --noproxy '*' http://127.0.0.1:36355/health >/dev/null && return 0; sleep 1; done
 return 1
}
start_api $out/integrated-server.txt
python -m agentos.workflow_check --url http://127.0.0.1:36355 --output $out/workflows.json >$out/workflows.txt 2>&1
kill "$apipid"; wait "$apipid" || true
start_api $out/restart-server.txt
python - <<'PY' >$out/restart.txt
import json,httpx
rows=json.load(open('../docs/verification/v3/workflows.json'))['runs']
with httpx.Client(base_url='http://127.0.0.1:36355',headers={'Authorization':'Bearer local-demo-token'},trust_env=False) as c:
 for r in rows:
  response=c.get('/runs/'+r['id']);response.raise_for_status()
  assert response.json()['status']=='completed'
  print(r['kind'],'persisted after API process restart',r['id'])
 receipt=rows[-1]['approval']['id']
 assert sum(e['id']==receipt for e in c.get('/inbox').json())==1
 print('Exactly one approved effect for this run after restart')
PY
