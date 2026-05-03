#!/opt/jerome-workspaces/1225610b9511/repo/.venv/bin/python
"""
Roll up the completed /tmp/active_game.json into a permanent record:
appends to data/tournament/games.json and updates the players' Elo
+ W/D/L counters in data/tournament/players.json.

Run after a game completes (status == "complete"). Will refuse to run
on an in-progress game.

Usage:
    finalize_active_game.py [--archive]

If --archive is given, the active file is renamed to
/tmp/active_game.<game_id>.json after success rather than left in
place, so the next game can start cleanly.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "llm-engine"))

from engine.tournament import GameSession, SideStats, finalize_and_persist

ACTIVE_FILE = Path("/tmp/active_game.json")


def _stats_from_dict(d: dict) -> SideStats:
    return SideStats(
        moves=d.get("moves", 0),
        illegal_moves=d.get("illegal_moves", 0),
        fallbacks=d.get("fallbacks", 0),
        tokens=d.get("tokens", 0),
        cost=d.get("cost", 0.0),
        total_latency_ms=d.get("total_latency_ms", 0),
        rationales=d.get("rationales", []),
        thinking_blocks=d.get("thinking_blocks", []),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()

    if not ACTIVE_FILE.exists():
        print(f"ERROR: {ACTIVE_FILE} does not exist", file=sys.stderr)
        sys.exit(1)

    state = json.loads(ACTIVE_FILE.read_text())
    if state.get("status") != "complete":
        print(f"ERROR: game still in progress (status={state.get('status')})", file=sys.stderr)
        sys.exit(2)

    sess = GameSession(
        game_id=state["game_id"],
        white_key=state["white_key"],
        black_key=state["black_key"],
        started_at=state["started_at"],
        initial_fen=state["initial_fen"],
        moves=state["moves"],
        fens=state["fens"],
        move_records=state["move_records"],
        white_stats=_stats_from_dict(state["white_stats"]),
        black_stats=_stats_from_dict(state["black_stats"]),
    )

    record = finalize_and_persist(
        sess,
        result=state["result"],
        termination=state["termination"],
        repo_root=REPO,
    )

    print(f"Persisted game {record['id']}")
    print(f"  result      : {record['result']} ({record['termination']})")
    print(f"  elo_before  : {record['elo_before']}")
    print(f"  elo_after   : {record['elo_after']}")
    print(f"  delta       : {record['elo_delta']}")
    print(f"  moves       : {len(record['moves'])}  ({record['opening']})")

    if args.archive:
        archive_path = ACTIVE_FILE.with_name(f"active_game.{state['game_id']}.json")
        shutil.move(str(ACTIVE_FILE), str(archive_path))
        print(f"  archived to : {archive_path}")


if __name__ == "__main__":
    main()
