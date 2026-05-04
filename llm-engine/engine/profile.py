"""
PlayerProfile — Elo decomposition for the simulated opponent.

The classical Elo number compresses four very different competencies
into one scalar: tactics, strategy, endgame, and opening theory. A
human's blunders cluster by *which of these they're weak at*, not by
"random under-performance." This module exposes the four sub-Elos
(R_P_Taktik, R_P_Strategie, R_P_Endspiel, R_P_Eröffnung) plus stylistic
descriptors that get fed into System 1's prompt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SubElo:
    """The four-axis Elo decomposition from the research paper."""

    tactics: int = 1500       # R_P_Taktik
    strategy: int = 1500      # R_P_Strategie
    endgame: int = 1500       # R_P_Endspiel
    opening: int = 1500       # R_P_Eröffnung

    @property
    def composite(self) -> int:
        """Mean across axes; useful for sanity-checking against a published Elo."""
        return round((self.tactics + self.strategy + self.endgame + self.opening) / 4)


@dataclass
class PlayerProfile:
    """
    A simulated opponent. Loaded from JSON in `data/profiles/*.json`
    and passed into System 1's prompt construction.
    """

    name: str
    sub_elo: SubElo = field(default_factory=SubElo)

    # Free-form stylistic guidance for the LLM. Kept short and
    # behavioural; the LLM does the rest.
    style: str = "Balanced; no strong preferences."

    # Opening repertoire as White and Black (ECO codes or names).
    repertoire_white: list[str] = field(default_factory=list)
    repertoire_black: list[str] = field(default_factory=list)

    # Known weaknesses — surfaces in narration ("avoiding the trade
    # because you're stronger in the endgame").
    weaknesses: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)

    # Optional source PGN corpus (for future fine-tuning); not yet used.
    pgn_corpus: Optional[str] = None

    @classmethod
    def load(cls, path: str | Path) -> "PlayerProfile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sub = data.pop("sub_elo", {})
        return cls(sub_elo=SubElo(**sub), **data)

    def save(self, path: str | Path) -> None:
        payload = asdict(self)
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def prompt_summary(self) -> str:
        """One paragraph the LLM can read at the top of its prompt."""
        lines = [
            f"You are simulating {self.name}.",
            f"Sub-Elo — tactics {self.sub_elo.tactics}, strategy {self.sub_elo.strategy}, "
            f"endgame {self.sub_elo.endgame}, opening {self.sub_elo.opening}.",
            f"Style: {self.style}",
        ]
        if self.repertoire_white:
            lines.append(f"As White, prefers: {', '.join(self.repertoire_white)}.")
        if self.repertoire_black:
            lines.append(f"As Black, prefers: {', '.join(self.repertoire_black)}.")
        if self.strengths:
            lines.append(f"Strengths: {', '.join(self.strengths)}.")
        if self.weaknesses:
            lines.append(f"Weaknesses: {', '.join(self.weaknesses)}.")
        return "\n".join(lines)
