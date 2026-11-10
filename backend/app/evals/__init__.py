"""Evaluation harness (docs/EVALUATION.md).

Runs the *same* compiled chunk graph the worker uses over a hand-written
golden set and scores the output four ways: chrF++ against the human
reference, glossary adherence, structure preserved, and (optionally) an LLM
judge from a different model family. Results are written as JSON plus one
row in ``docs/evals/results/README.md``.

    uv run translatebook eval validate ../docs/evals/golden/starter-v1.jsonl
    uv run translatebook eval run --golden ../docs/evals/golden/starter-v1.jsonl \\
        --provider ollama --model aya-expanse:8b --judge-provider ollama --judge-model llama3.1:8b
"""
