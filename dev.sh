#!/usr/bin/env bash
# Launch the dev stack: API, Celery worker + beat, Flower, frontend.
# Assumes Postgres is running and backend/.env is configured.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Load the approved local environment even when the shell has no direnv hook.
if [[ -f "$ROOT/.envrc" ]] && command -v direnv >/dev/null 2>&1; then
  DIRENV_EXPORT="$(cd "$ROOT" && direnv export bash)"
  eval "$DIRENV_EXPORT"
  unset DIRENV_EXPORT
fi

# The Python environment uv manages: .venv in the repo, or wherever UV_PROJECT_ENVIRONMENT points
# (useful when the checkout lives in a synced folder such as Dropbox).
VENV_DIR="${VENV_DIR:-${UV_PROJECT_ENVIRONMENT:-$ROOT/.venv}}"
VENV="${VENV:-$VENV_DIR/bin}"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$VENV_DIR}"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${API_PORT:-18020}"
FRONTEND_PORT="${FRONTEND_PORT:-25183}"
FLOWER_PORT="${FLOWER_PORT:-15565}"
OPEN_BROWSER="${OPEN_BROWSER:-1}"
PRIVATE_REDIS_PORT="${PRIVATE_REDIS_PORT:-}"

if [[ ! -x "$VENV/python" ]]; then
  echo "Python environment not found at $VENV." >&2
  echo "Create it with: uv sync --locked (or set UV_PROJECT_ENVIRONMENT to use another location)" >&2
  exit 1
fi

FLOWER_BASIC_AUTH="${FLOWER_BASIC_AUTH:-$(cd "$BACKEND" && "$VENV/python" -c 'import os; from dotenv import dotenv_values; print(os.environ.get("FLOWER_BASIC_AUTH") or dotenv_values(".env").get("FLOWER_BASIC_AUTH") or "")')}"

# Runtime files (beat schedule, Flower's task history, the private Redis log) in a directory only this
# user can read: Flower keeps task results, which include account ids and sync reports.
RUNTIME_DIR="${RUNTIME_DIR:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/returns-portal-$(id -u)}"
mkdir -p "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"
PRIVATE_REDIS_LOG="${PRIVATE_REDIS_LOG:-$RUNTIME_DIR/redis.log}"

# Each service runs in its own session and process group, so stopping it also stops its children.
# macOS has no setsid command; Python's os.setsid does the same.
if command -v setsid >/dev/null 2>&1; then
  NEW_SESSION=(setsid)
else
  NEW_SESSION=("$VENV/python" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])')
fi

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl --silent --fail --output /dev/null "$url"; then
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for $label at $url" >&2
  return 1
}

open_browser() {
  local url="$1"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
  elif command -v sensible-browser >/dev/null 2>&1; then
    sensible-browser "$url" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 &
  else
    echo "No browser opener found; open $url manually." >&2
  fi
}

configured_redis_url() {
  ( cd "$BACKEND" && "$VENV/python" -c 'from app.config import settings; print(settings.celery_broker_url)' )
}

redis_ping() {
  local url="$1"
  "$VENV/python" - "$url" <<'PYREDIS' >/dev/null 2>&1
import sys
from redis import Redis

Redis.from_url(sys.argv[1], socket_connect_timeout=1, socket_timeout=1).ping()
PYREDIS
}

free_tcp_port() {
  "$VENV/python" - <<'PYPORT'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PYPORT
}

ensure_redis() {
  local redis_url
  redis_url="$(configured_redis_url)"
  if redis_ping "$redis_url"; then
    return
  fi

  if ! command -v redis-server >/dev/null 2>&1; then
    echo "Redis is not reachable at the configured Celery broker URL." >&2
    echo "Start Redis or fix backend/.env REDIS_* settings, then rerun ./dev.sh." >&2
    exit 1
  fi

  PRIVATE_REDIS_PORT="${PRIVATE_REDIS_PORT:-$(free_tcp_port)}"
  echo "-> Configured Redis is unavailable; starting private Redis on localhost:$PRIVATE_REDIS_PORT"
  "${NEW_SESSION[@]}" redis-server --bind 127.0.0.1 --port "$PRIVATE_REDIS_PORT" --save "" --appendonly no --daemonize no >"$PRIVATE_REDIS_LOG" 2>&1 &
  redis_pid=$!
  pids+=("$redis_pid")

  export REDIS_PROTOCOL="redis://"
  export REDIS_HOST="127.0.0.1"
  export REDIS_PORT="$PRIVATE_REDIS_PORT"
  export REDIS_USERNAME=""
  export REDIS_PASSWORD=""
  export REDIS_CONNECTION_PARAMS=""
  export REDIS_DATABASE="${REDIS_DATABASE:-0}"

  redis_url="$(configured_redis_url)"
  for _ in $(seq 1 40); do
    if redis_ping "$redis_url"; then
      return
    fi
    sleep 0.25
  done

  echo "Private Redis did not become ready; see $PRIVATE_REDIS_LOG." >&2
  exit 1
}

pids=()
api_pid=""
worker_pid=""
beat_pid=""
flower_pid=""
frontend_pid=""
redis_pid=""
cleaned_up=0

