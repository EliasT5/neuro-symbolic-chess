"""
Neuro-Symbolic Chess — MCP Server (System 2: Calculation & Guardrails).

Exposes the chess.* tool surface that mirrors Jerome's broker, so any
MCP-aware client (Claude Code, Inspector, the LLM engine in this repo)
can verify legality, list moves, parse PGNs, and render boards without
ever risking an illegal play.

Run as:
    python mcp-server/server.py             # stdio transport (for MCP clients)
    python mcp-server/server.py --http      # HTTP transport on :8000

The pure logic lives in `chess_core.guardrails`. This file is just the
MCP/HTTP wrapper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# Make the repo root importable so `chess_core` resolves whether the
# server is launched from the repo root or from inside `mcp-server/`.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from chess_core import guardrails  # noqa: E402

mcp = FastMCP("neuro-symbolic-chess")


@mcp.tool(name="chess.move", description="Verify a chess move against a FEN; on legality, return the resulting FEN, status, SAN/UCI. On failure, return up to 6 legal alternatives.")
def chess_move(fen: str, move: str) -> dict:
    return guardrails.apply_move(fen, move)


@mcp.tool(name="chess.legal_moves", description="List the legal moves available in a position. Optionally restrict to moves leaving a single from-square.")
def chess_legal_moves(fen: str, from_square: Optional[str] = None) -> dict:
    return guardrails.list_legal_moves(fen, from_square=from_square)


@mcp.tool(name="chess.parse_pgn", description="Parse a PGN string and return headers, the SAN move list, and the final FEN.")
def chess_parse_pgn(pgn: str) -> dict:
    return guardrails.parse_pgn(pgn)


@mcp.tool(name="chess.get_fen_from_moves", description="Replay a sequence of SAN/UCI moves from an initial FEN (default: standard start) and return the resulting FEN.")
def chess_get_fen_from_moves(moves: list[str], initial_fen: Optional[str] = None) -> dict:
    return guardrails.apply_move_history(moves, initial_fen=initial_fen or "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


@mcp.tool(name="chess.board_svg", description="Render a position as an SVG board for the given FEN.")
def chess_board_svg(fen: str, flipped: bool = False) -> dict:
    return guardrails.board_svg(fen, flipped=flipped)


def _run_http(host: str, port: int) -> None:
    """Optional HTTP transport — useful for curl-debugging the same surface."""
    from fastapi import FastAPI
    from pydantic import BaseModel
    import uvicorn

    app = FastAPI(title="Neuro-Symbolic Chess (HTTP transport)")

    class MoveReq(BaseModel):
        fen: str
        move: str

    class LegalReq(BaseModel):
        fen: str
        from_square: Optional[str] = None

    class PgnReq(BaseModel):
        pgn: str

    class HistoryReq(BaseModel):
        moves: list[str]
        initial_fen: Optional[str] = None

    @app.post("/tools/chess.move")
    def _move(req: MoveReq):
        return guardrails.apply_move(req.fen, req.move)

    @app.post("/tools/chess.legal_moves")
    def _legal(req: LegalReq):
        return guardrails.list_legal_moves(req.fen, from_square=req.from_square)

    @app.post("/tools/chess.parse_pgn")
    def _pgn(req: PgnReq):
        return guardrails.parse_pgn(req.pgn)

    @app.post("/tools/chess.get_fen_from_moves")
    def _hist(req: HistoryReq):
        return guardrails.apply_move_history(req.moves, initial_fen=req.initial_fen or "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    @app.get("/tools/chess.board_svg")
    def _svg(fen: str, flipped: bool = False):
        return guardrails.board_svg(fen, flipped=flipped)

    uvicorn.run(app, host=host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Neuro-Symbolic Chess MCP server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP server instead of stdio MCP")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.http:
        _run_http(args.host, args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
