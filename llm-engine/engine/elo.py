"""
FIDE Elo update math.

Standard formula:
    E_a = 1 / (1 + 10 ^ ((R_b - R_a) / 400))    expected score for player A
    R_a' = R_a + K * (S_a - E_a)                rating update

K-factor (FIDE convention):
    K = 40   for the player's first 30 rated games (or until rating reaches 2300)
    K = 20   thereafter

S_a is the actual score for A: 1.0 win, 0.5 draw, 0.0 loss.
"""

from __future__ import annotations

from dataclasses import dataclass


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability A scores against B (1 = win, 0.5 = draw, 0 = loss)."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def k_factor(games_played: int, current_rating: float, *, threshold_games: int = 30, threshold_rating: float = 2300.0) -> int:
    """K=40 while still 'new' (under 30 games AND under 2300 rating). Else K=20."""
    if games_played < threshold_games and current_rating < threshold_rating:
        return 40
    return 20


@dataclass
class EloUpdate:
    """Result of a single rating update."""

    new_rating: int
    delta: int
    expected: float
    k: int


def update_rating(rating: float, opponent_rating: float, score: float, games_played: int) -> EloUpdate:
    """
    `score` ∈ {0.0, 0.5, 1.0}. Returns the new (rounded) rating + signed delta.
    """
    e = expected_score(rating, opponent_rating)
    k = k_factor(games_played, rating)
    new = rating + k * (score - e)
    new_rounded = round(new)
    return EloUpdate(
        new_rating=new_rounded,
        delta=new_rounded - round(rating),
        expected=e,
        k=k,
    )


def apply_game(white_rating: float, black_rating: float, white_games: int, black_games: int, result: str) -> tuple[EloUpdate, EloUpdate]:
    """
    Apply a result (one of '1-0', '0-1', '1/2-1/2') to both players.
    Returns (white_update, black_update).
    """
    if result == "1-0":
        s_white, s_black = 1.0, 0.0
    elif result == "0-1":
        s_white, s_black = 0.0, 1.0
    elif result in ("1/2-1/2", "½-½"):
        s_white, s_black = 0.5, 0.5
    else:
        raise ValueError(f"Unknown result string: {result!r}")

    return (
        update_rating(white_rating, black_rating, s_white, white_games),
        update_rating(black_rating, white_rating, s_black, black_games),
    )
