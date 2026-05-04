#!/opt/jerome-workspaces/1225610b9511/repo/.venv/bin/python
"""
Initialize /tmp/active_game.json for a new tournament game.

Both side-agents (white CLI, black CLI) will read and write this file
through `play_move.py`; nothing else should touch it directly.

Usage:
    init_active_game.py --white-key model-c-code-lite-c@base \
                        --black-key model-g-cli-lite-g@base \
                        [--game-id g-001]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import chess

ACTIVE_FILE = Path("/tmp/active_game.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--white-key", required=True)
    parser.add_argument("--black-key", required=True)
    parser.add_argument("--game-id", default=None)
    args = parser.parse_args()

    gid = args.game_id or f"g-{int(time.time())}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    initial_fen = chess.STARTING_FEN

    # Pre-render legal moves at the starting position so agents have them
    # ready without having to import chess themselves.
    board = chess.Board(initial_fen)
    legal_san = [board.san(m) for m in board.legal_moves]

    state = {
        "game_id": gid,
        "white_key": args.white_key,
        "black_key": args.black_key,
        "started_at": now,
        "initial_fen": initial_fen,
        "fen": initial_fen,
        "side_to_move": "white",
        "legal_moves_san": legal_san,
        "moves": [],
        "fens": [],
        "move_records": [],
        "white_stats": {"moves": 0, "illegal_moves": 0, "fallbacks": 0},
        "black_stats": {"moves": 0, "illegal_moves": 0, "fallbacks": 0},
        "status": "in_progress",
        "result": None,
        "termination": None,
        "last_update": now,
        "error_log": [],
    }

    tmp = ACTIVE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(ACTIVE_FILE)

    print(f"Initialised {ACTIVE_FILE}")
    print(f"  game_id     : {gid}")
    print(f"  white       : {args.white_key}")
    print(f"  black       : {args.black_key}")
    print(f"  side_to_move: white")
    print(f"  legal moves : {', '.join(legal_san)}")


if __name__ == "__main__":
    main()
