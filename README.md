# Neuro-Symbolic Chess AI

An innovative approach to simulating personalized chess playing styles using a neuro-symbolic LLM architecture.

## Overview

Traditional chess engines (like Stockfish) are optimized for mathematical perfection, often leading to the "Drunken Robot Syndrome" when throttled—playing at Grandmaster levels and then making unmotivated blunders to lower their win rate. This project aims to create a more human-like sparring partner by mimicking human cognitive processes through a dual-system architecture.

## Architecture

The system is divided into two main cognitive systems:

### System 1: Intuition (LLM Engine)
- **Role:** Pattern recognition and strategy planning.
- **Implementation:** Large Language Model (LLM) trained on specific opponent data (PGNs).
- **Goal:** Imitate the opponent's style, preferences, and opening repertoire.

### System 2: Calculation (MCP Server)
- **Role:** Deterministic calculation and tactical verification.
- **Implementation:** Model Context Protocol (MCP) Server.
- **Goal:** Provide a tactical sandbox to verify variations and ensure move legality without hallucinations.

## Key Mechanisms

### Elo Decomposition
Instead of a single Elo rating, the opponent's strength is broken down into sub-categories:
- **$R_{P\_Taktik}$:** Tactical strength in volatile positions.
- **$R_{P\_Strategie}$:** Precision in quiet, positional games.
- **$R_{P\_Endspiel}$:** Performance in material-reduced endgames.
- **$R_{P\_Eröffnung}$:** Depth and accuracy of opening theory.

### Stochastic Tactic Triggers
Human-like errors are simulated organically. For every move, the system probabilistically decides whether to trigger a tactical calculation (System 2) based on the difficulty of the pattern ($R_T$) and the simulated player's tactical Elo ($R_{P\_Taktik}$):

$$P(Trigger) = \frac{1}{1 + 10^{(R_T - R_{P\_Taktik}) / 400}}$$

If the trigger is not pulled, the system relies on the (potentially flawed) intuition of System 1.

### Guardrails & Explainability
- **MCP Server** ensures only legal moves are played.
- **LLM** provides natural language explanations for its moves based on the opponent's psychological profile (e.g., "I am avoiding the trade because my opponent is statistically stronger in the endgame").

## Project Structure

- `llm-engine/`: System 1 implementation (Intuition & Strategy).
- `mcp-server/`: System 2 implementation (Calculation & Guardrails).
- `data/`: Storage for PGNs, player profiles, and tactical datasets.
- `docs/`: Technical documentation and research papers.

## Getting Started

*(Instructions for setup and installation to be added)*

---
*Based on the research paper: Neuro-symbolisches Schachtraining © 2024*
