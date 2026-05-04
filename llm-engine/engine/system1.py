"""
System 1 — Intuition.

Asks an LLM, conditioned on a PlayerProfile and the current position,
for one move plus a short rationale. The output is then *always*
validated by the guardrails (System 2's substrate). If illegal, we
retry once with the legal alternatives in the prompt; if still illegal,
we fall back to a uniformly random legal move and flag the proposal as
a `fallback`.

Design choices:
- Prompt is short and structured; LLMs are bad enough at chess without
  giving them paragraphs of reasoning to ramble through.
- The list of legal moves is *always* included. This trades a few
  tokens for a sharp drop in illegal proposals.
- We accept SAN, UCI, or a "best move: <move>" wrapper. The guardrails
  parse all three.
- The Model-O client is constructed lazily so the engine importable
  without an API key (handy for unit tests of trigger / profile).
"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from typing import Optional

import chess

from chess_core import guardrails

from .thinking import ThinkingConfig

DEFAULT_MODEL = os.environ.get("NSC_LLM_MODEL", "model-o-4o-mini")
MAX_LEGAL_IN_PROMPT = 40


@dataclass
class MoveProposal:
    """What System 1 returns to the orchestrator."""

    san: str
    uci: str
    fen_after: str
    rationale: str
    candidates: list[str] = field(default_factory=list)  # top moves the LLM considered
    used_fallback: bool = False
    raw_response: str = ""
    thinking: str = ""  # captured <thinking>…</thinking> block, if any


_MOVE_FROM_TEXT_RE = re.compile(r"\b([NBRQK]?[a-h]?[1-8]?x?[a-h][1-8](?:=[NBRQ])?[+#]?|O-O(?:-O)?|[a-h][1-8][a-h][1-8][nbrq]?)\b")


class System1Intuition:
    """LLM-backed move proposer with guardrail validation."""

    def __init__(
        self,
        profile,
        *,
        client=None,
        model: str = DEFAULT_MODEL,
        rng: Optional[random.Random] = None,
        thinking: Optional[ThinkingConfig] = None,
    ):
        self.profile = profile
        self._client = client
        self.model = model
        self.rng = rng or random
        self.thinking = thinking or ThinkingConfig(enabled=False)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def propose(self, board: chess.Board, history_san: list[str]) -> MoveProposal:
        legal = list(board.legal_moves)
        if not legal:
            raise RuntimeError("System1.propose called on a terminal position.")

        prompt = self.thinking.augment_prompt(self._build_prompt(board, history_san, legal))
        raw = self._call_llm(prompt)

        proposal = self._extract_proposal(raw, board, legal)
        if proposal is not None:
            return proposal

        # Retry once with a tighter prompt referencing only the legal moves.
        retry_prompt = prompt + "\n\nYour previous answer could not be parsed as a legal move. Reply with only one move from the legal list above, in SAN."
        raw_retry = self._call_llm(retry_prompt)
        proposal = self._extract_proposal(raw_retry, board, legal)
        if proposal is not None:
            return proposal

        # Last resort: uniformly random legal move. Flagged as fallback.
        chosen = self.rng.choice(legal)
        san = board.san(chosen)
        check = guardrails.apply_move(board.fen(), san)
        return MoveProposal(
            san=san,
            uci=chosen.uci(),
            fen_after=check["fen_after"],
            rationale="(LLM produced no legal move twice; falling back to a random legal move.)",
            candidates=[],
            used_fallback=True,
            raw_response=raw + "\n---retry---\n" + raw_retry,
        )

    # ------------------------------------------------------------------ #
    # Prompting
    # ------------------------------------------------------------------ #

    def _build_prompt(self, board: chess.Board, history_san: list[str], legal: list[chess.Move]) -> str:
        # Cap the legal-move list — in middlegames it can hit 40+ which is
        # both noisy and unnecessary; the LLM only ever picks one.
        legal_san = [board.san(m) for m in legal][:MAX_LEGAL_IN_PROMPT]
        side = "White" if board.turn == chess.WHITE else "Black"

        recent = " ".join(history_san[-12:]) if history_san else "(start of game)"

        return (
            f"{self.profile.prompt_summary()}\n\n"
            f"Position FEN: {board.fen()}\n"
            f"Side to move: {side}\n"
            f"Recent moves: {recent}\n"
            f"Legal moves (SAN): {', '.join(legal_san)}\n\n"
            "Choose ONE move that fits the simulated player's profile and style. "
            "Reply as JSON with keys `move` (SAN), `rationale` (one sentence), "
            "and `candidates` (up to 3 alternative SAN moves you considered). "
            "Do not wrap in code fences."
        )

    def _call_llm(self, prompt: str) -> str:
        client = self._get_client()
        if client is None:
            # Importable without a key — for tests we degrade to a
            # heuristic that picks a central or developing move.
            return self._heuristic_response(prompt)

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You play chess in the style of a specific human profile. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _extract_proposal(self, raw: str, board: chess.Board, legal: list[chess.Move]) -> Optional[MoveProposal]:
        if not raw:
            return None

        thinking_inner, raw = self.thinking.extract_thinking(raw)

        move_str: Optional[str] = None
        rationale = ""
        candidates: list[str] = []

        # Try JSON first.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None

        if isinstance(data, dict):
            move_str = data.get("move") or data.get("san") or data.get("uci")
            rationale = str(data.get("rationale", "")).strip()
            cand = data.get("candidates") or []
            if isinstance(cand, list):
                candidates = [str(c) for c in cand][:3]

        if not move_str:
            match = _MOVE_FROM_TEXT_RE.search(raw)
            if match:
                move_str = match.group(1)
                rationale = raw.strip()

        if not move_str:
            return None

        result = guardrails.apply_move(board.fen(), move_str)
        if not result.get("ok"):
            return None

        return MoveProposal(
            san=result["san"],
            uci=result["uci"],
            fen_after=result["fen_after"],
            rationale=rationale or "(no rationale provided)",
            candidates=candidates,
            used_fallback=False,
            raw_response=raw,
            thinking=thinking_inner,
        )

    # ------------------------------------------------------------------ #
    # Client + offline heuristic
    # ------------------------------------------------------------------ #

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not os.environ.get("MODEL_O_API_KEY"):
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        self._client = OpenAI()
        return self._client

    def _heuristic_response(self, prompt: str) -> str:
        """
        Used when no API key is configured. Picks a "reasonable" move by
        crude priorities so the rest of the engine can be exercised
        end-to-end without burning tokens.
        """
        # The legal list lives inside the prompt; pull it back out.
        match = re.search(r"Legal moves \(SAN\): (.+)", prompt)
        if not match:
            return ""
        legal_san = [m.strip() for m in match.group(1).split(",")]

        priorities = [
            lambda m: m.endswith("#"),                                       # mate
            lambda m: m.endswith("+"),                                       # check
            lambda m: "x" in m and m[0] in "NBRQK",                          # piece capture
            lambda m: "x" in m,                                              # any capture
            lambda m: m in {"e4", "d4", "e5", "d5"},                         # central pawn
            lambda m: m.startswith(("N", "B")) and not m.startswith(("Na", "Nh", "Ba", "Bh")),  # develop
            lambda m: m in {"O-O", "O-O-O"},                                 # castle
        ]
        for predicate in priorities:
            for move in legal_san:
                if predicate(move):
                    return json.dumps({
                        "move": move,
                        "rationale": "(offline heuristic: no API key configured)",
                        "candidates": legal_san[:3],
                    })
        return json.dumps({"move": legal_san[0], "rationale": "(offline heuristic: first legal move)", "candidates": []})
