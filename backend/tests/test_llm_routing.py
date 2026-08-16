"""LLM routing (card A1, item 4) — provider= wins over the env.

The one property that must never regress: a stray ``OPENAI_COMPATIBLE_MODEL`` (a
v1 leftover, plan §9) cannot reroute the portfolio graph to a compat endpoint,
nor reroute the Lab off Groq. The explicit ``provider=`` argument is
authoritative.
"""

from __future__ import annotations

import pytest
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from agents.llm import OPENAI_OFFICIAL_BASE_URL, get_chat_llm


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_MODEL", raising=False)


def _base_url(model: ChatOpenAI) -> str:
    return str(model.root_client.base_url)


def test_portfolio_provider_is_openai_even_with_compat_model_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The exact leftover the brief calls out: OPENAI_COMPATIBLE_MODEL set.
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "some-compat-model")
    llm = get_chat_llm("gpt-4o-mini", provider="openai")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4o-mini"  # NOT the compat model name
    assert _base_url(llm).startswith("https://api.openai.com")


def test_openai_provider_pins_official_endpoint_over_stray_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even a stray OPENAI_BASE_URL (which the openai client would otherwise
    # follow) must not redirect a provider="openai" call.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "some-compat-model")
    llm = get_chat_llm("gpt-4o-mini", provider="openai")
    assert _base_url(llm).rstrip("/") == OPENAI_OFFICIAL_BASE_URL


def test_lab_agent_stays_on_groq_even_with_compat_model_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A Lab agent calls get_chat_llm(model) with NO provider. A lone
    # OPENAI_COMPATIBLE_MODEL must NOT switch it to a compat endpoint.
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "some-compat-model")
    llm = get_chat_llm("llama-3.1-8b-instant")
    assert isinstance(llm, ChatGroq)


def test_default_is_groq_with_clean_env() -> None:
    assert isinstance(get_chat_llm("llama-3.1-8b-instant"), ChatGroq)


def test_default_uses_compat_only_when_base_url_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A real endpoint (OPENAI_BASE_URL) does still enable compat mode for the
    # default path — that contract is intact; only the model-only trigger is gone.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "compat-model")
    llm = get_chat_llm("fallback-model")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "compat-model"
    assert _base_url(llm).startswith("https://compat.example.com")


def test_explicit_groq_provider_ignores_compat_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.com/v1")
    assert isinstance(get_chat_llm("llama-3.1-8b-instant", provider="groq"), ChatGroq)
