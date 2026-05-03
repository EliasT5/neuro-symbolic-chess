#!/bin/bash
# tools/agent_loop.sh — bash-driven outer loop for tournament agents.
#
# Each iteration:
#   1. Block on wait_turn.sh (pure bash — no LLM tokens while waiting).
#   2. Build a tight per-move prompt from the active state.
#   3. Invoke <CLI> -p with --model <MODEL> for ONE move.
#   4. Parse the CLI's reply for the first SAN-shaped token.
#   5. Apply via play_move.py with up to 3 retries; on persistent
#      failure, fall back to a random legal move (stats-marked).
#
# This sidesteps the agentic-loop fragility of small CLIs (Gemini
# Flash Lite, etc.) — the loop lives in shell where it cannot fail
# to comply.
#
# Usage:
#     agent_loop.sh white  claude haiku
#     agent_loop.sh black  gemini gemini-2.5-flash-lite
#     agent_loop.sh white  codex  gpt-5.4-mini
#
# Logs are appended to /tmp/nsc-logs/<color>.log

set -u

COLOR="${1:-}"
CLI="${2:-}"
MODEL="${3:-}"
case "$COLOR" in white|black) ;; *) echo "usage: agent_loop.sh white|black <cli> <model>" >&2; exit 99 ;; esac

TOOLS=/opt/jerome-workspaces/1225610b9511/repo/tools
ACTIVE=/tmp/active_game.json
LOG_DIR=/tmp/nsc-logs
LOG="$LOG_DIR/${COLOR}.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

extract_move() {
    # First SAN-shaped token in the response.
    echo "$1" | grep -oE '[NBRQK]?[a-h]?[1-8]?x?[a-h][1-8](=[NBRQ])?[+#]?|O-O(-O)?' | head -1
}

random_legal() {
    local count
    count=$(jq '.legal_moves_san | length' "$ACTIVE")
    [ "$count" -gt 0 ] || { echo ""; return; }
    jq -r ".legal_moves_san[$((RANDOM % count))]" "$ACTIVE"
}

log "─── agent_loop start: color=$COLOR cli=$CLI model=$MODEL ───"

while true; do
    "$TOOLS/wait_turn.sh" "$COLOR" >/dev/null
    case $? in
      0) ;;
      1) log "GAME_COMPLETE — exiting cleanly"; exit 0 ;;
      2) log "TIMEOUT (30 min) — exiting"; exit 1 ;;
      *) log "wait_turn.sh unknown exit"; exit 2 ;;
    esac

    FEN=$(jq -r .fen "$ACTIVE")
    REC=$(jq -r '.moves[-12:] | join(" ")' "$ACTIVE")
    LGL=$(jq -r '.legal_moves_san | join(", ")' "$ACTIVE")

    PROMPT="You are playing chess as $COLOR. Output ONLY your move in SAN notation — one token, no prose, no JSON, nothing else.

Position FEN: $FEN
Recent moves: ${REC:-(start of game)}
Legal moves available to you: $LGL

Your move:"

    log "polling $CLI($MODEL) for move at FEN=$FEN"

    case "$CLI" in
      claude) RAW=$("$CLI" -p "$PROMPT" --model "$MODEL" --dangerously-skip-permissions 2>>"$LOG") ;;
      gemini) RAW=$("$CLI" -p "$PROMPT" -m    "$MODEL" --yolo                          2>>"$LOG") ;;
      codex)  RAW=$("$CLI" exec --model "$MODEL" "$PROMPT"                              2>>"$LOG") ;;
      *) log "ERROR: unknown CLI '$CLI'"; exit 99 ;;
    esac

    # Truncated raw response for log readability
    log "raw: $(printf %s "$RAW" | head -c 200 | tr '\n' ' ')"

    if [ -z "$RAW" ]; then
        log "ERROR: empty CLI response → fallback to random legal"
        MOVE=$(random_legal)
        "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" --fallback --rationale "empty CLI response" 2>>"$LOG"
        continue
    fi

    MOVE=$(extract_move "$RAW")
    if [ -z "$MOVE" ]; then
        log "ERROR: could not extract SAN from response → fallback to random legal"
        MOVE=$(random_legal)
        "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" --fallback --rationale "unparseable CLI output" 2>>"$LOG"
        continue
    fi

    log "extracted: $MOVE"

    SUCCESS=0
    for ATTEMPT in 1 2 3; do
        if "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" --rationale "agent_loop attempt $ATTEMPT" 2>>"$LOG"; then
            SUCCESS=1
            log "play_move accepted: $MOVE (attempt $ATTEMPT)"
            break
        fi
        EXIT=$?
        case $EXIT in
            4) log "GAME_COMPLETE on play_move"; exit 0 ;;
            3) log "NOT_OUR_TURN — bailing this iteration"; break ;;
            2) log "ILLEGAL ($MOVE) attempt $ATTEMPT → trying a different legal move"
               MOVE=$(random_legal) ;;
            *) log "play_move unexpected exit $EXIT — bailing"; break ;;
        esac
    done

    if [ $SUCCESS -eq 0 ]; then
        log "WARN: 3 attempts failed → forcing random-legal fallback"
        MOVE=$(random_legal)
        "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" --fallback --rationale "3 attempts failed, forced fallback" 2>>"$LOG"
    fi
done
