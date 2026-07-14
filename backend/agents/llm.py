"""Shared LLM construction for AlphaDesk agents.

By default the app uses Groq via ``ChatGroq``. Set either
``OPENAI_BASE_URL`` or ``OPENAI_COMPATIBLE_MODEL`` to route LLM calls through
an OpenAI-compatible endpoint instead.
"""

from __future__ import annotations

import os
from typing import Any


def get_chat_llm(default_model: str, *, temperature: float = 0) -> Any:
    """Return a chat model using env-selected provider settings.

    OpenAI-compatible mode is enabled when either of these vars is present:
    - OPENAI_BASE_URL: compatible API base URL, e.g. https://.../v1
    - OPENAI_COMPATIBLE_MODEL: model name served by that endpoint

    OPENAI_API_KEY is read by ``ChatOpenAI`` from the environment.
    """

    openai_base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    openai_model = os.environ.get("OPENAI_COMPATIBLE_MODEL", "").strip()

    if openai_base_url or openai_model:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": openai_model or default_model,
            "temperature": temperature,
        }
        if openai_base_url:
            kwargs["base_url"] = openai_base_url
        return ChatOpenAI(**kwargs)

    from langchain_groq import ChatGroq

    return ChatGroq(model=default_model, temperature=temperature)
