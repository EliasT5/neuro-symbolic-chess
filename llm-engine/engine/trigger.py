"""
Stochastic Tactic Trigger.

The crown jewel of the architecture: rather than always calculating,
the engine *probabilistically* decides whether System 2 (the deterministic
calculator) should look at a position. The probability follows the
classical Elo expectancy curve from the README:

    P(Trigger) = 1 / (1 + 10 ^ ((R_T - R_P_Taktik) / 400))

Where:
    R_T          = tactical difficulty rating of the position
    R_P_Taktik   = the simulated player's tactical sub-Elo

Intuition:
    - Easy tactic (low R_T) vs strong tactician → P ≈ 1 (always seen)
    - Hard tactic (high R_T) vs weak tactician  → P ≈ 0 (always missed)
    - Equal ratings                              → P = 0.5

When the trigger does *not* fire, the engine commits to System 1's
intuitive move — including any blunder it contains. That is the entire
point: characteristic mistakes, not uniform under-performance.

Estimating R_T from a position is itself a research problem. For the
scaffold we expose three difficulty estimators (constant, heuristic,
puzzle-rated) so the rest of the engine can be developed against a
stable interface while the estimator is iterated on.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Protocol

import chess


def trigger_probability(position_difficulty: float, player_tactics_elo: float) -> float:
    """The README equation. Returns a probability in [0, 1]."""
    exponent = (position_difficulty - player_tactics_elo) / 400.0
    return 1.0 / (1.0 + math.pow(10.0, exponent))


class DifficultyEstimator(Protocol):
    """Anything that can score a position's tactical difficulty in Elo terms."""

    def estimate(self, board: chess.Board) -> float: ...


@dataclass
class ConstantDifficulty:
    """Returns a fixed R_T for every position. Useful for tests and bootstrapping."""

    rating: float = 1500.0

    def estimate(self, board: chess.Board) -> float:
        return self.rating


@dataclass
class HeuristicDifficulty:
    """
    Cheap, no-model estimator. Boosts difficulty when the position
    smells tactical: side-to-move is in check, a recent capture
    happened, or many candidate moves involve a capture/check. A real
    implementation would use a learned policy; this is a placeholder
    that's at least not wrong on obvious cases.

    Bounds: [floor, ceiling].
    """

    floor: float = 1100.0
    ceiling: float = 2300.0
    base: float = 1500.0

    def estimate(self, board: chess.Board) -> float:
        score = self.base
        legal = list(board.legal_moves)
        if not legal:
            return self.floor

        if board.is_check():
            score += 200

        captures = [m for m in legal if board.is_capture(m)]
        checks = [m for m in legal if board.gives_check(m)]
        capture_ratio = len(captures) / len(legal)
        check_ratio = len(checks) / len(legal)

        score += 300 * capture_ratio
        score += 200 * check_ratio

        # Many forcing options → it's a calculation position.
        if len(captures) + len(checks) >= 4:
            score += 150

        # Endgame-ish positions get a small discount: tactics are
        # rarer, but when they exist they're deeper.
        major_pieces = sum(1 for p in board.piece_map().values() if p.piece_type in (chess.QUEEN, chess.ROOK))
        if major_pieces <= 2:
            score -= 100

        return max(self.floor, min(self.ceiling, score))


@dataclass
class TacticTrigger:
    """
    Bundles an estimator + RNG. `roll(board, profile_tactics_elo)`
    returns (fired, probability, difficulty) so the orchestrator can
    log *why* it did or didn't deepen the search.
    """

    estimator: DifficultyEstimator
    rng: random.Random | None = None

    def roll(self, board: chess.Board, player_tactics_elo: float) -> tuple[bool, float, float]:
        difficulty = self.estimator.estimate(board)
        probability = trigger_probability(difficulty, player_tactics_elo)
        rng = self.rng or random
        fired = rng.random() < probability
        return fired, probability, difficulty
