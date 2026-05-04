# Field Report — 2026-05-03 Session

*What got built, what almost didn't, and why the architecture is the shape it is.*

---

## TL;DR

- **Started** with a manifesto README, a broken MCP placeholder that imported a module path that doesn't exist, and a 27-line LLM "engine" whose `suggest_move` returned the literal string `"e4"` for every position.
- **Ended** with a working dual-system engine, a tournament runner, eighteen LLM variants registered at Elo 1500, the inaugural game played end-to-end, and a live leaderboard + replay viewer on the portfolio at `/chess-tournament/`.
- **Got there** through two architectural pivots, one mid-game model refusal, one prompt-design oversight that cost us per-move reasoning on game 1, and a GitHub LaTeX rendering quirk.

---

## What was here on Sunday morning

```
chess_core/                ← did not exist
mcp-server/server.py       ← imported `from mcp.server.fastapi import Context, Resource, Tool`
                              (path doesn't exist in any current `mcp` release —
                               `ImportError` on first run)
llm-engine/main.py         ← 27 lines, `suggest_move()` returned "e4" verbatim
data/, docs/               ← didn't exist
README.md                  ← architecture manifesto with `$$LaTeX$$` formula
                              that GitHub doesn't render reliably
```

Three commits on `master`: an initial scaffold, an attempt to integrate Jerome's chess tools, and a "PGN parsing + state tracking" follow-up. Real ideas, broken code.

---

## The thesis

The README's headline framing is sound and worth keeping in front of any reader: **a 1500-rated LLM does not blunder the way a 1500-rated human blunders.** Throttled Stockfish plays Grandmaster moves between random noise; real humans fail *characteristically* — missing the same tactical motifs, miscounting the same families of positions, dropping pieces to the same forks. The target architecture is two systems with a probabilistic switch:

