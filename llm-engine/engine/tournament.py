"""
Tournament runner — utilities for the Strength League.

The tournament measures *raw* model strength: no PlayerProfile, no
trigger, no System 2 deepening. Each side is just an LLM proposing a
move, validated through `chess_core.guardrails`, with the same retry +
random-fallback discipline used by System 1 in production.

Architecture note:
    The actual model invocation (`dispatch_to_model`, OpenAI/Anthropic
    SDK, etc.) is supplied by the *driver* — this module is
    transport-agnostic. The driver passes a `move_responder` callable
    of signature `(prompt: str) -> ModelResponse`. That keeps this
    module free of provider plumbing and lets the same code run under
    Claude-driven dispatch (one game at a time) or a script-based
    runner (many games in a batch).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import chess

from chess_core import guardrails

from .elo import apply_game
from .thinking import ThinkingConfig

# --------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------- #

NEUTRAL_SYSTEM = (
    "You are playing chess. Choose strong, legal moves. Output only "
    "the requested JSON — no prose, no code fences, no extra text."
)

MAX_LEGAL_IN_PROMPT = 40


def neutral_prompt(
    board: chess.Board,
    history_san: list[str],
    *,
    thinking: Optional[ThinkingConfig] = None,
    retry_hint: Optional[str] = None,
) -> str:
    """
    The user-content half of the prompt. The system content is
    `NEUTRAL_SYSTEM` and is constant.
    """
    side = "White" if board.turn == chess.WHITE else "Black"
    legal_san = [board.san(m) for m in board.legal_moves][:MAX_LEGAL_IN_PROMPT]
    recent = " ".join(history_san[-12:]) if history_san else "(start of game)"

    base = (
        f"You are playing the {side} pieces.\n"
        f"Position FEN: {board.fen()}\n"
        f"Recent moves: {recent}\n"
        f"Legal moves (SAN): {', '.join(legal_san)}\n\n"
        "Choose ONE legal move from the list above. Reply as compact JSON "
        'with keys `move` (SAN) and `rationale` (one sentence): '
        '{"move": "Nf3", "rationale": "develops a piece toward the center"}'
    )
    if retry_hint:
        base += f"\n\nRETRY: {retry_hint}"
    if thinking:
        base = thinking.augment_prompt(base)
    return base


# --------------------------------------------------------------------- #
# Move parsing + per-side stats
# --------------------------------------------------------------------- #


@dataclass
class ModelResponse:
    """What the driver passes back from a model call."""

    raw_text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


@dataclass
class MoveOutcome:
    san: str
    uci: str
    fen_after: str
    rationale: str
    thinking: str = ""
    illegal_count: int = 0
    used_fallback: bool = False
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


def parse_move_from_response(raw: str, board: chess.Board, *, thinking: Optional[ThinkingConfig] = None) -> tuple[Optional[str], str, str]:
    """
    Returns (move_san_or_None, rationale, thinking_text).
    `move_san_or_None` is None if no legal move could be extracted.
    """
    cfg = thinking or ThinkingConfig(enabled=False)
    thinking_text, body = cfg.extract_thinking(raw)

    move_str: Optional[str] = None
    rationale = ""

    body = body.strip()
    if body.startswith("```"):
        body = body.strip("`").lstrip("json").strip()

    try:
        data = json.loads(body)
        if isinstance(data, dict):
            move_str = data.get("move") or data.get("san") or data.get("uci")
            rationale = str(data.get("rationale", "")).strip()
    except json.JSONDecodeError:
        # Fallback: pull the first SAN-looking token out of the prose.
        import re
        m = re.search(r"\b([NBRQK]?[a-h]?[1-8]?x?[a-h][1-8](?:=[NBRQ])?[+#]?|O-O(?:-O)?|[a-h][1-8][a-h][1-8][nbrq]?)\b", body)
        if m:
            move_str = m.group(1)
            rationale = body[:200]

    if not move_str:
        return None, rationale, thinking_text

    result = guardrails.apply_move(board.fen(), move_str)
    if not result.get("ok"):
        return None, rationale, thinking_text
    return result["san"], rationale, thinking_text


# --------------------------------------------------------------------- #
# Per-side accumulator
# --------------------------------------------------------------------- #


@dataclass
class SideStats:
    moves: int = 0
    illegal_moves: int = 0
    fallbacks: int = 0
    tokens: int = 0
    cost: float = 0.0
    total_latency_ms: int = 0
    rationales: list[str] = field(default_factory=list)
    thinking_blocks: list[str] = field(default_factory=list)

    def avg_time_ms(self) -> float:
        return (self.total_latency_ms / self.moves) if self.moves else 0.0


# --------------------------------------------------------------------- #
# Game session
# --------------------------------------------------------------------- #


@dataclass
class GameSession:
    """Lives across turns when Claude is the dispatch driver. Persistable."""

    game_id: str
    white_key: str
    black_key: str
    started_at: str
    initial_fen: str
    moves: list[str] = field(default_factory=list)
    fens: list[str] = field(default_factory=list)  # fen_after each move; useful for stepper
    move_records: list[dict] = field(default_factory=list)
    white_stats: SideStats = field(default_factory=SideStats)
    black_stats: SideStats = field(default_factory=SideStats)

    @property
    def board(self) -> chess.Board:
        b = chess.Board(self.initial_fen)
        for san in self.moves:
            b.push_san(san)
        return b

    def to_json(self) -> str:
        return json.dumps({
            "game_id": self.game_id,
            "white_key": self.white_key,
            "black_key": self.black_key,
            "started_at": self.started_at,
            "initial_fen": self.initial_fen,
            "moves": self.moves,
            "fens": self.fens,
            "move_records": self.move_records,
            "white_stats": asdict(self.white_stats),
            "black_stats": asdict(self.black_stats),
        }, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "GameSession":
        data = json.loads(Path(path).read_text())
        ws = SideStats(**data.pop("white_stats"))
        bs = SideStats(**data.pop("black_stats"))
        return cls(white_stats=ws, black_stats=bs, **data)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())


def new_session(white_key: str, black_key: str, *, game_id: Optional[str] = None) -> GameSession:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    gid = game_id or f"g-{int(time.time())}"
    return GameSession(
        game_id=gid,
        white_key=white_key,
        black_key=black_key,
        started_at=started,
        initial_fen=chess.STARTING_FEN,
        fens=[],
    )


# --------------------------------------------------------------------- #
# Move ingestion (driver-facing)
# --------------------------------------------------------------------- #


def submit_move(
    session: GameSession,
    response: ModelResponse,
    *,
    thinking: Optional[ThinkingConfig] = None,
    rng_seed: Optional[int] = None,
) -> MoveOutcome:
    """
    Ingest one model response. Validates, retries logic is the driver's
    responsibility (driver re-calls submit_move with another response if
    the first was illegal). On the third illegal we fall back to a
    random legal move.

    Returns the MoveOutcome and mutates the session in place.
    """
    board = session.board
    side_white = board.turn == chess.WHITE
    stats = session.white_stats if side_white else session.black_stats

    san, rationale, thinking_text = parse_move_from_response(response.raw_text, board, thinking=thinking)

    used_fallback = False
    illegal_this_call = 0 if san else 1

    if not san:
        # We do NOT auto-fallback here — the driver decides whether to
        # retry with a hint. submit_move just reports back.
        outcome = MoveOutcome(
            san="",
            uci="",
            fen_after=board.fen(),
            rationale=rationale,
            thinking=thinking_text,
            illegal_count=1,
            used_fallback=False,
            tokens=response.tokens_in + response.tokens_out,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
        )
        stats.illegal_moves += 1
        stats.tokens += outcome.tokens
        stats.cost += outcome.cost_usd
        stats.total_latency_ms += outcome.latency_ms
        return outcome

    # Apply the move
    result = guardrails.apply_move(board.fen(), san)
    assert result["ok"], f"parse_move_from_response returned a move that guardrails rejected: {san}"
    board.push_san(san)
    session.moves.append(san)
    session.fens.append(result["fen_after"])

    move_rec = {
        "ply": len(session.moves),
        "side": "white" if side_white else "black",
        "san": san,
        "uci": result["uci"],
        "fen_after": result["fen_after"],
        "status": result["status"],
        "rationale": rationale,
        "thinking": thinking_text,
        "tokens": response.tokens_in + response.tokens_out,
        "cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
    }
    session.move_records.append(move_rec)

    stats.moves += 1
    stats.tokens += response.tokens_in + response.tokens_out
    stats.cost += response.cost_usd
    stats.total_latency_ms += response.latency_ms
    if rationale:
        stats.rationales.append(rationale)
    if thinking_text:
        stats.thinking_blocks.append(thinking_text)

    return MoveOutcome(
        san=san,
        uci=result["uci"],
        fen_after=result["fen_after"],
        rationale=rationale,
        thinking=thinking_text,
        illegal_count=illegal_this_call,
        used_fallback=used_fallback,
        tokens=response.tokens_in + response.tokens_out,
        cost_usd=response.cost_usd,
        latency_ms=response.latency_ms,
    )


def force_random_fallback(session: GameSession, response: ModelResponse) -> MoveOutcome:
    """
    Driver calls this after retries failed. Plays a uniformly random
    legal move, attributes the cost of the failed attempts to the
    side's stats, and flags the fallback.
    """
    import random
    board = session.board
    side_white = board.turn == chess.WHITE
    stats = session.white_stats if side_white else session.black_stats

    legal = list(board.legal_moves)
    chosen = random.choice(legal)
    san = board.san(chosen)
    result = guardrails.apply_move(board.fen(), san)
    board.push_san(san)
    session.moves.append(san)
    session.fens.append(result["fen_after"])

    stats.moves += 1
    stats.fallbacks += 1
    stats.tokens += response.tokens_in + response.tokens_out
    stats.cost += response.cost_usd
    stats.total_latency_ms += response.latency_ms

    move_rec = {
        "ply": len(session.moves),
        "side": "white" if side_white else "black",
        "san": san,
        "uci": result["uci"],
        "fen_after": result["fen_after"],
        "status": result["status"],
        "rationale": "(fallback to random legal move after retries failed)",
        "thinking": "",
        "tokens": response.tokens_in + response.tokens_out,
        "cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
        "fallback": True,
    }
    session.move_records.append(move_rec)

    return MoveOutcome(
        san=san, uci=result["uci"], fen_after=result["fen_after"],
        rationale=move_rec["rationale"], thinking="",
        illegal_count=0, used_fallback=True,
        tokens=move_rec["tokens"], cost_usd=move_rec["cost_usd"],
        latency_ms=move_rec["latency_ms"],
    )


# --------------------------------------------------------------------- #
# Termination + result
# --------------------------------------------------------------------- #


def is_terminal(session: GameSession) -> tuple[bool, str, str]:
    """
    Returns (done, result_string, termination_reason).
    Honours all standard chess draw rules — no artificial move cap.
    """
    board = session.board
    if board.is_checkmate():
        winner = "0-1" if board.turn == chess.WHITE else "1-0"
        return True, winner, "checkmate"
    if board.is_stalemate():
        return True, "1/2-1/2", "stalemate"
    if board.is_insufficient_material():
        return True, "1/2-1/2", "insufficient_material"
    if board.is_fivefold_repetition():
        return True, "1/2-1/2", "fivefold_repetition"
    if board.is_seventyfive_moves():
        return True, "1/2-1/2", "seventyfive_move_rule"
    if board.can_claim_threefold_repetition():
        return True, "1/2-1/2", "threefold_repetition"
    if board.can_claim_fifty_moves():
        return True, "1/2-1/2", "fifty_move_rule"
    return False, "", ""


# --------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------- #


def _opening_signature(moves: list[str], plies: int = 6) -> str:
    return " ".join(moves[:plies]) if moves else ""


def finalize_and_persist(
    session: GameSession,
    result: str,
    termination: str,
    *,
    repo_root: str | Path,
) -> dict:
    """
    Write the game record into data/tournament/games.json and update
    Elo + W/D/L counters in data/tournament/players.json.

    Returns the appended game record.
    """
    repo = Path(repo_root)
    players_path = repo / "data" / "tournament" / "players.json"
    games_path   = repo / "data" / "tournament" / "games.json"

    players_doc = json.loads(players_path.read_text())
    games_doc   = json.loads(games_path.read_text())

    by_key = {p["key"]: p for p in players_doc["models"]}
    w = by_key[session.white_key]
    b = by_key[session.black_key]

    elo_before = {"white": w["current_elo"], "black": b["current_elo"]}
    upd_w, upd_b = apply_game(w["current_elo"], b["current_elo"], w["games_played"], b["games_played"], result)
    elo_after = {"white": upd_w.new_rating, "black": upd_b.new_rating}

    # Update player rows
    w["current_elo"] = upd_w.new_rating
    b["current_elo"] = upd_b.new_rating
    w["games_played"] += 1
    b["games_played"] += 1
    if result == "1-0":
        w["wins"] += 1; b["losses"] += 1
    elif result == "0-1":
        w["losses"] += 1; b["wins"] += 1
    else:
        w["draws"] += 1; b["draws"] += 1

    pgn = " ".join(
        f"{(i // 2) + 1}." + (" " if i % 2 == 0 else "..") + f" {san}"
        for i, san in enumerate(session.moves)
    )

    record = {
        "id": session.game_id,
        "date": session.started_at,
        "white": {"id": w["id"], "variant": w["variant"]},
        "black": {"id": b["id"], "variant": b["variant"]},
        "result": result,
        "termination": termination,
        "moves": session.moves,
        "fens": session.fens,
        "pgn": pgn,
        "opening": _opening_signature(session.moves),
        "elo_before": elo_before,
        "elo_after": elo_after,
        "elo_delta": {"white": upd_w.delta, "black": upd_b.delta},
        "expected": {"white": round(upd_w.expected, 4), "black": round(upd_b.expected, 4)},
        "k_factor": {"white": upd_w.k, "black": upd_b.k},
        "stats": {
            "white": {
                "moves":          session.white_stats.moves,
                "illegal_moves":  session.white_stats.illegal_moves,
                "fallbacks":      session.white_stats.fallbacks,
                "tokens":         session.white_stats.tokens,
                "cost":           round(session.white_stats.cost, 6),
                "avg_time_ms":    round(session.white_stats.avg_time_ms(), 1),
            },
            "black": {
                "moves":          session.black_stats.moves,
                "illegal_moves":  session.black_stats.illegal_moves,
                "fallbacks":      session.black_stats.fallbacks,
                "tokens":         session.black_stats.tokens,
                "cost":           round(session.black_stats.cost, 6),
                "avg_time_ms":    round(session.black_stats.avg_time_ms(), 1),
            },
        },
        "move_records": session.move_records,
    }

    games_doc.setdefault("games", []).append(record)

    players_path.write_text(json.dumps(players_doc, indent=2) + "\n")
    games_path.write_text(json.dumps(games_doc, indent=2) + "\n")
    return record
