#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && ruff check agentos tests && ruff format --check agentos tests && pytest -q)
(cd frontend && npm test && npm run build)
# Optional: TEST_POSTGRES_URL=... RUN_NEURAL_TESTS=1 scripts/verify.sh
