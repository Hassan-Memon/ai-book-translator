# ADR-0007: The evaluation judge is never from the translating model's family
Date: 2026-11-02 · Status: planned (the evaluation harness, `docs/EVALUATION.md`)

## Context
The evaluation harness will score translations with an LLM judge against human references. LLMs prefer text in their own style. A judge from the same family as the translator inflates scores in exactly the comparison we care about, and the v0.3 smoke test already showed an 8B reviewer giving 0.95 to its own family's flawed Arabic.

## Decision
The harness refuses a configuration where the judge and translator share a family (OpenAI, Anthropic, Google, Qwen, Llama, Gemma, Mistral, Cohere). Each results row records both models. The judge is calibrated once on the reference against deliberately degraded copies, and 10 verdicts are spot-checked by hand per milestone.

## Alternatives considered
- **Same-family judge for convenience**: cheaper, but biased in a known direction.
- **chrF or BLEU only**: unbiased but blind to omissions and register. Both are kept alongside the judge.
- **Human-only scoring**: the gold standard, but too slow to run after every change.

## Consequences
- Easier: numbers that hold up when a buyer or reviewer asks "who graded this?"
- Harder: at least two providers are needed to run the full harness.
