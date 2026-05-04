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
# This sidesteps the agentic-loop fragility of small CLIs (model-g
# lite-g Lite, etc.) — the loop lives in shell where it cannot fail
# to comply.
#
# Usage:
#     agent_loop.sh white  model-c lite-c
#     agent_loop.sh black  model-g model-g-2.5-lite-g-lite
#     agent_loop.sh white  model-x  model-o-5.4-mini
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

# Try to parse a {"move": "...", "why": "..."} object out of the response.
# Echoes "MOVE\tWHY" on success; empty string on failure.
extract_json() {
    # Pull the first {...} block (handles code fences + surrounding prose)
    local json
    json=$(echo "$1" | tr -d '\r' | grep -oE '\{[^{}]*\}' | head -1)
    [ -n "$json" ] || { echo ""; return; }
    local m w
    m=$(printf %s "$json" | jq -r '.move // .san // empty' 2>/dev/null)
    w=$(printf %s "$json" | jq -r '.why  // .rationale // .reason // empty' 2>/dev/null)
    [ -n "$m" ] || { echo ""; return; }
    # Tab-separated; reasoning may contain spaces but should not contain tabs
    printf '%s\t%s' "$m" "$w"
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

    PROMPT="You are playing chess as $COLOR. Reply with COMPACT JSON only — no code fences, no prose around it:

{\"move\": \"<your SAN move>\", \"why\": \"<one short sentence explaining the move>\"}

Position FEN: $FEN
Recent moves: ${REC:-(start of game)}
Legal moves available to you: $LGL"

    log "polling $CLI($MODEL) for move at FEN=$FEN"

    case "$CLI" in
      model-c) RAW=$("$CLI" -p "$PROMPT" --model "$MODEL" --dangerously-skip-permissions 2>>"$LOG") ;;
      model-g) RAW=$("$CLI" -p "$PROMPT" -m    "$MODEL" --yolo                          2>>"$LOG") ;;
      model-x)  RAW=$("$CLI" exec --model "$MODEL" "$PROMPT"                              2>>"$LOG") ;;
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

    # Prefer JSON parse so we capture the model's stated reasoning.
    JSON_PARSED=$(extract_json "$RAW")
    if [ -n "$JSON_PARSED" ]; then
        MOVE=$(printf %s "$JSON_PARSED" | cut -f1)
        WHY=$( printf %s "$JSON_PARSED" | cut -f2)
        log "json: move=$MOVE  why=$(printf %s "$WHY" | head -c 160)"
    else
        # Legacy fallback: model didn't return JSON. Pull a SAN token; mark rationale missing.
        MOVE=$(extract_move "$RAW")
        WHY="(no rationale; model did not return JSON)"
        log "no-json fallback: extracted=$MOVE"
    fi

    if [ -z "$MOVE" ]; then
        log "ERROR: could not extract SAN from response → fallback to random legal"
        MOVE=$(random_legal)
        "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" --fallback --rationale "unparseable CLI output" 2>>"$LOG"
        continue
    fi

    SUCCESS=0
    for ATTEMPT in 1 2 3; do
        if "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" --rationale "$WHY" 2>>"$LOG"; then
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
