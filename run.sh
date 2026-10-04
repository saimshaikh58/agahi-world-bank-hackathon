#!/usr/bin/env bash
# agahi_hackathon: one-command start for macOS / Linux.
set -e
cd "$(dirname "$0")"
PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. ".venv/bin/activate"
if ! python -c "import fastapi, uvicorn, sklearn, pandas, rapidfuzz, httpx, PIL, jinja2, multipart, docx" >/dev/null 2>&1; then
  echo "Installing requirements (first time only)..."
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r requirements-train.txt
fi
[ -f .env ] || cp .env.example .env
python scripts/first_run.py
PORT=$(grep -E '^PORT=' .env | cut -d= -f2)
PORT=${PORT:-8000}
if python -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', int('$PORT')))==0 else 1)"; then
  echo "Port $PORT is busy, using $((PORT+1))"
  PORT=$((PORT+1))
fi
PW=$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2)
echo ""
echo "  Chat:  http://localhost:$PORT/   Admin: http://localhost:$PORT/admin   Password: ${PW:-agahi-admin}"
echo "  (Change ADMIN_PASSWORD in .env before sharing. Press Ctrl+C to stop.)"
echo ""
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
