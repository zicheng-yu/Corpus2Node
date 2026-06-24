#!/usr/bin/env bash
#
# corpus — dev / release launcher for Corpus2Node
#   FastAPI backend (uv + uvicorn)  +  React/Vite frontend (npm)
#
# Usage:
#   corpus            same as `corpus dev`
#   corpus dev        run both in the FOREGROUND with reload/HMR; Ctrl-C stops both  (debugging)
#   corpus start      run both in the BACKGROUND (logs to .run/logs); survives terminal close  (release)
#   corpus stop|end   stop the background servers
#   corpus restart    stop then start (background)
#   corpus status     show what's running
#   corpus logs       tail the background logs
#   corpus help       this message
#
# Env overrides: CORPUS_HOST, CORPUS_BACKEND_PORT, CORPUS_FRONTEND_PORT
#
set -uo pipefail
export PATH="$PATH:/usr/sbin:/usr/bin:/bin"  # ensure lsof/pgrep are found in non-login shells

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/frontend"
RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
BACK_PIDFILE="$RUN_DIR/backend.pid"
FRONT_PIDFILE="$RUN_DIR/frontend.pid"

HOST="${CORPUS_HOST:-127.0.0.1}"
BACK_PORT="${CORPUS_BACKEND_PORT:-8000}"
FRONT_PORT="${CORPUS_FRONTEND_PORT:-5173}"

# ── pretty output ─────────────────────────────────────────────────────────────
_c() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
info() { _c "34" "• $*"; }
ok()   { _c "32" "✓ $*"; }
warn() { _c "33" "! $*"; }
die()  { _c "31" "✗ $*"; exit 1; }

# ── helpers ───────────────────────────────────────────────────────────────────
ensure_deps() {
  command -v uv  >/dev/null 2>&1 || die "uv not found — install from https://docs.astral.sh/uv/"
  command -v npm >/dev/null 2>&1 || die "npm not found — install Node.js"
  if [ ! -d "$FRONTEND/node_modules" ]; then
    info "frontend deps missing — running npm install…"
    ( cd "$FRONTEND" && npm install ) || die "npm install failed"
  fi
  mkdir -p "$LOG_DIR"
}

port_busy() { command -v lsof >/dev/null 2>&1 && lsof -ti tcp:"$1" >/dev/null 2>&1; }
free_port() { command -v lsof >/dev/null 2>&1 && lsof -ti tcp:"$1" 2>/dev/null | xargs kill 2>/dev/null; return 0; }

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
pidfile_alive() { [ -f "$1" ] && pid_alive "$(cat "$1" 2>/dev/null)"; }

# recursively kill a process and its descendants (uvicorn --reload / vite spawn children)
kill_tree() {
  local pid="${1:-}" child
  [ -n "$pid" ] || return 0
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null
}

# ── commands ──────────────────────────────────────────────────────────────────
dev() {
  ensure_deps
  port_busy "$BACK_PORT"  && die "port $BACK_PORT busy — 'corpus stop' first, or set CORPUS_BACKEND_PORT"
  port_busy "$FRONT_PORT" && die "port $FRONT_PORT busy — 'corpus stop' first, or set CORPUS_FRONTEND_PORT"

  local back front
  ( cd "$ROOT" && exec uv run uvicorn corpus2node.api.app:app --reload --host "$HOST" --port "$BACK_PORT" ) &
  back=$!
  ( cd "$FRONTEND" && exec npm run dev -- --port "$FRONT_PORT" --strictPort ) &
  front=$!

  cleanup() {
    trap - INT TERM EXIT
    printf '\n'; info "stopping…"
    kill_tree "$back"; kill_tree "$front"
    free_port "$BACK_PORT"; free_port "$FRONT_PORT"
    ok "stopped"
  }
  trap cleanup INT TERM EXIT

  printf '\n'
  ok   "backend   http://$HOST:$BACK_PORT      (docs: /docs · min-ui: /ui)"
  ok   "frontend  http://localhost:$FRONT_PORT"
  info "Ctrl-C to stop both"
  printf '\n'
  wait
}

start() {
  ensure_deps
  if pidfile_alive "$BACK_PIDFILE" || port_busy "$BACK_PORT"; then
    warn "backend already running on $BACK_PORT"
  else
    ( cd "$ROOT" && exec nohup uv run uvicorn corpus2node.api.app:app --host "$HOST" --port "$BACK_PORT" \
        >"$LOG_DIR/backend.log" 2>&1 ) &
    echo $! > "$BACK_PIDFILE"
    ok "backend  → http://$HOST:$BACK_PORT  (log: .run/logs/backend.log)"
  fi
  if pidfile_alive "$FRONT_PIDFILE" || port_busy "$FRONT_PORT"; then
    warn "frontend already running on $FRONT_PORT"
  else
    ( cd "$FRONTEND" && exec nohup npm run dev -- --port "$FRONT_PORT" --strictPort \
        >"$LOG_DIR/frontend.log" 2>&1 ) &
    echo $! > "$FRONT_PIDFILE"
    ok "frontend → http://localhost:$FRONT_PORT  (log: .run/logs/frontend.log)"
  fi
  printf '\n'
  info "follow logs: corpus logs   ·   stop: corpus stop"
}

stop() {
  local did=0
  for pf in "$BACK_PIDFILE" "$FRONT_PIDFILE"; do
    if [ -f "$pf" ]; then
      kill_tree "$(cat "$pf" 2>/dev/null)"
      rm -f "$pf"
      did=1
    fi
  done
  # safety net: free the ports even if a pidfile was lost
  free_port "$BACK_PORT"; free_port "$FRONT_PORT"
  if [ "$did" = 1 ]; then ok "stopped"; else info "nothing tracked to stop (ports freed if held)"; fi
}

status() {
  _report() {
    local name="$1" pf="$2" port="$3" url="$4"
    if pidfile_alive "$pf" || port_busy "$port"; then
      ok "$name running  → $url"
    else
      warn "$name stopped"
    fi
  }
  _report "backend " "$BACK_PIDFILE"  "$BACK_PORT"  "http://$HOST:$BACK_PORT"
  _report "frontend" "$FRONT_PIDFILE" "$FRONT_PORT" "http://localhost:$FRONT_PORT"
}

logs() {
  [ -f "$LOG_DIR/backend.log" ] || [ -f "$LOG_DIR/frontend.log" ] || die "no logs yet — run 'corpus start' first"
  info "tailing .run/logs/*.log (Ctrl-C to stop)"
  tail -n 40 -F "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log" 2>/dev/null
}

usage() {
  cat <<'EOF'
corpus — dev / release launcher for Corpus2Node (FastAPI backend + React/Vite frontend)

  corpus            same as `corpus dev`
  corpus dev        run both in the FOREGROUND with reload/HMR; Ctrl-C stops both  (debugging)
  corpus start      run both in the BACKGROUND (logs to .run/logs); survives terminal close  (release)
  corpus stop|end   stop the background servers
  corpus restart    stop then start (background)
  corpus status     show what's running
  corpus logs       tail the background logs
  corpus help       this message

Env overrides: CORPUS_HOST, CORPUS_BACKEND_PORT, CORPUS_FRONTEND_PORT
EOF
}

# ── dispatch ──────────────────────────────────────────────────────────────────
case "${1:-dev}" in
  dev|"")        dev ;;
  start|up)      start ;;
  stop|end|down) stop ;;
  restart)       stop; start ;;
  status|ps)     status ;;
  logs|log)      logs ;;
  help|-h|--help) usage ;;
  *) die "unknown command '$1' — try 'corpus help'" ;;
esac
