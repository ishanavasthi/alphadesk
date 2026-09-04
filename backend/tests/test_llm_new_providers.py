"""Named `nvidia` + `bai` providers and bare per-agent model aliases (#42-slice).

Same contract as the `openrouter` path they mirror: each provider is pinned to
its own endpoint and its own key, a missing key raises rather than borrowing
another provider's, and the A1 invariant holds — no stray env var reroutes
either family. The bare `SCANNER_MODEL`-style vars are deprecated aliases for
`LAB_<AGENT>_MODEL`, so an unset-everything deploy routes byte-identically.

Constructing the clients touches no network; all keys here are fakes.
"""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from agents.llm import (
    BAI_DEFAULT_BASE_URL,
    NVIDIA_NIM_BASE_URL,
    get_chat_llm,
    get_lab_llm,
    get_overview_llm,
    lab_model,
    lab_provider,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-not-a-real-key")
    monkeypatch.setenv("BAI_API_KEY", "bai-test-not-a-real-key")
    for var in (
        "OPENAI_BASE_URL",
        "OPENAI_COMPATIBLE_MODEL",
        "BAI_BASE_URL",
        "OVERVIEW_PROVIDER",
        "OVERVIEW_MODEL",
        "LAB_PROVIDER",
        "LAB_MODEL",
        "LAB_SCANNER_MODEL",
        "LAB_RESEARCH_MODEL",
        "LAB_ANALYST_MODEL",
        "LAB_RISK_MODEL",
        "SCANNER_MODEL",
        "RESEARCH_MODEL",
        "ANALYST_MODEL",
        "RISK_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def _base_url(model: ChatOpenAI) -> str:
    return str(model.root_client.base_url)


def test_nvidia_pins_its_endpoint_and_its_own_key() -> None:
    llm = get_chat_llm("moonshotai/kimi-k3", provider="nvidia")
    assert _base_url(llm).rstrip("/") == NVIDIA_NIM_BASE_URL
    assert llm.openai_api_key.get_secret_value() == "nvapi-test-not-a-real-key"


def test_nvidia_without_a_key_raises_rather_than_borrowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY")
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        get_chat_llm("moonshotai/kimi-k3", provider="nvidia")


def test_bai_pins_its_default_endpoint_and_its_own_key() -> None:
    llm = get_chat_llm("glm-5.3-flash", provider="bai")
    assert _base_url(llm).rstrip("/") == BAI_DEFAULT_BASE_URL
    assert llm.openai_api_key.get_secret_value() == "bai-test-not-a-real-key"


def test_bai_base_url_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAI_BASE_URL", "https://bai-mirror.example.com/v1")
    llm = get_chat_llm("glm-5.3-flash", provider="bai")
    assert _base_url(llm).rstrip("/") == "https://bai-mirror.example.com/v1"


def test_bai_without_a_key_raises_rather_than_borrowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BAI_API_KEY")
    with pytest.raises(ValueError, match="BAI_API_KEY"):
        get_chat_llm("glm-5.3-flash", provider="bai")


def test_unknown_family_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "wat")
    with pytest.raises(ValueError, match="LAB_PROVIDER"):
        lab_provider()


def test_bare_model_alias_sits_between_prefixed_and_blanket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert lab_model("scanner", "default") == "default"
    monkeypatch.setenv("LAB_MODEL", "blanket")
    assert lab_model("scanner", "default") == "blanket"
    monkeypatch.setenv("SCANNER_MODEL", "alias")
    assert lab_model("scanner", "default") == "alias"
    monkeypatch.setenv("LAB_SCANNER_MODEL", "prefixed")
    assert lab_model("scanner", "default") == "prefixed"
    # Other agents are unaffected by the scanner alias.
    assert lab_model("research", "default") == "blanket"


def test_stray_bai_base_url_cannot_reroute_the_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The A1 invariant, extended: a stray `BAI_BASE_URL` moves nothing."""
    monkeypatch.setenv("BAI_BASE_URL", "https://evil.example.com/v1")
    llm = get_overview_llm("gpt-4o-mini")
    assert _base_url(llm).rstrip("/") == "https://api.openai.com/v1"


def test_lab_family_routes_through_new_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "nvidia")
    llm = get_lab_llm("analyst", "openai/gpt-oss-120b")
    assert _base_url(llm).rstrip("/") == NVIDIA_NIM_BASE_URL
    monkeypatch.setenv("LAB_PROVIDER", "bai")
    llm = get_lab_llm("research", "llama-3.1-8b-instant")
    assert _base_url(llm).rstrip("/") == BAI_DEFAULT_BASE_URL
