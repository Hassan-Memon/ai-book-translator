# ADR-0001: Record architecture decisions
Date: 2026-11-02 · Status: accepted

## Context
This project is built by one engineer over 12 weeks and will be read by hiring managers who want
to know *why* things are the way they are, not just *what* they are. Decisions made in a hurry are
forgotten in a week and are impossible to defend in a review.

## Decision
Every decision that someone could reasonably have made differently gets a short ADR in
`docs/adr/`, numbered sequentially, written at the time of the decision.

## Alternatives considered
- Comments in code — scattered, no context, no alternatives recorded.
- A single DECISIONS.md — becomes a wall of text; hard to supersede entries.

## Consequences
- Slightly more writing per change (5–10 minutes).
- The README "Decisions" section can simply link here.
- The answer to "why X and not Y" is already written down.
