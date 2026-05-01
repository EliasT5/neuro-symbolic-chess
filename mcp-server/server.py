import chess
import chess.svg
import json
from mcp.server.fastapi import Context, Resource, Tool
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

app = FastAPI(title="Neuro-Symbolic Chess MCP Server")

class MoveRequest(BaseModel):
    fen: str = Field(..., description="FEN of the position before the move")
    move: str = Field(..., description="Proposed move in SAN, UCI or plain notation")

class LegalMovesRequest(BaseModel):
    fen: str = Field(..., description="FEN of the position")
    from_square: Optional[str] = Field(None, alias="from", description="Optional from-square ('e2'); restricts the list to moves leaving that square")

def get_game_status(board: chess.Board):
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient_material"
    if board.is_seventyfive_moves():
        return "draw_75_move"
    if board.is_fivefold_repetition():
        return "draw_fivefold_repetition"
    if board.is_check():
        return "check"
    return "normal"

@app.post("/tools/chess.move")
async def chess_move(request: MoveRequest):
    """
    Verify a chess move against a position and, if legal, return the resulting FEN.
    """
    try:
        board = chess.Board(request.fen)
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid FEN: {str(e)}"}]}

    try:
        # Try parsing as SAN first, then UCI
        try:
            move = board.parse_san(request.move)
        except ValueError:
            move = board.parse_uci(request.move)
    except ValueError:
        # If both fail, look for alternatives
        legal_moves = list(board.legal_moves)
        alternatives = [{"san": board.san(m), "uci": m.uci()} for m in legal_moves[:6]]
        return {
            "ok": False,
            "reason": f"'{request.move}' is illegal or unrecognized in this position.",
            "to_move": "white" if board.turn == chess.WHITE else "black",
            "alternatives": alternatives,
            "legal_move_count": len(legal_moves)
        }

    san_out = board.san(move)
    uci_out = move.uci()
    board.push(move)
    
    return {
        "ok": True,
        "san": san_out,
        "uci": uci_out,
        "fen_after": board.fen(),
        "status": get_game_status(board),
        "side_to_move": "white" if board.turn == chess.WHITE else "black"
    }

@app.post("/tools/chess.legal_moves")
async def chess_legal_moves(request: LegalMovesRequest):
    """
    List the legal moves available in a position.
    """
    try:
        board = chess.Board(request.fen)
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid FEN: {str(e)}"}]}

    moves = list(board.legal_moves)
    
    if request.from_square:
        try:
            from_sq = chess.parse_square(request.from_square)
            moves = [m for m in moves if m.from_square == from_sq]
        except ValueError:
            return {"isError": True, "content": [{"type": "text", "text": f"Invalid from-square: {request.from_square}"}]}

    formatted_moves = [{"san": board.san(m), "uci": m.uci()} for m in moves]
    
    return {
        "to_move": "white" if board.turn == chess.WHITE else "black",
        "status": get_game_status(board),
        "count": len(formatted_moves),
        "moves": formatted_moves
    }

@app.get("/tools/chess.board_svg")
async def chess_board_svg(fen: str):
    """
    Returns an SVG representation of the board for the given FEN.
    """
    try:
        board = chess.Board(fen)
        return {"type": "image/svg+xml", "content": chess.svg.board(board)}
    except ValueError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Invalid FEN: {str(e)}"}]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
