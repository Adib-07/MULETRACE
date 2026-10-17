#!/usr/bin/env bash
# Reboot resilience without sudo: a user crontab @reboot entry that restarts the demo keeping alerts.db.
#   bash scripts/autostart.sh            show what would be installed (no changes)
#   bash scripts/autostart.sh --apply    add it to this user's crontab (idempotent)
#   bash scripts/autostart.sh --remove   remove it
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LINE="@reboot sleep 20 && bash $REPO/scripts/demo_start.sh --keep-db >> $REPO/autostart.log 2>&1 && bash $REPO/scripts/public_start.sh >> $REPO/autostart.log 2>&1 # muletrace-autostart"
case "${1:-}" in
  --apply)  ( crontab -l 2>/dev/null | grep -v "# muletrace-autostart" || true; echo "$LINE" ) | crontab -; echo "installed:"; crontab -l | grep muletrace-autostart ;;
  --remove) ( crontab -l 2>/dev/null | grep -v "# muletrace-autostart" || true ) | crontab -; echo "removed" ;;
  *)        echo "would install (run with --apply):"; echo "$LINE" ;;
esac
