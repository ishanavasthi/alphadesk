"""Shared LLM construction for AlphaDesk agents.

Two families of agent live in this repo and they are configured independently:

- **The Lab pipeline** (`agents/scanner`, `research`, `analyst`, `risk_manager`)
  — a labelled simulation, tiered per agent. Configured by ``LAB_PROVIDER`` and
  ``LAB_MODEL`` / ``LAB_<AGENT>_MODEL``. With those unset it behaves exactly as
  before: the env-selected default, which is Groq at the historical per-agent
  tiers.
- **The portfolio overview** (`agents/portfolio/*`, card A1) — configured by
  ``OVERVIEW_PROVIDER`` and ``OVERVIEW_MODEL``. With those unset it behaves
  exactly as before: real OpenAI on ``gpt-4o-mini``.

Routing precedence, highest first:

1. An explicit ``provider=`` argument to :func:`get_chat_llm`. Authoritative.
2. The family's **own dedicated** env var (``OVERVIEW_PROVIDER`` /
   ``LAB_PROVIDER``), applied by :func:`get_overview_llm` / :func:`get_lab_llm`.
3. The ambient env default (compat iff ``OPENAI_BASE_URL``, else Groq).

**The A1 invariant survives the addition of (2).** Card A1 (plan §9) requires
that the stray v1 leftovers ``OPENAI_BASE_URL`` / ``OPENAI_COMPATIBLE_MODEL``
can never reroute either family. They still cannot:

- ``provider="openai"`` pins the official OpenAI endpoint
  (``https://api.openai.com/v1``) even when ``OPENAI_BASE_URL`` points somewhere
  else — the underlying ``openai`` client reads ``OPENAI_BASE_URL`` from the
  environment, so a bare ``ChatOpenAI(model=...)`` would silently follow a
  compat endpoint. We pass the base URL explicitly to defeat that.
  ``provider="openrouter"`` pins ``https://openrouter.ai/api/v1`` and its own
  key the same way.
- The overview's fallback is ``provider="openai"``, so with ``OVERVIEW_PROVIDER``
  unset a stray base URL is inert there exactly as it was.
- In the **default** (``provider is None``) path, OpenAI-compatible mode is
  enabled **only** by ``OPENAI_BASE_URL`` — a real endpoint. A lone
  ``OPENAI_COMPATIBLE_MODEL`` (the model name a compat endpoint would serve) is
  inert without a base URL, so the leftover in a dev ``.env`` cannot reroute the
  Lab agents to a compat endpoint or collapse their per-agent tiering.

In short: rerouting a family now takes that family's *own* variable, set
deliberately. Ambient OpenAI vars still move nothing.

Keys are read from the environment per provider: ``OPENAI_API_KEY`` (openai and
compat), ``GROQ_API_KEY`` (groq), ``OPENROUTER_API_KEY`` (openrouter). Never
construct a chat model directly in an agent — go through this helper.
"""

from __future__ import annotations

import os
from typing import Any, Literal, Optional, get_args

#: The canonical OpenAI endpoint. Pinned for ``provider="openai"`` so a stray
#: ``OPENAI_BASE_URL`` in the environment cannot redirect a portfolio call.
OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"

#: OpenRouter's OpenAI-compatible endpoint. Pinned for ``provider="openrouter"``
#: for the same reason, and paired with its own key so an ``OPENAI_API_KEY`` in
#: the environment is never sent to it.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

#: Attribution headers OpenRouter uses for its app leaderboard. Harmless
#: elsewhere; only ever sent on the openrouter path.
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/ishanavasthi/alphadesk",
    "X-Title": "AlphaDesk",
}

Provider = Literal["openai", "groq", "compat", "openrouter"]

#: Every accepted ``provider`` value, for validating env input.
PROVIDERS: frozenset[str] = frozenset(get_args(Provider))

