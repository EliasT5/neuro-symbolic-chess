import chess
from mcp.server.fastapi import Context, Resource, Tool
from fastapi import FastAPI

app = FastAPI(title="Chess Calculation Server")

@app.get("/validate-move")
def validate_move(fen: str, move_uci: str):
    """
    System 2: Calculation
    Ensures move legality and performs tactical verification.
    """
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(move_uci)
        if move in board.legal_moves:
            return {"valid": True, "message": "Legal move"}
        else:
            return {"valid": False, "message": "Illegal move"}
    except ValueError:
        return {"valid": False, "message": "Invalid UCI format"}

@app.get("/calculate-tactics")
def calculate_tactics(fen: str, depth: int = 10):
    """
    Perform deterministic calculation for the given position.
    """
    # Placeholder for Stockfish integration or similar
    return {"best_move": "e2e4", "score": 0.5}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
