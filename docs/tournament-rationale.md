# Research Rationale: The Baseline Tournament Phase

This document outlines the scientific objectives of the initial tournament sweep. This phase serves as the **Discovery & Validation Layer** before escalating to university-scale compute.

## 1. Internal Board Representation (IBR) Analysis
Before modeling human intuition, we must identify which Large Language Models (LLMs) possess a high-fidelity internal board state. 
*   **The Probe**: Identifying the "Fluency Floor."
*   **Metric**: Rate of illegal move proposals and "hallucinated" piece coordinates in move rationales.
*   **Goal**: Filter for models that understand the *language* of chess well enough to serve as a reliable System 1.

## 2. The "Malleability vs. Rigidity" Threshold
We hypothesize that the strongest models (SOTA Oracles) may be too rigid to simulate human-like skill degradation, as they are hard-coded for perfection.
*   **The Probe**: Measuring "Instruction Sensitivity."
*   **Metric**: The degree to which a model respects the `PlayerProfile` constraints (e.g., an aggressive 1200-rated player) vs. defaulting to its pre-trained "best" move.
*   **Goal**: Identify the "Sweet Spot" candidate: high fluency but high behavioral malleability.

## 3. Establishing the "Zero-Shot" Blunder Baseline
To prove our Neuro-Symbolic engine creates a "more human" error distribution, we must first establish the "Control Group."
*   **The Probe**: Mapping the "Natural Blunder Profile."
*   **Metric**: Average Centipawn Loss (ACPL) and blunder categorization (Random Noise vs. Tactical/Aggressive Over-extension).
*   **Goal**: Create a baseline of un-modified LLM play to compare against our future "Fine-tuned + Triggered" versions.

## 4. Operational Integrity (Lab Readiness)
This tournament serves as the "Stress Test" for the research infrastructure before requesting heavy compute resources.
*   **The Probe**: Engineering validation.
*   **Metric**: Loop stability, `chess_core` guardrail effectiveness, and MCP server latency.
*   **Goal**: Prove the "Telescope" is built and functional. University compute will be used for "Observation," not "Debugging."

## 5. Quantification of the "Identity Refusal" Rate
Current base models occasionally default to their "AI Assistant" identities, refusing to play or providing generic disclaimers.
*   **The Probe**: Measuring "Cognitive Dissonance."
*   **Metric**: Percentage of "Identity Refusals" necessitating engine-forced random fallbacks.
*   **Goal**: Quantify the necessity for model-weight fine-tuning. This data directly justifies the "Ask" for compute to move beyond prompting and into dedicated behavioral weights.
