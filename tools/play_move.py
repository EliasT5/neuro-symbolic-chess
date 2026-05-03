#!/opt/jerome-workspaces/1225610b9511/repo/.venv/bin/python
"""
Atomically apply a chess move to /tmp/active_game.json.

Used by both the white CLI and the black CLI as their ONLY way to
update game state. This is the single chokepoint where:
    - move legality is verified (chess_core.guardrails)
    - per-side stats are incremented
    - terminal-position detection runs
    - the active state file is rewritten atomically (tmp + rename)
    - cross-process safety is enforced via fcntl.LOCK_EX

Usage:
    play_move.py --color white --san "e4" --rationale "central"
    play_move.py --color black --san "e5" --rationale "central response"
    play_move.py --color white --san "Nf3" --fallback        # marks as random fallback
    play_move.py --color white --san "..." --thinking "..."  # captures reasoning

Exit codes:
    0 — move applied (status field will say if game terminated)
    2 — illegal/unparseable move (alternatives printed to stderr)
    3 — not your turn
    4 — game already complete
    5 — file lock acquisition timed out
    6 — active game file does not exist
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import chess
from chess_core import guardrails

ACTIVE_FILE = Path("/tmp/active_game.json")
LOCK_FILE = Path("/tmp/active_game.json.lock")
LOCK_TIMEOUT_S = 30


def _terminal(board: chess.Board):
    if board.is_checkmate():
        return ("0-1" if board.turn == chess.WHITE else "1-0", "checkmate")
    if board.is_stalemate():
        return ("1/2-1/2", "stalemate")
    if board.is_insufficient_material():
        return ("1/2-1/2", "insufficient_material")
    if board.is_fivefold_repetition():
        return ("1/2-1/2", "fivefold_repetition")
    if board.is_seventyfive_moves():
        return ("1/2-1/2", "seventyfive_move_rule")
    if board.can_claim_threefold_repetition():
        return ("1/2-1/2", "threefold_repetition")
    if board.can_claim_fifty_moves():
        return ("1/2-1/2", "fifty_move_rule")
    return None


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.rename(path)


def _acquire_lock(path: Path, timeout_s: float):
    fp = open(path, "w")
    deadline = time.time() + timeout_s
    while True:
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fp
        except BlockingIOError:
            if time.time() > deadline:
                fp.close()
                return None
            time.sleep(0.1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--color", required=True, choices=["white", "black"])
    parser.add_argument("--san", required=True)
    parser.add_argument("--rationale", default="")
    parser.add_argument("--thinking", default="")
    parser.add_argument("--fallback", action="store_true")
    args = parser.parse_args()

    if not ACTIVE_FILE.exists():
        print(f"ERROR: {ACTIVE_FILE} does not exist (init_active_game.py first)", file=sys.stderr)
        sys.exit(6)

    lock = _acquire_lock(LOCK_FILE, LOCK_TIMEOUT_S)
    if lock is None:
        print("ERROR: lock timeout", file=sys.stderr)
        sys.exit(5)

    try:
        state = json.loads(ACTIVE_FILE.read_text())

        if state["status"] == "complete":
            print(f"GAME ALREADY COMPLETE — result {state['result']} ({state['termination']})", file=sys.stderr)
            sys.exit(4)

        if state["side_to_move"] != args.color:
            print(f"NOT YOUR TURN — side_to_move={state['side_to_move']}, you sent {args.color}", file=sys.stderr)
            sys.exit(3)

        result = guardrails.apply_move(state["fen"], args.san)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if not result.get("ok"):
            alt = ", ".join(a["san"] for a in result.get("alternatives", []))
            print(f"ILLEGAL: {result.get('reason')}", file=sys.stderr)
            print(f"ALTERNATIVES: {alt}", file=sys.stderr)
            state["error_log"].append({
                "timestamp": now,
                "color": args.color,
                "attempted_san": args.san,
                "reason": result.get("reason"),
            })
            state[f"{args.color}_stats"]["illegal_moves"] += 1
            state["last_update"] = now
            _atomic_write(ACTIVE_FILE, state)
            sys.exit(2)

        # Apply the move
        new_fen = result["fen_after"]
        board = chess.Board(new_fen)
        new_side = "white" if board.turn == chess.WHITE else "black"
        legal_san = [board.san(m) for m in board.legal_moves]

        state["fen"] = new_fen
        state["moves"].append(result["san"])
        state["fens"].append(new_fen)
        state["side_to_move"] = new_side
        state["legal_moves_san"] = legal_san
        state["last_update"] = now

        state["move_records"].append({
            "ply": len(state["moves"]),
            "side": args.color,
            "san": result["san"],
            "uci": result["uci"],
            "fen_after": new_fen,
            "status": result["status"],
            "rationale": args.rationale,
            "thinking": args.thinking,
            "fallback": args.fallback,
            "timestamp": now,
        })

        stats = state[f"{args.color}_stats"]
        stats["moves"] += 1
        if args.fallback:
            stats["fallbacks"] += 1

        terminal = _terminal(board)
        if terminal:
            res, why = terminal
            state["status"] = "complete"
            state["result"] = res
            state["termination"] = why
            _atomic_write(ACTIVE_FILE, state)
            print(f"GAME COMPLETE — {res} ({why}); played {result['san']}")
            return

        _atomic_write(ACTIVE_FILE, state)
        print(f"OK — {args.color} played {result['san']}; next: {new_side}")

    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    main()
