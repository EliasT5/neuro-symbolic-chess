"""
NeuroSymbolicEngine — System 1 + System 2 + the trigger.

For every move:
    1. System 1 proposes a move + rationale, conditioned on the profile.
    2. The trigger rolls based on R_T (estimator) vs R_P_Taktik (profile).
    3. If the trigger fires, System 2 sweeps the candidate set:
         - If S2's best move differs from S1's pick AND beats it by
           more than `override_threshold_cp` centipawns, override.
         - Otherwise stand by S1's pick.
    4. If the trigger does NOT fire, we commit to S1's pick *as-is* —
       blunders included. This is the design.

Returns an `EngineDecision` so the caller can render it, log it, and
narrate it for the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import chess

from .profile import PlayerProfile
from .system1 import MoveProposal, System1Intuition
from .system2 import System2Calculator, TacticalAssessment
from .trigger import HeuristicDifficulty, TacticTrigger


@dataclass
class EngineDecision:
    """Fully-traced output of a single move decision."""

    chosen_san: str
    chosen_uci: str
    fen_before: str
    fen_after: str
    rationale: str
    proposal: MoveProposal
    trigger_fired: bool
    trigger_probability: float
    position_difficulty: float
    assessment: Optional[TacticalAssessment] = None
    overridden: bool = False
    override_delta_cp: int = 0
    notes: list[str] = field(default_factory=list)


class NeuroSymbolicEngine:
    """The full neuro-symbolic loop, ready to plug into a game runner."""

    def __init__(
        self,
        profile: PlayerProfile,
        *,
        system1: Optional[System1Intuition] = None,
        system2: Optional[System2Calculator] = None,
        trigger: Optional[TacticTrigger] = None,
        override_threshold_cp: int = 150,
    ):
        self.profile = profile
        self.system1 = system1 or System1Intuition(profile)
        self.system2 = system2 or System2Calculator(depth=3)
        self.trigger = trigger or TacticTrigger(estimator=HeuristicDifficulty())
        self.override_threshold_cp = override_threshold_cp

    def decide(self, board: chess.Board, history_san: list[str]) -> EngineDecision:
        fen_before = board.fen()
        proposal = self.system1.propose(board, history_san)

        fired, probability, difficulty = self.trigger.roll(board, self.profile.sub_elo.tactics)
        notes: list[str] = []

        chosen_san = proposal.san
        chosen_uci = proposal.uci
        fen_after = proposal.fen_after
        rationale = proposal.rationale
        assessment: Optional[TacticalAssessment] = None
        overridden = False
        override_delta = 0

        if fired:
            candidate_set = [proposal.san] + [c for c in proposal.candidates if c != proposal.san]
            assessment = self.system2.assess(board, candidate_set)
            scored = dict(assessment.scored)

            s1_score = scored.get(proposal.san)
            s2_best = assessment.best_move_san
            s2_best_score = assessment.best_score_cp

            if s1_score is None:
                notes.append("S1's pick was not in S2's candidate set — keeping it anyway (LLM intuition is canon when not refuted).")
            else:
                delta = s2_best_score - s1_score
                if s2_best != proposal.san and delta > self.override_threshold_cp:
                    overridden = True
                    override_delta = delta
                    chosen_san = s2_best
                    # Re-derive UCI/FEN-after via guardrails — cheaper than tracking it through.
                    from chess_core import guardrails
                    refined = guardrails.apply_move(fen_before, s2_best)
                    chosen_uci = refined["uci"]
                    fen_after = refined["fen_after"]
                    rationale = (
                        f"On reflection ({assessment.note}), {s2_best} is "
                        f"{delta} cp better than my first instinct ({proposal.san}). "
                        f"Overriding."
                    )
                    notes.append(f"System 2 overrode S1: +{delta} cp.")
                else:
                    notes.append(f"System 2 confirmed S1 (Δ={delta} cp, threshold={self.override_threshold_cp}).")
        else:
            notes.append("Trigger did not fire — committing to intuition.")

        return EngineDecision(
            chosen_san=chosen_san,
            chosen_uci=chosen_uci,
            fen_before=fen_before,
            fen_after=fen_after,
            rationale=rationale,
            proposal=proposal,
            trigger_fired=fired,
            trigger_probability=probability,
            position_difficulty=difficulty,
            assessment=assessment,
            overridden=overridden,
            override_delta_cp=override_delta,
            notes=notes,
        )
