"""Shared LLM construction for AlphaDesk agents.

Two families of agent live in this repo and they must never share a model:

- **The Lab pipeline** (`agents/scanner`, `research`, `analyst`, `risk_manager`,
  `execution`) runs on **Groq**, tiered per agent. These callers pass no
  ``provider`` and get the env-selected default, which is Groq.
- **The portfolio overview** (`agents/portfolio/*`, card A1) runs on **OpenAI**
  and says so explicitly: ``get_chat_llm(model, provider="openai")``.

``provider`` is authoritative and **wins over the environment**. This is a hard
requirement of card A1 (plan §9): the stray v1 leftover ``OPENAI_COMPATIBLE_MODEL``
must never reroute either family. Two things make that true:

1. ``provider="openai"`` pins the official OpenAI endpoint
   (``https://api.openai.com/v1``) even when ``OPENAI_BASE_URL`` points somewhere
   else — the underlying ``openai`` client reads ``OPENAI_BASE_URL`` from the
   environment, so a bare ``ChatOpenAI(model=...)`` would silently follow a
   compat endpoint. We pass the base URL explicitly to defeat that.
2. In the **default** (``provider is None``) path, OpenAI-compatible mode is
   enabled **only** by ``OPENAI_BASE_URL`` — a real endpoint. A lone
   ``OPENAI_COMPATIBLE_MODEL`` (the model name a compat endpoint would serve) is
   inert without a base URL, so the leftover in a dev ``.env`` cannot reroute the
   Lab agents to a compat endpoint or collapse their per-agent tiering. This is a
   deliberate tightening of the v1 "set either var" contract, whose whole point
   in v2 is that these vars stay unset in production (plan §9).

``OPENAI_API_KEY`` is read from the environment by ``ChatOpenAI`` for the OpenAI
and compat providers. Never construct a chat model directly in an agent — go
through this helper.
"""

from __future__ import annotations

import os
from typing import Any, Literal, Optional

#: The canonical OpenAI endpoint. Pinned for ``provider="openai"`` so a stray
#: ``OPENAI_BASE_URL`` in the environment cannot redirect a portfolio call.
OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"

Provider = Literal["openai", "groq", "compat"]


def _chat_openai(
    model: str, temperature: float, base_url: Optional[str], timeout: Optional[float]
) -> Any:
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOpenAI(**kwargs)


def _chat_groq(model: str, temperature: float) -> Any:
    from langchain_groq import ChatGroq

    return ChatGroq(model=model, temperature=temperature)


def get_chat_llm(
    default_model: str,
    *,
    temperature: float = 0,
    provider: Optional[Provider] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Return a chat model, routing by explicit ``provider`` first, then env.

    Args:
        default_model: The model name to use (a Groq model for the Lab, an
            OpenAI model for the portfolio overview).
        temperature: Sampling temperature.
        provider: Explicit routing, and it **wins over the environment**:

            - ``"openai"`` — real OpenAI (`api.openai.com`), regardless of
              ``OPENAI_BASE_URL`` / ``OPENAI_COMPATIBLE_MODEL``. This is what the
              portfolio agents pass.
            - ``"groq"`` — Groq, regardless of env.
            - ``"compat"`` — an OpenAI-compatible endpoint from
              ``OPENAI_BASE_URL`` (required) + ``OPENAI_COMPATIBLE_MODEL``.
            - ``None`` — env-selected default: compat **iff** ``OPENAI_BASE_URL``
              is set, otherwise Groq. A lone ``OPENAI_COMPATIBLE_MODEL`` is inert
              here, so the Lab keeps running Groq even when that leftover is set.
        timeout: Per-request timeout (seconds) for the OpenAI/compat paths, so a
            stalled connection fails fast instead of hanging. Ignored for Groq.
    """
    if provider == "openai":
        # Pin the official endpoint so a stray OPENAI_BASE_URL cannot redirect
        # this call, and use exactly the model asked for — never the compat
        # model name, which belongs to a different endpoint entirely.
        return _chat_openai(default_model, temperature, OPENAI_OFFICIAL_BASE_URL, timeout)

    if provider == "groq":
        return _chat_groq(default_model, temperature)

    if provider == "compat":
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if not base_url:
            raise ValueError(
                "provider='compat' needs OPENAI_BASE_URL set to the compatible "
                "endpoint's base URL."
            )
        model = os.environ.get("OPENAI_COMPATIBLE_MODEL", "").strip() or default_model
        return _chat_openai(model, temperature, base_url, timeout)

    # provider is None: env-selected default. Compat mode requires a real
    # endpoint (OPENAI_BASE_URL). OPENAI_COMPATIBLE_MODEL alone does NOT switch
    # provider — that is the v1 leftover A1 refuses to let reroute the Lab.
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if base_url:
        model = os.environ.get("OPENAI_COMPATIBLE_MODEL", "").strip() or default_model
        return _chat_openai(model, temperature, base_url, timeout)

    return _chat_groq(default_model, temperature)


__all__ = ["OPENAI_OFFICIAL_BASE_URL", "get_chat_llm"]
