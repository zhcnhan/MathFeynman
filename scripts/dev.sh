#!/usr/bin/env bash
# YanHui 一键启动（macOS/Linux，docs/02 §4）。Windows 用 scripts/dev.ps1。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
RUNTIME="$ROOT/.runtime"
mkdir -p "$RUNTIME"
PY="$VENV/bin/python"

[ -x "$PY" ] || python3 -m venv "$VENV"
"$PY" -m pip install -e "$ROOT/backend" -q
[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm install --no-fund --no-audit)

echo "启动后端 uvicorn (127.0.0.1:8000)…"
(cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  >"$RUNTIME/backend.out.log" 2>"$RUNTIME/backend.err.log") &
echo $! > "$RUNTIME/backend.pid"

echo "启动前端 vite dev…"
(cd "$ROOT/frontend" && exec npm run dev -- --port 5173 --host 127.0.0.1 \
  >"$RUNTIME/front.out.log" 2>"$RUNTIME/front.err.log") &
echo $! > "$RUNTIME/front.pid"

sleep 5
echo "浏览器打开 http://127.0.0.1:5173  （停止: kill \$(cat $RUNTIME/*.pid)）"
