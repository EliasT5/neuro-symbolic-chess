"""
System 2 — Calculation.

When the stochastic trigger fires, the engine "looks." This module is
deliberately small: a depth-limited negamax with a material-only
evaluation function, restricted to the candidate set proposed by
System 1 (plus, optionally, all forcing replies — captures and checks).

What this is NOT:
- A real chess engine. We do not compete with Stockfish; we do not want to.
- A solver. The point of System 2 is to *catch obvious blunders* —
  hangs, missed mates-in-1, trades that lose material — at roughly the
  level a thoughtful human would catch them with a few seconds of
  deliberate calculation.

The Stockfish integration seam lives in `evaluate_with_stockfish` —
unimplemented in the scaffold, but the orchestrator can be pointed at
any object satisfying the same `assess(board, candidates)` interface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import chess


# Centipawn values; classic textbook weights.
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,  # accounted for via mate, not material
}


@dataclass
class TacticalAssessment:
    """Result of a System 2 sweep over a candidate set."""

    best_move_san: str
    best_score_cp: int
    scored: list[tuple[str, int]] = field(default_factory=list)  # [(san, cp), ...]
    nodes: int = 0
    depth: int = 0
    note: str = ""


def _material_score(board: chess.Board) -> int:
    """Centipawn material balance from the side-to-move's perspective."""
    score = 0
    for piece_type, value in PIECE_VALUES.items():
        score += value * len(board.pieces(piece_type, chess.WHITE))
        score -= value * len(board.pieces(piece_type, chess.BLACK))
    return score if board.turn == chess.WHITE else -score


def _evaluate(board: chess.Board) -> int:
    if board.is_checkmate():
        # The side to move is mated — terrible for them.
        return -100_000
    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_threefold_repetition():
        return 0
    return _material_score(board)


def _negamax(board: chess.Board, depth: int, alpha: int, beta: int, node_counter: list[int]) -> int:
    node_counter[0] += 1
    if depth == 0 or board.is_game_over(claim_draw=True):
        return _evaluate(board)

    best = -math.inf
    for move in board.legal_moves:
        board.push(move)
        score = -_negamax(board, depth - 1, -beta, -alpha, node_counter)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return int(best) if best != -math.inf else _evaluate(board)


@dataclass
class System2Calculator:
    """
    Depth-limited negamax with alpha-beta pruning, scored by material.

    `depth` is plies *after* each candidate move (so depth=2 means: I
    play move M, opponent replies, I reply, then evaluate). 3 is a
    sensible default for a scaffold — enough to catch hangs and basic
    tactics, fast enough to run inline.
    """

    depth: int = 3
    include_forcing_moves: bool = True

    def assess(self, board: chess.Board, candidate_san: list[str]) -> TacticalAssessment:
        candidates = self._build_candidate_set(board, candidate_san)
        if not candidates:
            raise RuntimeError("System2.assess: no legal candidates to score.")

        node_counter = [0]
        scored: list[tuple[str, int]] = []
        for move in candidates:
            board.push(move)
            score = -_negamax(board, self.depth - 1, -math.inf, math.inf, node_counter)
            board.pop()
            scored.append((board.san(move), score))

        scored.sort(key=lambda t: t[1], reverse=True)
        best_san, best_cp = scored[0]
        return TacticalAssessment(
            best_move_san=best_san,
            best_score_cp=best_cp,
            scored=scored,
            nodes=node_counter[0],
            depth=self.depth,
            note=f"negamax(material-only), depth={self.depth}",
        )

    def _build_candidate_set(self, board: chess.Board, candidate_san: list[str]) -> list[chess.Move]:
        legal = list(board.legal_moves)
        chosen: list[chess.Move] = []

        # Start from the LLM's suggestions — these are what the human
        # *thought* they wanted to play.
        for san in candidate_san:
            try:
                move = board.parse_san(san)
                if move in legal and move not in chosen:
                    chosen.append(move)
            except ValueError:
                continue

        if self.include_forcing_moves:
            for move in legal:
                if move in chosen:
                    continue
                if board.is_capture(move) or board.gives_check(move):
                    chosen.append(move)

        # Always include the LLM's primary if we somehow lost it.
        if candidate_san:
            try:
                primary = board.parse_san(candidate_san[0])
                if primary in legal and primary not in chosen:
                    chosen.insert(0, primary)
            except ValueError:
                pass

        return chosen or legal[:1]


def evaluate_with_stockfish(board: chess.Board, candidate_san: list[str], *, engine_path: str, depth: int = 12) -> TacticalAssessment:
    """
    Optional Stockfish integration seam. Not wired into the scaffold —
    requires `python-chess[engine]` + a Stockfish binary on disk. Drop
    this in by passing a partial of it to `NeuroSymbolicEngine` in
    place of System2Calculator.assess.
    """
    raise NotImplementedError(
        "Stockfish integration is intentionally left as a future drop-in. "
        "See chess.engine.SimpleEngine.popen_uci(engine_path)."
    )