stop_group() {
  local signal="$1"
  local pid="$2"
  if [[ -z "$pid" ]]; then
    return
  fi
  kill "-$signal" -- "-$pid" 2>/dev/null || kill "-$signal" "$pid" 2>/dev/null || true
}

wait_for_groups() {
  local timeout="$1"
  shift
  local pid
  for _ in $(seq 1 "$timeout"); do
    local running=0
    for pid in "$@"; do
      if [[ -n "$pid" ]] && kill -0 -- "-$pid" 2>/dev/null; then
        running=1
      fi
    done
    if [[ "$running" == "0" ]]; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

cleanup() {
  if [[ "$cleaned_up" == "1" ]]; then
    return
  fi
  cleaned_up=1
  echo
  echo "Stopping dev stack..."
  stop_group INT "$flower_pid"
  stop_group TERM "$frontend_pid"
  stop_group TERM "$api_pid"
  stop_group TERM "$beat_pid"
  stop_group TERM "$worker_pid"

  wait_for_groups 50 "$flower_pid" "$frontend_pid" "$api_pid" "$beat_pid" "$worker_pid" || true

  stop_group TERM "$redis_pid"
  wait_for_groups 25 "$redis_pid" || true

  for pid in ${pids[@]+"${pids[@]}"}; do stop_group KILL "$pid"; done
  for pid in ${pids[@]+"${pids[@]}"}; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

echo "-> Applying migrations"
export DATABASE_URL="$(cd "$BACKEND" && "$VENV/python" -c 'from app.config import settings; print(settings.database_url)')"
if [[ -z "$DATABASE_URL" ]]; then
  echo "DATABASE_URL is empty; check backend/.env or app.config settings." >&2
  exit 1
fi
( cd "$BACKEND" && dbmate --no-dump-schema up )
echo "-> Applying SQL functions"
( cd "$BACKEND" && "$VENV/python" scripts/apply_db_functions.py )

ensure_redis

echo "-> API on :$API_PORT"
( cd "$BACKEND" && exec "${NEW_SESSION[@]}" env APP_ENV="${APP_ENV:-development}" "$VENV/uvicorn" app.api:app --host 127.0.0.1 --port "$API_PORT" --reload --no-access-log ) & api_pid=$!; pids+=("$api_pid")

echo "-> Celery worker"
( cd "$BACKEND" && exec "${NEW_SESSION[@]}" "$VENV/celery" -A app.celery_app worker --loglevel=info ) & worker_pid=$!; pids+=("$worker_pid")

echo "-> Celery beat"
( cd "$BACKEND" && exec "${NEW_SESSION[@]}" "$VENV/celery" -A app.celery_app beat --loglevel=info --schedule="$RUNTIME_DIR/celerybeat-schedule" ) & beat_pid=$!; pids+=("$beat_pid")

echo "-> Flower on localhost:$FLOWER_PORT"
# Flower can revoke tasks and shut workers down, and any web page can reach a localhost port, so it
# always gets a password: FLOWER_BASIC_AUTH, or a random one for this run (printed below).
FLOWER_PASSWORD_NOTE=""
if [[ -z "$FLOWER_BASIC_AUTH" ]]; then
  FLOWER_BASIC_AUTH="flower:$("$VENV/python" -c 'import secrets; print(secrets.token_urlsafe(12))')"
  FLOWER_PASSWORD_NOTE=" (user flower, password ${FLOWER_BASIC_AUTH#flower:})"
fi
( cd "$BACKEND" && exec "${NEW_SESSION[@]}" env FLOWER_BASIC_AUTH="$FLOWER_BASIC_AUTH" "$VENV/celery" -A app.celery_app flower --address=127.0.0.1 --port="$FLOWER_PORT" --url-prefix=flower --persistent=True --db="$RUNTIME_DIR/flower.db" ) & flower_pid=$!; pids+=("$flower_pid")

echo "-> Frontend SSR on :$FRONTEND_PORT"
( cd "$FRONTEND" && exec "${NEW_SESSION[@]}" env API_PORT="$API_PORT" API_ORIGIN="http://127.0.0.1:$API_PORT" FRONTEND_PORT="$FRONTEND_PORT" FLOWER_PORT="$FLOWER_PORT" npm run dev ) & frontend_pid=$!; pids+=("$frontend_pid")

echo
echo "Stack up: API http://localhost:$API_PORT | UI http://localhost:$FRONTEND_PORT | Flower http://localhost:$FRONTEND_PORT/flower/$FLOWER_PASSWORD_NOTE"
echo "Ctrl-C to stop."

echo "-> Queuing startup market-data refresh (FX, prices, then PnL)"
if ! ( cd "$BACKEND" && "$VENV/python" scripts/refresh_market_data.py ); then
  echo "Startup market-data refresh could not be queued; reports may be stale. Retry with backend/scripts/refresh_market_data.py." >&2
fi

if [[ "$OPEN_BROWSER" != "0" ]]; then
  ui_url="http://localhost:$FRONTEND_PORT/"
  if wait_for_url "http://localhost:$API_PORT/api/health/live" "API" && wait_for_url "$ui_url" "frontend"; then
    echo "-> Opening $ui_url"
    open_browser "$ui_url"
  fi
fi

wait
