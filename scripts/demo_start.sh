#!/usr/bin/env bash
# Start the MuleTrace demo on the VM: stop old server, fresh alerts.db, uvicorn on 127.0.0.1:8000 in tmux "mt".
# Token comes from ~/.muletrace.env (outside the repo, mode 600). --rotate-token writes a new one first.
# --keep-db restarts without wiping alerts.db (alerts and audit log persist).
# --env-only writes/rotates the env file and exits (used by tests).
# Usage (on the VM, from anywhere): bash ~/muletrace/scripts/demo_start.sh [--rotate-token] [--keep-db] [--env-only]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${MULETRACE_ENV_FILE:-$HOME/.muletrace.env}"
VENV="${MULETRACE_VENV:-$HOME/venv}"

ROTATE=0; KEEP=0; ENV_ONLY=0
for a in "$@"; do case "$a" in --rotate-token) ROTATE=1;; --keep-db) KEEP=1;; --env-only) ENV_ONLY=1;; *) echo "unknown option $a" >&2; exit 2;; esac; done
if [ "$ROTATE" = 1 ] || [ ! -s "$ENV_FILE" ]; then
  # plain KEY=value, no quotes, no `export`, one line: the format the console and `cut -d= -f2` expect
  ( umask 077; printf 'MULETRACE_TOKEN=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > "$ENV_FILE" )
  echo "new token written to $ENV_FILE"
fi
chmod 600 "$ENV_FILE"
if [ "$ENV_ONLY" = 1 ]; then echo "token file: $ENV_FILE (read it with: cut -d= -f2 $ENV_FILE)"; exit 0; fi

tmux kill-session -t mt 2>/dev/null || true
tmux kill-session -t api 2>/dev/null || true          # older session name
sleep 1
if [ "$KEEP" = 0 ]; then rm -f "$REPO/alerts.db" "$REPO/alerts.db-wal" "$REPO/alerts.db-shm"; fi

tmux new -d -s mt "cd '$REPO' && set -a && . '$ENV_FILE' && set +a && . '$VENV/bin/activate' && python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-access-log 2>&1 | tee -a '$REPO/server.log'"

for _ in $(seq 1 90); do
  if curl -s -m 2 http://127.0.0.1:8000/health >/dev/null; then
    echo "MuleTrace up: $(curl -s http://127.0.0.1:8000/health) (tmux session 'mt', 127.0.0.1:8000, $([ "$KEEP" = 1 ] && echo "alerts.db kept" || echo "fresh alerts.db"))"
    echo "token (not printed): run  cut -d= -f2 $ENV_FILE  on the VM"
    exit 0
  fi
  sleep 1
done
echo "server did not answer /health within 90 s; see: tmux attach -t mt" >&2
exit 1
