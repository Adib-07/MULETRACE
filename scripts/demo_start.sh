#!/usr/bin/env bash
# Start the MuleTrace demo on the VM: stop old server, fresh alerts.db, uvicorn on 127.0.0.1:8000 in tmux "mt".
# Token comes from ~/.muletrace.env (outside the repo, mode 600). --rotate-token writes a new one first.
# Usage (on the VM, from anywhere): bash ~/muletrace/scripts/demo_start.sh [--rotate-token]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${MULETRACE_ENV_FILE:-$HOME/.muletrace.env}"
VENV="${MULETRACE_VENV:-$HOME/venv}"

if [ "${1:-}" = "--rotate-token" ] || [ ! -s "$ENV_FILE" ]; then
  ( umask 077; echo "MULETRACE_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > "$ENV_FILE" )
  echo "new token written to $ENV_FILE"
fi
chmod 600 "$ENV_FILE"

tmux kill-session -t mt 2>/dev/null || true
tmux kill-session -t api 2>/dev/null || true          # older session name
sleep 1
rm -f "$REPO/alerts.db" "$REPO/alerts.db-wal" "$REPO/alerts.db-shm"

tmux new -d -s mt "cd '$REPO' && set -a && . '$ENV_FILE' && set +a && . '$VENV/bin/activate' && python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 2>&1 | tee -a '$REPO/server.log'"

for _ in $(seq 1 90); do
  if curl -s -m 2 http://127.0.0.1:8000/health >/dev/null; then
    echo "MuleTrace up: $(curl -s http://127.0.0.1:8000/health) (tmux session 'mt', 127.0.0.1:8000, fresh alerts.db)"
    echo "token: see $ENV_FILE (not printed)"
    exit 0
  fi
  sleep 1
done
echo "server did not answer /health within 90 s; see: tmux attach -t mt" >&2
exit 1
