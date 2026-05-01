"""
Neuro-Symbolic Chess — interactive CLI.

Plays a game between you (the human) and a simulated PlayerProfile.
The simulated side is driven by `NeuroSymbolicEngine`: System 1 (LLM)
intuits a move, the trigger decides whether System 2 (calculator) gets
to look, and the chosen move + rationale + trace are printed.

Usage:
    python llm-engine/main.py --profile data/profiles/aggressive_club.json --side black
    python llm-engine/main.py --profile data/profiles/aggressive_club.json --side white --trace

Without OPENAI_API_KEY set, System 1 falls back to a small heuristic
so the loop is exercisable end-to-end with no external calls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chess

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, ENGINE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from engine import NeuroSymbolicEngine, PlayerProfile  # noqa: E402
from chess_core import guardrails  # noqa: E402


def _print_board(board: chess.Board, *, flip: bool) -> None:
    """ASCII print, oriented for the human's perspective."""
    text = board.unicode(invert_color=False, borders=True)
    if flip:
        text = "\n".join(reversed(text.splitlines()))
    print(text)
    print(f"FEN: {board.fen()}")


def _format_decision(decision, *, trace: bool) -> str:
    head = (
        f"Engine plays {decision.chosen_san}\n"
        f"  rationale: {decision.rationale}\n"
        f"  trigger: P={decision.trigger_probability:.2f} "
        f"(R_T≈{decision.position_difficulty:.0f}) → "
        f"{'FIRED' if decision.trigger_fired else 'skipped'}"
    )
    if not trace:
        return head

    extras = ["  notes:"]
    for n in decision.notes:
        extras.append(f"    - {n}")
    if decision.assessment:
        a = decision.assessment
        extras.append(f"  S2 best={a.best_move_san} ({a.best_score_cp:+d} cp), depth={a.depth}, nodes={a.nodes}")
        for san, cp in a.scored[:5]:
            extras.append(f"    {san}: {cp:+d} cp")
    if decision.proposal.candidates:
        extras.append(f"  S1 candidates: {', '.join(decision.proposal.candidates)}")
    if decision.proposal.used_fallback:
        extras.append("  (S1 fell back to a random legal move — LLM produced no parseable move)")
    return head + "\n" + "\n".join(extras)


def _human_turn(board: chess.Board) -> str:
    while True:
        raw = input("Your move (SAN/UCI, or 'quit'): ").strip()
        if raw.lower() in {"quit", "q", "exit"}:
            sys.exit(0)
        if raw.lower() == "fen":
            print(board.fen())
            continue
        result = guardrails.apply_move(board.fen(), raw)
        if result.get("ok"):
            return result["san"]
        alt = ", ".join(f"{a['san']}" for a in result.get("alternatives", [])[:6])
        print(f"  {result.get('reason', 'illegal move')} Try one of: {alt}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play against a neuro-symbolic chess profile.")
    parser.add_argument("--profile", required=True, help="Path to a PlayerProfile JSON file.")
    parser.add_argument("--side", choices=["white", "black"], default="white", help="Which side YOU play.")
    parser.add_argument("--trace", action="store_true", help="Print full decision trace each move.")
    args = parser.parse_args()

    profile = PlayerProfile.load(args.profile)
    engine = NeuroSymbolicEngine(profile)

    board = chess.Board()
    history: list[str] = []
    human_color = chess.WHITE if args.side == "white" else chess.BLACK
    flip = (args.side == "black")

    print(f"\nNeuro-Symbolic Chess — you are {args.side.upper()} vs {profile.name}")
    print("=" * 60)

    while not board.is_game_over(claim_draw=True):
        _print_board(board, flip=flip)
        if board.turn == human_color:
            san = _human_turn(board)
            board.push_san(san)
            history.append(san)
        else:
            decision = engine.decide(board, history)
            print(_format_decision(decision, trace=args.trace))
            board.push_san(decision.chosen_san)
            history.append(decision.chosen_san)

    _print_board(board, flip=flip)
    print(f"\nResult: {board.result()} ({guardrails.get_game_status(board)})")
    print("PGN:", " ".join(history))


if __name__ == "__main__":
    main()
