"""
Thinking Tool — uniform extended-reasoning scaffold.

Some models in our roster (Opus 4.7, Sonnet 4.6, Gemini 3 Pro,
GPT 5.5, GPT 5.3 Codex) support extended thinking natively via a
provider-specific API parameter. Others (Haiku 4.5, Gemini Flash Lite,
GPT 5.4 Mini) do not. To compare apples to apples in the tournament,
we expose a *uniform* thinking interface based on a prompt scaffold:

    1. Append a scaffold instruction asking the model to reason inside
       <thinking>...</thinking> tags before committing to an answer.
    2. After the response comes back, strip the thinking block before
       passing the rest to the move parser.

This works on every model regardless of native support — native
thinkers will simply do better with it (richer hidden reasoning to
apply), while scaffold-only models gain the same shape of behaviour at
the cost of a few hundred extra output tokens.

A second variant of every model is registered in the tournament
roster as `<id> (thinking)` so the data shows whether the scaffold
actually moves the needle on Elo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Models with first-class extended-thinking APIs. Listed for
# documentation; the scaffold approach below is provider-agnostic and
# does not branch on this set.
NATIVE_THINKING_MODELS: frozenset[str] = frozenset({
    "claude-code-opus",
    "claude-code-sonnet",
    "gemini-cli-pro",
    "gemini-cli-auto",
    "codex-cli-gpt55",
    "codex-cli-codex",
})


SCAFFOLD_INSTRUCTION = (
    "Before you answer, think the position through. Open with a "
    "<thinking> block in which you (a) name the candidate moves you are "
    "weighing, (b) consider the opponent's most likely reply to each, "
    "(c) check whether your top choice loses material or walks into a "
    "tactic, and (d) confirm the move fits the simulated player's "
    "profile. Close the block with </thinking>. After </thinking>, "
    "output ONLY the final JSON answer with no extra prose. The "
    "thinking block will be discarded; only what comes after it is "
    "parsed."
)


_THINKING_BLOCK_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


@dataclass
class ThinkingConfig:
    """Toggle + tuning for the scaffold."""

    enabled: bool = False
    # Soft hint to the caller for budgeting output tokens. The scaffold
    # itself doesn't enforce this — it lives in the LLM call site.
    extra_max_tokens: int = 600

    def augment_prompt(self, base_prompt: str) -> str:
        if not self.enabled:
            return base_prompt
        return f"{base_prompt}\n\n{SCAFFOLD_INSTRUCTION}"

    def extract_thinking(self, raw: str) -> tuple[str, str]:
        """
        Returns (thinking_text, post_thinking_text).
        If no thinking block is present, returns ("", raw).
        """
        if not raw:
            return "", ""
        match = _THINKING_BLOCK_RE.search(raw)
        if not match:
            return "", raw
        thinking = match.group(0)
        # Strip the inner thinking content for storage; remove the whole
        # block (tags included) from the post-text so downstream parsers
        # see only the JSON.
        inner = thinking[len("<thinking>") : -len("</thinking>")].strip()
        post = _THINKING_BLOCK_RE.sub("", raw, count=1).strip()
        return inner, post

    def is_native_capable(self, model_id: str) -> bool:
        return model_id in NATIVE_THINKING_MODELS