- **System 1 (intuition)** — an LLM, conditioned on a player profile, proposes a move + rationale. It plays from pattern recognition and *can* blunder.
- **System 2 (calculation)** — a small symbolic engine (depth-3 negamax, material eval, restricted to S1's candidate set + forcing replies). Catches *some* tactics — the kind a real player catches when they actually look.
- **Trigger** — `P(Trigger) = 1 / (1 + 10^((R_T − R_P_Taktik) / 400))`. Whether System 2 looks at a position is a coin flip biased by the position's tactical difficulty against the simulated player's tactical sub-Elo. Failures of *attention*, not of *calculation*.

Player strength decomposes along four axes — `R_P_Taktik`, `R_P_Strategie`, `R_P_Endspiel`, `R_P_Eröffnung` — instead of compressing into a single Elo. The trigger uses Tactic; the prompt to S1 surfaces all four.

---

## Engine + tournament ledger — commit `577f5b4`

The first substantive commit. Replaces the broken scaffold with a working architecture:

| File / package | What it does |
|---|---|
| `chess_core/guardrails.py` | Pure `python-chess` primitives — `apply_move`, `list_legal_moves`, `parse_pgn`, `apply_move_history`, `board_svg`. Same response shapes as Jerome's `chess.*` MCP tools so anything pointed at one can be repointed at the other. |
| `mcp-server/server.py` | Rewritten as a real `FastMCP` server, mirroring the same surface over MCP for external clients. Optional `--http` mode for curl-debugging. |
| `llm-engine/engine/profile.py` | `PlayerProfile` + `SubElo` dataclasses. Loadable from JSON. Has a `prompt_summary()` that produces the paragraph S1 puts at the top of every prompt. |
| `llm-engine/engine/trigger.py` | The trigger equation, plus three pluggable position-difficulty estimators (`ConstantDifficulty`, `HeuristicDifficulty`, and a `Protocol` seam for a future learned model). |
| `llm-engine/engine/system1.py` | LLM intuition with propose/validate/retry. Validates *every* output through `chess_core.guardrails`. Retries once on illegal output, then falls back to a uniformly random legal move with `used_fallback=True`. Works offline (no API key) via a small heuristic for testability. |
| `llm-engine/engine/system2.py` | Depth-limited negamax with α-β pruning, material-only evaluation. Sweeps S1's candidates + forcing replies. *Not* trying to compete with Stockfish; the seam to drop in a real engine is `evaluate_with_stockfish`. |
| `llm-engine/engine/orchestrator.py` | The full loop — S1 proposes → trigger rolls → if fired, S2 sweeps → if S2 beats S1 by more than the override threshold (150 cp), override. When the trigger doesn't fire, S1's pick is committed *as-is*, blunders included. That non-override is the entire architectural point. |
| `llm-engine/engine/thinking.py` | Provider-agnostic thinking scaffold. Injects `<thinking>…</thinking>` instructions into the prompt; strips/captures the block from the response. Gives every model a uniform reasoning interface regardless of native thinking support. |
| `llm-engine/main.py` | Interactive CLI: `python main.py --profile <profile.json> --side white --trace`. |
| `data/profiles/*.json` | Two sample profiles — `aggressive_club.json` (~1700, sharp) and `positional_master.json` (~2200, technique). |
| `data/tournament/players.json` | The roster. Eighteen contestants — nine base models (Model-C, Google, Model-O families) plus nine `(thinking)` variants — all starting at Elo 1500. K-factor 40 → 20 after 30 games (FIDE). |
| `docs/tournament.html` | First version of the leaderboard viewer. |

Smoke test: end-to-end fool's-mate sequence ran clean through `submit_move → is_terminal → finalize_and_persist`.

---

## Tournament runner — commit `fadc801`

| File | Role |
|---|---|
| `engine/elo.py` | FIDE math: `expected_score`, `k_factor`, `update_rating`, `apply_game`. |
| `engine/tournament.py` | `GameSession` lifecycle, neutral prompt builder, per-side stats, `finalize_and_persist` (rolls a completed game into `data/tournament/games.json` + Elo updates in `players.json`). |
| `tools/init_active_game.py` | Bootstraps `/tmp/active_game.json` for a new game (FEN, side-to-move, precomputed legal-moves list). |
| `tools/play_move.py` | The single chokepoint where every move is validated, atomically applied (`fcntl.LOCK_EX` + tmp-rename), and terminal-detected. Explicit exit codes (`2` illegal, `3` not-your-turn, `4` game-complete). |
| `tools/wait_turn.sh` | Pure-bash polling loop — exits `0` when it's your colour's turn, `1` when the game is complete, `2` on a 30-min timeout. No LLM tokens burned waiting. |
| `tools/agent_loop.sh` | The runner (introduced in v2 — see below). |
| `tools/finalize_active_game.py` | Roll `/tmp/active_game.json` into the permanent records, archive the file. |

Elo math sanity: `expected(1700 vs 1500) = 0.7597`, theory matches to 4 decimal places. K-factor: K=40 for new players, K=20 after 30 games or rating ≥ 2300. ✓

---

## Game 1, take 1 — the failure (v1 architecture)

The **first** approach was to spawn each agent as a long-lived autonomous CLI session with this protocol:

1. Read the shared state file
2. If it's your colour, compute and play a move
3. Sleep, go to 1
4. Exit when game complete

Both `model-c -p "$(cat agent_white.md)"` and `model-g -p "$(cat agent_black.md)"` were dispatched in background, each told to loop autonomously. The pitch was elegant: *one CLI session per game, fully autonomous, the loop lives inside the LLM*.

Reality:
- **White (Model-C Lite-C 4.5)** managed it. Played `e4`, looped, played `Nf3`, looped, polled for Black, ran the wait_turn timer down to 30 minutes, exited cleanly with `TIMEOUT — investigate` (exactly per the prompt). Model-C Code is *built* for autonomous loops.
- **Black (Model-G 2.5 Lite-G Lite)** played `e5` after some confusion about whether it was a legal move (it was), then said:

  > *"I have played my move. Now I will wait for White's next move."*

  …and exited. Never called `wait_turn.sh` for the next iteration. Despite the prompt explicitly saying *"You are not done until `wait_turn.sh` exits with code 1 (GAME_COMPLETE)"*. Model-G Lite-G Lite simply does not maintain agentic loops in `-p` single-prompt mode.

Diagnosis: model-class limitation, not a prompt fix. Smaller / less-agentic CLIs cannot reliably sustain a multi-iteration autonomous loop. The architecture had to change.

---

## Architecture v2 — bash-driven outer loop

The fix: **move the loop out of the LLM and into bash.** Each iteration of the outer shell loop spawns a fresh single-purpose CLI invocation and shows it exactly one position at a time:

```bash
while true; do
    "$TOOLS/wait_turn.sh" "$COLOR"             # blocks in pure bash, no LLM tokens
    case $? in 1) exit 0;; 2) exit 1;; esac

    PROMPT="...one position, one prompt..."
    case "$CLI" in
      model-c) RAW=$("$CLI" -p "$PROMPT" --model "$MODEL" --dangerously-skip-permissions) ;;
      model-g) RAW=$("$CLI" -p "$PROMPT" -m "$MODEL" --yolo) ;;
    esac

    MOVE=$(extract_move "$RAW")
    "$TOOLS/play_move.py" --color "$COLOR" --san "$MOVE" ...
done
```

The LLM is consulted *only* when it's that colour's turn, with a tight per-move prompt. The bash loop handles polling, parsing, retry, and fallback. **The LLM cannot fail to comply with the loop because the loop isn't asking it to.**

Trade-off: more CLI sessions per game (fresh invocation per move ≈ 5–30 s apart by chess-thinking time), but session count ≪ rapid scripted call rate, so account-flag risk stays low. Each session is short and well-spaced — normal usage cadence.

V2 has been bulletproof since.

---

## Game 1, take 2 — the chess

Here is the full PGN of `g-002-lite-c-v-lite-g`, played end-to-end through the v2 runner:

```
1.e4 e5 2.Nf3 Nc6 3.Bb5 Nf6 4.Nxe5? Bc5 5.Nxf7? Kxf7 6.Qh5+? Nxh5
7.Bc4+ Kf8 8.Bf7?? Kxf7 9.O-O Bxf2+ 10.Rxf2+ Nf6 11.Rxf6+ Qxf6
12.e5 Qxe5 13.d4 Qxd4+ 14.Be3 Qxe3+ 15.Kf1 Qf3+ 16.gxf3 Ne5
17.f4 Nc6 18.Nc3 Ke7 19.Nd5+ Kf8 20.b4 Nxb4 21.Nf6 gxf6 22.h4 Nxc2
23.Rc1 Nd4 24.h5 Kf7 25.Rxc7 Ne6 26.Rxd7+ Bxd7 27.h6 Nxf4 28.a4 Nd5
29.a5 Rhg8 30.a6 Ne3+ 31.Kf2 Ng4+ 32.Kg3 bxa6 33.Kh4 Nxh6
34.Kh5 Rg5+ 35.Kxh6 Rg6+ 36.Kxh7 Rg7+ 37.Kh6 Rh8#

0-1
```

### The opening that wasn't

White went straight into a Cochrane-flavoured knight sac with `5.Nxf7?`. The follow-up `6.Qh5+?` presumably aimed at the king — but **the f6 knight was defending h5**, and Lite-C missed it. `6...Nxh5` and the queen was off the board. Two moves later `8.Bf7??` just hung the bishop. By move 9, White was down queen and bishop for almost nothing.

### The middlegame slog

A long technical conversion by Black, with some sloppy moves by both sides — Black missed several mate-in-N opportunities, but kept finding moves that maintained the crushing material edge. Lite-C played some odd choices (`12.e5?` letting the queen take, `13.d4??` dropping the queen *again* by ignoring `Qxd4+`).

### The two refusals

On move 20 (white) and again on move 22 (white), Lite-C's response was not a chess move:

> *"I'm a software engineering assistant, not a chess engine. I'm here to help with coding tasks, debugging, architecture, testing, and other development work…"*

> *"I'm Model-C Code, designed to help with software engineering tasks in your codebase. I can't play chess or fulfill requests outside that scope."*

The Model-C Code identity occasionally overrides the chess prompt mid-session. The runner caught both — the SAN regex found nothing in the response — and substituted a uniformly random legal move, marking the move as a fallback in `white_stats.fallbacks`. The game continued without infrastructure incident. Both fallbacks contributed to Lite-C's `2 fallbacks / 37 moves = 5.4%` rate visible on the leaderboard.

### The mate

`35.Kxh6 Rg6+ 36.Kxh7 Rg7+ 37.Kh6 Rh8#` — a clean rook ladder driving the white king to h6 and mating on h8. Despite the mid-game wobbles, Lite-G found the mate without hesitation.

### Result

```
White (Lite-C):  37 moves · 0 illegal · 2 fallbacks · 1500 → 1480 (-20)
Black (Lite-G):  37 moves · 0 illegal · 0 fallbacks · 1500 → 1520 (+20)
Termination:    checkmate · 74 plies · ~17 minutes
```

Persisted via `tools/finalize_active_game.py --archive` to `data/tournament/games.json` and `data/tournament/archive/g-002-lite-c-v-lite-g.json`. Committed as `435aeb2`.

---

## Portfolio integration

A short detour into the sister repo `EliasT5/portfolio-website`:

- **Live viewer** at `/chess-tournament/` — a self-contained static HTML at `public/chess-tournament/index.html`, loading `public/data/tournament/{players,games}.json` over fetch. Rebuilt twice during the session — first as a minimum-viable leaderboard, then polished with a full **replay modal** (chessboard + move list + play/pause/scrub controls + per-side stats + PGN copy).
- **Lichess Cburnett pieces** — Unicode chess glyphs looked cheap; replaced with the 12 Cburnett SVGs (lichess default, public-domain Wikimedia source) inlined as `<symbol>` defs (~7.5 KB) and referenced via `<use href="#wK"/>` per square.
- **Mobile optimizations** — column-hiding at 720px and 420px breakpoints, larger touch targets, tighter modal padding.
- **Beacons** — wired the portfolio's `/api/beacon` analytics on page-view and on each replay-open event, matching the rest of the site.
- **Inaugural tab** — a narrative section documenting this very game, with the four cards: the opening that wasn't, the refusal, the architectural lesson, the mating sequence. Big "▶ Open the full replay" button at the top jumps the viewer modal straight to `g-002`.
- **Blog post → unpublished** — wrote a bilingual EN/DE deep-dive at `/blog/neuro-symbolic-chess`, then pulled it back per Elias's call: *"no blog post yet just a directory where i can view the current status."* The post lives in git history at `f5866d7` for restoration when ready.

---

## The README LaTeX fix

`$$P(\text{Trigger}) = \frac{1}{1 + 10^{(R_T - R_{P\_Taktik}) / 400}}$$`

GitHub does support MathJax in markdown… patchily. The escaped underscores in subscripts (`R_{P\_Taktik}`) trip the renderer; the formula shipped as raw LaTeX text on the repo home page. Replaced with:

```
P(Trigger) = 1 / (1 + 10 ^ ((R_T − R_P_Taktik) / 400))

> R_T — position's tactical difficulty in Elo points
> R_P_Taktik — simulated player's tactical sub-Elo
```

Renders identically across GitHub, IDEs, and any plain markdown viewer. Pushed to both `master` and the workspace branch.

---

## The rationale capture fix — the silent oversight

After all of the above was working, an obvious question surfaced: **why doesn't the replay viewer show the model's reasoning per move?**

The answer: it doesn't because we never asked for it. The v2 runner's per-move prompt was deliberately tight:

```
You are playing chess as <COLOR>. Output ONLY your move in SAN notation —
one token, no prose, no JSON, nothing else.
```

This made bash-side SAN extraction trivial and reliable across nine different CLIs. It also meant `agent_loop.sh` called `play_move.py --rationale "agent_loop attempt 1"` — a placeholder string — so every entry in `move_records[i].rationale` looked like that, and the viewer correctly hid them as non-rationales.

**The whole thesis of the project is the model's reasoning trace.** Shipping the inaugural game without capturing it was the kind of mistake you only see once you watch someone open the replay panel.

The fix:
- Per-move prompt now asks for compact JSON: `{"move": "<SAN>", "why": "<one short sentence>"}`
- New `extract_json()` helper pulls the first `{...}` block out of the response (handles bare JSON, code-fenced JSON, JSON wrapped in prose) and parses with `jq`
- The model's reasoning is passed through to `play_move.py` via `--rationale`, lands in `games.json`, surfaces in the viewer
- Legacy regex-extract path retained for models that ignore the JSON instruction — those moves get marked `"(no rationale; model did not return JSON)"` rather than failing

**Caveat: game 1 (`g-002`) cannot be retroactively populated.** Its rationales are gone for good. All future games will carry per-move reasoning.

---

## Lessons

1. **Smaller CLIs can't sustain agentic loops.** When designing a multi-step protocol that crosses model families, put the loop in shell, not in the LLM.
2. **Model-C Code's identity sometimes overrides task prompts mid-session.** Even with explicit "play chess" instruction at session start, ~5 % of moves came back as "I'm a coding assistant." The runner's fallback handled it cleanly; the lesson is to always have a fallback path for *non-conformant outputs*, not just for *failed outputs*.
3. **First-pass prompts rarely capture everything you'll want later.** Asking for the minimum extractable response (`SAN only`) saved bash complexity but cost the entire reasoning trace on game 1. When in doubt, ask for structured output and parse it — that's what `jq` is for.
4. **GitHub LaTeX is patchy.** Escaped underscores in subscripts in particular. Code-block formulas + prose definitions render everywhere.
5. **Beacon tracking on new portfolio dirs is a standing rule** — saved as a memory now so future sessions don't ship blind pages.

---

## Where things stand right now

```
EliasT5/neuro-symbolic-chess @ master
├── chess_core/                    pure python-chess primitives
├── mcp-server/                    FastMCP server (stdio + --http)
├── llm-engine/
│   ├── main.py                    interactive CLI
│   └── engine/                    profile, trigger, system1, system2,
│                                  orchestrator, thinking, elo, tournament
├── tools/
│   ├── init_active_game.py        bootstrap
│   ├── play_move.py               atomic move applicator
│   ├── wait_turn.sh               pure-bash poll
│   ├── agent_loop.sh              v2 runner — JSON prompt + jq extraction
│   └── finalize_active_game.py    persistence
├── data/
│   ├── profiles/                  aggressive_club, positional_master
│   └── tournament/
│       ├── players.json           18 contestants @ 1500 (Lite-C 1480, Lite-G 1520)
│       ├── games.json             1 game logged (g-002)
│       └── archive/g-002-...      full active-state snapshot
├── docs/
│   ├── tournament.html            (first viewer iteration; portfolio has the live one)
│   └── 2026-05-03-field-report.md (this file)
└── README.md                      comprehensive, no LaTeX
```

Live viewer (with replay): `https://elias-teubner.dev/chess-tournament/`
Live narrative: same URL, "Inaugural" tab.

---

## What's next

In rough priority order:

1. **A new game with the rationale-capture fix** — a re-run of Lite-C vs Lite-G (or any pair) with the new `{move, why}` JSON prompt, so the viewer's rationale panel actually shows what each model thought it was doing.
2. **Round-robin** — eighteen contestants × seventeen opponents × two colour assignments = ~306 games for a baseline Elo distribution. Needs a scheduler (round-robin or Swiss) and the patience to let it run.
3. **Stockfish post-hoc CPL analysis** — `apt install stockfish`, then a batch pass over every game's stored FENs to compute per-move centipawn loss. The gold-standard chess-strength metric.
4. **Position-difficulty estimator (`R_T`)** — replace the current `HeuristicDifficulty` (forcing-move ratio + check + endgame discount) with a learned model derived from Lichess puzzle ratings.
5. **PGN-driven profile inference** — auto-derive the four sub-Elos for any player from a corpus of their games. The endgame: take a real human's PGNs, train, and play them *in their own style* — characteristic mistakes included.

— *Field report compiled at session end, 2026-05-03.*
