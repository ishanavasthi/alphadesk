"""Portfolio AI overview (card A1).

The dashboard's narrative layer. Its one non-negotiable rule: **numbers are
computed deterministically in Python (`metrics.py`) and the agents may only
narrate verified metrics — never invent a figure.** The narrative is the only
part that needs the LLM; every computed number renders with or without it, so
the dashboard is complete even when the model is unavailable.

Modules:

- ``metrics``  — deterministic metric computation (the source of every number).
- ``redact``   — the prompt scrubber every LLM payload is routed through.
- ``narrative``— segment/paragraph types + figure-in-metric verification.
- ``agents``   — the four specialist prompts + the synthesizer.
- ``spend``    — the app-side daily spend ceilings (global + per user).
"""
