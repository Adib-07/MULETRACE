#!/usr/bin/env bash
# Public judge demo: a SEPARATE MuleTrace instance in judge mode (127.0.0.1:8100, own demo DB) behind Caddy (HTTPS).
# The admin app on 127.0.0.1:8000 is untouched and never proxied.
#   bash scripts/public_start.sh --app-only   start/restart only the public instance (no ports opened)
#   bash scripts/public_start.sh              public instance + Caddy (needs ports 80/443 open and cap_net_bind_service)
#   bash scripts/public_start.sh --check      health of both, no changes
# Config: ~/.muletrace.env (admin token, as for demo_start.sh) and ~/.muletrace-public.env with MULETRACE_HOST=<host>.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${MULETRACE_VENV:-$HOME/venv}"; CADDY="${CADDY:-$HOME/bin/caddy}"
ENV_FILE="${MULETRACE_ENV_FILE:-$HOME/.muletrace.env}"; PUB_ENV="${MULETRACE_PUBLIC_ENV:-$HOME/.muletrace-public.env}"
PORT=8100; DB="$REPO/alerts-public.db"; LOGDIR="$HOME/muletrace-public"; mkdir -p "$LOGDIR"
MODE="${1:-all}"

health() { curl -s -m 3 "http://127.0.0.1:$PORT/health" >/dev/null; }
if [ "$MODE" = "--check" ]; then
  echo "public instance: $(health && echo up || echo DOWN)"
  if [ -s "$PUB_ENV" ]; then . "$PUB_ENV"; echo "https://$MULETRACE_HOST/health -> $(curl -s -m 8 -o /dev/null -w %{http_code} "https://$MULETRACE_HOST/health" || true)"; fi
  exit 0
fi
[ -s "$ENV_FILE" ] || { echo "missing $ENV_FILE (run scripts/demo_start.sh once)" >&2; exit 1; }

tmux kill-session -t pub 2>/dev/null || true
tmux new -d -s pub "cd '$REPO' && set -a && . '$ENV_FILE' && set +a && . '$VENV/bin/activate' && \
  MULETRACE_PUBLIC_DEMO=1 MULETRACE_TRUST_PROXY=1 MULETRACE_DB='$DB' \
  python -m uvicorn api.main:app --host 127.0.0.1 --port $PORT --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1 2>&1 | tee -a '$LOGDIR/app.log'"
for _ in $(seq 1 90); do health && break; sleep 1; done
health || { echo "public instance did not start; see: tmux attach -t pub" >&2; exit 1; }
echo "public instance up on 127.0.0.1:$PORT (judge mode, DB $DB)"
[ "$MODE" = "--app-only" ] && exit 0

[ -s "$PUB_ENV" ] || { echo "missing $PUB_ENV with MULETRACE_HOST=<host>" >&2; exit 1; }
[ -x "$CADDY" ] || { echo "missing $CADDY" >&2; exit 1; }
tmux kill-session -t caddy 2>/dev/null || true
tmux new -d -s caddy "set -a && . '$PUB_ENV' && set +a && HOME='$HOME' '$CADDY' run --config '$REPO/deploy/Caddyfile' --adapter caddyfile 2>&1 | tee -a '$LOGDIR/caddy.log'"
. "$PUB_ENV"
for _ in $(seq 1 60); do curl -s -m 5 -o /dev/null "https://$MULETRACE_HOST/health" && break; sleep 2; done
echo "https://$MULETRACE_HOST/health -> $(curl -s -m 8 -o /dev/null -w %{http_code} "https://$MULETRACE_HOST/health" || true)"
