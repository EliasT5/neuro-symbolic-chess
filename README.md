# Neuro-Symbolic Chess AI

An innovative approach to simulating personalized chess playing styles using a neuro-symbolic LLM architecture.

## Overview

Traditional chess engines (like Stockfish) are optimized for mathematical perfection, often leading to the **"Drunken Robot Syndrome"** when throttled — playing at Grandmaster levels and then making unmotivated blunders to lower their win rate. This project aims to create a more human-like sparring partner by mimicking human cognitive processes through a dual-system architecture.

## Architecture

```
                  ┌──────────────────────────┐
                  │    PlayerProfile         │
                  │  (Elo decomposition,     │
                  │   style, repertoire)     │
                  └──────────────┬───────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌────────────────┐      ┌────────────────┐      ┌──────────────────┐
│  System 1      │      │ Tactic Trigger │      │   System 2       │
│  (Intuition)   │─────▶│   roll P(R_T,  │─────▶│  (Calculation)   │
│  LLM proposes  │      │   R_P_Taktik)  │ fire │  negamax sweep   │
│  + rationale   │      └────────────────┘      │  over candidates │
└───────┬────────┘                              └────────┬─────────┘
        │                                                │
        │      ┌─────────────────────────────────┐       │
        └─────▶│       NeuroSymbolicEngine       │◀──────┘
               │  reconcile, override if Δ>thr   │
               └────────────────┬────────────────┘
                                ▼
                ┌──────────────────────────────┐
                │  chess_core.guardrails       │
                │  (validate every move,       │
                │   shared with MCP server)    │
                └──────────────────────────────┘
```

### System 1: Intuition (`llm-engine/engine/system1.py`)
- LLM (default: `gpt-4o-mini`, configurable via `NSC_LLM_MODEL`).
- Prompted with the profile, FEN, recent moves, and the legal-move list.
- Returns SAN + one-sentence rationale + up to 3 alternatives considered.
- All output is validated by the guardrails; one retry on illegal output, then a flagged fallback to a uniformly random legal move.
- Works offline (without `OPENAI_API_KEY`) via a small heuristic — useful for tests.

### System 2: Calculation (`llm-engine/engine/system2.py`)
- Depth-limited negamax with alpha-beta pruning, material-only evaluation.
- Sweeps S1's candidate set + all forcing replies (captures, checks).
- Default depth: 3 plies. Catches hangs and basic tactics; **does not** try to compete with Stockfish.
- A `evaluate_with_stockfish` seam is provided for future drop-in.

### Stochastic Tactic Trigger (`llm-engine/engine/trigger.py`)
The probability that System 2 gets to look at a given position:

$$P(\text{Trigger}) = \frac{1}{1 + 10^{(R_T - R_{P\_Taktik}) / 400}}$$

- Easy tactic vs strong tactician → trigger always fires.
- Hard tactic vs weak tactician → trigger usually doesn't fire, blunder happens organically.
- The position-difficulty estimator `R_T` is pluggable: `ConstantDifficulty`, `HeuristicDifficulty` (the default — bumps difficulty for forcing positions), or your own.

### MCP Server: Guardrails (`mcp-server/server.py`)
A real `FastMCP` server exposing the same `chess.*` surface used internally by the engine. Mirrors Jerome's broker tools so external MCP clients (Claude Code, the MCP Inspector, anyone else) can use this repo as a chess legality oracle.

Tools exposed:
- `chess.move(fen, move)` — validate + apply, return `fen_after`/`status`/`alternatives`
- `chess.legal_moves(fen, from?)` — enumerate, optionally restricted to a from-square
- `chess.parse_pgn(pgn)` — headers + SAN list + final FEN
- `chess.get_fen_from_moves(moves, initial_fen?)` — replay from a position
- `chess.board_svg(fen, flipped?)` — SVG render

## Project Structure

```
.
├── chess_core/                 # shared guardrail primitives (pure python-chess)
│   └── guardrails.py
├── mcp-server/
│   └── server.py               # FastMCP wrapper (stdio or --http)
├── llm-engine/
│   ├── main.py                 # interactive CLI: play vs a profile
│   └── engine/                 # the neuro-symbolic engine package
│       ├── profile.py          # PlayerProfile + Elo decomposition
│       ├── trigger.py          # P(Trigger) + difficulty estimators
│       ├── system1.py          # LLM intuition
│       ├── system2.py          # negamax calculation
│       └── orchestrator.py     # the full loop
├── data/
│   └── profiles/
│       ├── aggressive_club.json
│       └── positional_master.json
└── docs/
```

## Getting Started

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...        # optional; without it, S1 uses an offline heuristic

# Play a game (you are White, engine plays the aggressive club profile)
python llm-engine/main.py --profile data/profiles/aggressive_club.json --side white --trace

# Run the MCP server (stdio — for MCP clients)
python mcp-server/server.py

# Or run the same surface as HTTP for curl-debugging
python mcp-server/server.py --http --port 8000
```

## Status

This is a **scaffold**. The structure is real and end-to-end; the rough edges are honest:

- **System 1 prompting** is plain few-shot; quality will jump with a small fine-tune on the target player's PGNs (the Maia approach).
- **R_T estimation** is a heuristic. The next research step is a learned position-difficulty model (e.g. derived from Lichess puzzle ratings).
- **System 2** is intentionally minimal. Drop in Stockfish via the `evaluate_with_stockfish` seam when you want stronger calculation.
- **PGN-driven profile inference** (auto-deriving sub-Elos from a player's game corpus) is the natural next module.

---
*Based on the research paper: Neuro-symbolisches Schachtraining © 2024*
