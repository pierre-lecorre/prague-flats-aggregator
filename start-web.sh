#!/usr/bin/env bash
# Quickstart: local flats dashboard at http://127.0.0.1:8765
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null; then
  echo "python3 missing" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

export PYTHONPATH="$ROOT/src"
PORT="${WEB_PORT:-8765}"
HOST="${WEB_HOST:-127.0.0.1}"
echo "Dashboard → http://${HOST}:${PORT}"
exec python3 "$ROOT/src/webapp.py"
