"""Neuro-symbolic chess engine — System 1 (intuition) + System 2 (calculation)."""

from .profile import PlayerProfile, SubElo
from .trigger import TacticTrigger, trigger_probability
from .system1 import System1Intuition, MoveProposal
from .system2 import System2Calculator, TacticalAssessment
from .orchestrator import NeuroSymbolicEngine, EngineDecision
from .thinking import ThinkingConfig, NATIVE_THINKING_MODELS
from .elo import EloUpdate, apply_game, expected_score, k_factor, update_rating
from .tournament import (
    GameSession,
    ModelResponse,
    MoveOutcome,
    SideStats,
    finalize_and_persist,
    force_random_fallback,
    is_terminal,
    neutral_prompt,
    new_session,
    submit_move,
)

__all__ = [
    "PlayerProfile",
    "SubElo",
    "TacticTrigger",
    "trigger_probability",
    "System1Intuition",
    "MoveProposal",
    "System2Calculator",
    "TacticalAssessment",
    "NeuroSymbolicEngine",
    "EngineDecision",
    "ThinkingConfig",
    "NATIVE_THINKING_MODELS",
    "EloUpdate",
    "apply_game",
    "expected_score",
    "k_factor",
    "update_rating",
    "GameSession",
    "ModelResponse",
    "MoveOutcome",
    "SideStats",
    "finalize_and_persist",
    "force_random_fallback",
    "is_terminal",
    "neutral_prompt",
    "new_session",
    "submit_move",
]
