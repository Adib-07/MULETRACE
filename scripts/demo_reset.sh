#!/usr/bin/env bash
# Reset the demo: empty case queue and audit log, stream back at the start of the test set. Keeps the token.
exec bash "$(dirname "$0")/demo_start.sh"