#: Lab agents that take a model, in pipeline order. ``execution`` makes no LLM
#: call, so it is deliberately absent. Each name ``x`` reads ``LAB_X_MODEL``.
LAB_AGENTS: tuple[str, ...] = ("scanner", "research", "analyst", "risk")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _chat_openai(
    model: str,
    temperature: float,
    base_url: Optional[str],
    timeout: Optional[float],
    api_key: Optional[str] = None,
    default_headers: Optional[dict[str, str]] = None,
) -> Any:
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout
    if api_key:
        kwargs["api_key"] = api_key
    if default_headers:
        kwargs["default_headers"] = default_headers
    return ChatOpenAI(**kwargs)


def _chat_groq(model: str, temperature: float) -> Any:
    from langchain_groq import ChatGroq

    return ChatGroq(model=model, temperature=temperature)


def _chat_openrouter(model: str, temperature: float, timeout: Optional[float]) -> Any:
    """OpenRouter, pinned to its own endpoint and its own key.

    The key is passed explicitly: without it ``ChatOpenAI`` would fall back to
    ``OPENAI_API_KEY`` from the environment and send a real OpenAI key to a
    third party. Missing key is a loud failure, never a silent substitution.
    """
    api_key = _env("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "provider='openrouter' needs OPENROUTER_API_KEY set to an OpenRouter "
            "API key (sk-or-...)."
        )
    return _chat_openai(
        model,
        temperature,
        OPENROUTER_BASE_URL,
        timeout,
        api_key=api_key,
        default_headers=OPENROUTER_HEADERS,
    )


