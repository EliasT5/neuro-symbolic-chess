#!/bin/bash
# wait_turn.sh — efficient bash polling loop.
#
# Blocks until /tmp/active_game.json indicates it is COLOR's turn,
# burning shell-only cycles (no LLM tokens). Polling interval 2 s.
#
# Usage:   wait_turn.sh white   |   wait_turn.sh black
#
# Exit codes:
#   0 — your turn (prints "YOUR_TURN" to stdout)
#   1 — game complete (prints "GAME_COMPLETE")
#   2 — 30-minute timeout (prints "TIMEOUT")
#   99 — usage error

set -u

COLOR="${1:-}"
case "$COLOR" in
  white|black) ;;
  *) echo "usage: wait_turn.sh white|black" >&2; exit 99 ;;
esac

ACTIVE_FILE=/tmp/active_game.json
DEADLINE=$(($(date +%s) + 1800))   # 30 minutes
POLL_INTERVAL=2

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    if [ ! -f "$ACTIVE_FILE" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi
    STATUS=$(jq -r '.status // ""' "$ACTIVE_FILE" 2>/dev/null)
    if [ "$STATUS" = "complete" ]; then
        echo "GAME_COMPLETE"
        exit 1
    fi
    SIDE=$(jq -r '.side_to_move // ""' "$ACTIVE_FILE" 2>/dev/null)
    if [ "$SIDE" = "$COLOR" ]; then
        echo "YOUR_TURN"
        exit 0
    fi
    sleep "$POLL_INTERVAL"
done
echo "TIMEOUT"
exit 2
