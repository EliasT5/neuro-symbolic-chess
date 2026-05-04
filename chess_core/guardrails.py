"""
Pure-Python guardrail primitives for chess move validation, legality
listing, PGN parsing, and board rendering. Mirrors the surface of
Jerome's `chess.move` / `chess.legal_moves` MCP tools so external
clients (the LLM engine, the MCP server, tests) all see the same
semantics.

Design notes:
- No framework dependencies — only `python-chess`. Anything HTTP- or
  MCP-shaped lives in the wrappers.
- Response dicts use the same field names as Jerome's broker so the
  shapes are interchangeable when this server is swapped in.
- Move parsing accepts SAN, UCI, or plain "e2 e4" / "e2-e4" forms.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Iterable

import chess
import chess.pgn
import chess.svg

ALTERNATIVE_LIMIT = 6


class GameStatus:
    NORMAL = "normal"
    CHECK = "check"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    DRAW_50_MOVE = "draw_50_move"
    DRAW_75_MOVE = "draw_75_move"
    DRAW_FIVEFOLD = "draw_fivefold_repetition"


def get_game_status(board: chess.Board) -> str:
    if board.is_checkmate():
        return GameStatus.CHECKMATE
    if board.is_stalemate():
        return GameStatus.STALEMATE
    if board.is_insufficient_material():
        return GameStatus.INSUFFICIENT_MATERIAL
    if board.is_fivefold_repetition():
        return GameStatus.DRAW_FIVEFOLD
    if board.is_seventyfive_moves():
        return GameStatus.DRAW_75_MOVE
    if board.halfmove_clock >= 100:
        return GameStatus.DRAW_50_MOVE
    if board.is_check():
        return GameStatus.CHECK
    return GameStatus.NORMAL


def _side(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


_PLAIN_MOVE_RE = re.compile(r"[\s\-→>]+")


def _normalise_move_str(move: str) -> str:
    return _PLAIN_MOVE_RE.sub("", move.strip())


def _parse_move(board: chess.Board, move: str) -> chess.Move:
    """
    Try SAN → UCI → normalised-plain in that order. Raises ValueError
    if none succeed.
    """
    raw = move.strip()
    # SAN first (most common from an LLM); strip decorations.
    san = raw.rstrip("+#!?")
    try:
        return board.parse_san(san)
    except ValueError:
        pass

    cleaned = _normalise_move_str(raw)
    try:
        return board.parse_uci(cleaned.lower())
    except ValueError:
        pass

    raise ValueError(f"Could not parse move {move!r}")


def _alternatives(board: chess.Board, attempted: str | None = None) -> list[dict[str, str]]:
    """
    Up to ALTERNATIVE_LIMIT legal moves, biased toward the same piece
    type if we can guess one from the failed input.
    """
    legal = list(board.legal_moves)
    if not legal:
        return []

    biased: list[chess.Move] = []
    if attempted:
        first = attempted.strip()[:1]
        piece_letters = {"N", "B", "R", "Q", "K"}
        if first in piece_letters:
            piece_type = chess.PIECE_SYMBOLS.index(first.lower())
            biased = [m for m in legal if board.piece_at(m.from_square) and board.piece_at(m.from_square).piece_type == piece_type]

    chosen = (biased + [m for m in legal if m not in biased])[:ALTERNATIVE_LIMIT]
    return [{"san": board.san(m), "uci": m.uci()} for m in chosen]


def apply_move(fen: str, move: str) -> dict[str, Any]:
    """
    Validate a move against `fen`. On success, return the resulting
    FEN plus SAN/UCI/status. On failure, return a structured error
    with up to 6 legal alternatives.
    """
    try:
        board = chess.Board(fen)
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid FEN: {e}"}]}

    try:
        parsed = _parse_move(board, move)
    except ValueError:
        legal = list(board.legal_moves)
        return {
            "ok": False,
            "reason": f"{move!r} is illegal or unrecognised in this position.",
            "to_move": _side(board),
            "alternatives": _alternatives(board, attempted=move),
            "legal_move_count": len(legal),
        }

    if parsed not in board.legal_moves:
        legal = list(board.legal_moves)
        return {
            "ok": False,
            "reason": f"{move!r} parsed but is not legal in this position.",
            "to_move": _side(board),
            "alternatives": _alternatives(board, attempted=move),
            "legal_move_count": len(legal),
        }

    san_out = board.san(parsed)
    uci_out = parsed.uci()
    board.push(parsed)
    return {
        "ok": True,
        "san": san_out,
        "uci": uci_out,
        "fen_after": board.fen(),
        "status": get_game_status(board),
        "side_to_move": _side(board),
    }


def list_legal_moves(fen: str, from_square: str | None = None) -> dict[str, Any]:
    try:
        board = chess.Board(fen)
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid FEN: {e}"}]}

    moves: Iterable[chess.Move] = board.legal_moves
    if from_square:
        try:
            from_sq = chess.parse_square(from_square)
        except ValueError:
            return {"isError": True, "content": [{"type": "text", "text": f"Invalid from-square: {from_square!r}"}]}
        moves = [m for m in moves if m.from_square == from_sq]

    formatted = [{"san": board.san(m), "uci": m.uci()} for m in moves]
    return {
        "to_move": _side(board),
        "status": get_game_status(board),
        "count": len(formatted),
        "moves": formatted,
    }


def parse_pgn(pgn_text: str) -> dict[str, Any]:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return {"isError": True, "content": [{"type": "text", "text": "Could not parse PGN data."}]}

    board = game.board()
    moves: list[str] = []
    for move in game.mainline_moves():
        moves.append(board.san(move))
        board.push(move)

    return {
        "ok": True,
        "headers": dict(game.headers),
        "moves": moves,
        "final_fen": board.fen(),
        "status": get_game_status(board),
        "to_move": _side(board),
    }


@dataclass
class HistoryStep:
    san: str
    fen_after: str


def apply_move_history(moves: list[str], initial_fen: str = chess.STARTING_FEN) -> dict[str, Any]:
    try:
        board = chess.Board(initial_fen)
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid initial FEN: {e}"}]}

    applied: list[str] = []
    for move_str in moves:
        try:
            parsed = _parse_move(board, move_str)
        except ValueError:
            return {
                "ok": False,
                "reason": f"Move {move_str!r} is unparseable at ply {len(applied) + 1}.",
                "last_valid_fen": board.fen(),
                "moves_completed": applied,
            }
        if parsed not in board.legal_moves:
            return {
                "ok": False,
                "reason": f"Move {move_str!r} is illegal at ply {len(applied) + 1}.",
                "last_valid_fen": board.fen(),
                "moves_completed": applied,
            }
        applied.append(board.san(parsed))
        board.push(parsed)

    return {
        "ok": True,
        "fen": board.fen(),
        "status": get_game_status(board),
        "moves": applied,
    }


def board_svg(fen: str, *, flipped: bool = False) -> dict[str, Any]:
    try:
        board = chess.Board(fen)
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid FEN: {e}"}]}
    return {
        "type": "image/svg+xml",
        "content": chess.svg.board(board, flipped=flipped),
    }