def get_chat_llm(
    default_model: str,
    *,
    temperature: float = 0,
    provider: Optional[Provider] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Return a chat model, routing by explicit ``provider`` first, then env.

    Args:
        default_model: The model name to use.
        temperature: Sampling temperature.
        provider: Explicit routing, and it **wins over the environment**:

            - ``"openai"`` — real OpenAI (`api.openai.com`), regardless of
              ``OPENAI_BASE_URL`` / ``OPENAI_COMPATIBLE_MODEL``.
            - ``"groq"`` — Groq, regardless of env.
            - ``"openrouter"`` — OpenRouter (`openrouter.ai/api/v1`) on
              ``OPENROUTER_API_KEY``, regardless of env.
            - ``"compat"`` — an OpenAI-compatible endpoint from
              ``OPENAI_BASE_URL`` (required) + ``OPENAI_COMPATIBLE_MODEL``.
            - ``None`` — env-selected default: compat **iff** ``OPENAI_BASE_URL``
              is set, otherwise Groq. A lone ``OPENAI_COMPATIBLE_MODEL`` is inert
              here, so the Lab keeps running Groq even when that leftover is set.
        timeout: Per-request timeout (seconds) for the OpenAI/compat/OpenRouter
            paths, so a stalled connection fails fast instead of hanging.
            Ignored for Groq.
    """
    if provider == "openai":
        # Pin the official endpoint so a stray OPENAI_BASE_URL cannot redirect
        # this call, and use exactly the model asked for — never the compat
        # model name, which belongs to a different endpoint entirely.
        return _chat_openai(default_model, temperature, OPENAI_OFFICIAL_BASE_URL, timeout)

    if provider == "groq":
        return _chat_groq(default_model, temperature)

    if provider == "openrouter":
        return _chat_openrouter(default_model, temperature, timeout)

    if provider == "compat":
        base_url = _env("OPENAI_BASE_URL")
        if not base_url:
            raise ValueError(
                "provider='compat' needs OPENAI_BASE_URL set to the compatible "
                "endpoint's base URL."
            )
        model = _env("OPENAI_COMPATIBLE_MODEL") or default_model
        return _chat_openai(model, temperature, base_url, timeout)

    # provider is None: env-selected default. Compat mode requires a real
    # endpoint (OPENAI_BASE_URL). OPENAI_COMPATIBLE_MODEL alone does NOT switch
    # provider — that is the v1 leftover A1 refuses to let reroute the Lab.
    base_url = _env("OPENAI_BASE_URL")
    if base_url:
        model = _env("OPENAI_COMPATIBLE_MODEL") or default_model
        return _chat_openai(model, temperature, base_url, timeout)

    return _chat_groq(default_model, temperature)


# --------------------------------------------------------------------------
# Per-family configuration
#
# Each family reads exactly one provider variable of its own. Unset means "keep
# the historical behaviour", so an untouched deploy routes identically to
# before this indirection existed.
# --------------------------------------------------------------------------


def _provider_from_env(var: str) -> Optional[Provider]:
    """Read and validate a family provider var. Blank/unset → ``None``.

    A typo raises rather than silently falling back: quietly billing the wrong
    provider is worse than a startup-time error naming the mistake.
    """
    raw = _env(var).lower()
    if not raw:
        return None
    if raw not in PROVIDERS:
        raise ValueError(
            f"{var}={raw!r} is not a known provider. "
            f"Expected one of: {', '.join(sorted(PROVIDERS))}."
        )
    return raw  # type: ignore[return-value]


def overview_provider() -> Provider:
    """The AI-overview provider: ``OVERVIEW_PROVIDER``, else real OpenAI.

    The default is ``"openai"`` — not ``None`` — so with the var unset the
    ambient ``OPENAI_BASE_URL`` still cannot reroute the overview (card A1).
    """
    return _provider_from_env("OVERVIEW_PROVIDER") or "openai"


def overview_model(default: str) -> str:
    """The AI-overview model: ``OVERVIEW_MODEL``, then the legacy
    ``OPENAI_OVERVIEW_MODEL``, then ``default``."""
    return _env("OVERVIEW_MODEL") or _env("OPENAI_OVERVIEW_MODEL") or default


def get_overview_llm(
    default_model: str, *, temperature: float = 0.2, timeout: Optional[float] = None
) -> Any:
    """Construct the AI-overview chat model from its own env vars."""
    return get_chat_llm(
        overview_model(default_model),
        temperature=temperature,
        provider=overview_provider(),
        timeout=timeout,
    )


def lab_provider() -> Optional[Provider]:
    """The Lab provider: ``LAB_PROVIDER``, else ``None``.

    ``None`` deliberately means "the ambient env default" (compat iff
    ``OPENAI_BASE_URL``, else Groq) — the Lab's historical behaviour.
    """
    return _provider_from_env("LAB_PROVIDER")


def lab_model(agent: str, default: str) -> str:
    """The model for one Lab agent.

    Precedence: ``LAB_<AGENT>_MODEL`` (per-agent) → ``LAB_MODEL`` (blanket) →
    ``default`` (the agent's historical tier).
    """
    if agent not in LAB_AGENTS:
        raise ValueError(f"unknown Lab agent {agent!r}; expected one of {LAB_AGENTS}.")
    return _env(f"LAB_{agent.upper()}_MODEL") or _env("LAB_MODEL") or default


def get_lab_llm(agent: str, default_model: str, *, temperature: float = 0) -> Any:
    """Construct one Lab agent's chat model from the Lab env vars."""
    return get_chat_llm(
        lab_model(agent, default_model),
        temperature=temperature,
        provider=lab_provider(),
    )


def structured(llm: Any, schema: Any) -> Any:
    """Bind a Pydantic ``schema`` to ``llm`` using **tool-calling** on every provider.

    ``langchain_openai`` defaults ``with_structured_output`` to strict
    ``json_schema``. Real OpenAI implements that; many models reachable through
    OpenRouter or a compat endpoint do **not** — they ignore the response format
    and answer in prose. Because both Lab callers swallow the resulting parse
    error to "skip a stock the model can't score", that failure is silent: every
    candidate is dropped and the run simply comes back empty.

    ``method="function_calling"`` is the one method every provider we route to
    supports (verified against Groq's ``openai/gpt-oss-120b`` and OpenRouter's
    ``stealth/ox-alpha``), and it is what Groq resolves to by default anyway — so
    pinning it changes nothing on the default path and makes the swap work.
    """
    return llm.with_structured_output(schema, method="function_calling")


__all__ = [
    "LAB_AGENTS",
    "OPENAI_OFFICIAL_BASE_URL",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_HEADERS",
    "PROVIDERS",
    "Provider",
    "get_chat_llm",
    "get_lab_llm",
    "get_overview_llm",
    "lab_model",
    "lab_provider",
    "overview_model",
    "overview_provider",
    "structured",
]
