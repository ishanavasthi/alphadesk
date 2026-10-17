"""The `anthropic` provider (Anthropic Messages API via ChatAnthropic).

Same contract as the OpenAI-compatible providers: pinned to its own endpoint
and its own key, a missing key raises rather than borrowing another provider's,
and the A1 invariant holds — no stray env var reroutes either family. On top of
that, two Anthropic-specific facts are pinned here: current Claude models reject
non-default sampling and forced tool-choice, so the helper sends no
temperature and structured output goes through native `json_schema`.

Constructing the clients touches no network; all keys here are fakes.
"""

from __future__ import annotations

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agents.llm import (
    ANTHROPIC_BASE_URL,
    ANTHROPIC_DEFAULT_MODEL,
    ANTHROPIC_MAX_TOKENS,
    OPENAI_OFFICIAL_BASE_URL,
    get_chat_llm,
    get_lab_llm,
    get_overview_llm,
    message_text,
    provider_key_configured,
    structured,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    for var in (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_WORKSPACE_ID",
        "OPENAI_BASE_URL",
        "OPENAI_COMPATIBLE_MODEL",
        "OVERVIEW_PROVIDER",
        "OVERVIEW_MODEL",
        "OPENAI_OVERVIEW_MODEL",
        "LAB_PROVIDER",
        "LAB_MODEL",
        "LAB_EFFORT",
        "OVERVIEW_EFFORT",
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


class _Schema(BaseModel):
    score: float


def test_anthropic_pins_its_endpoint_and_its_own_key() -> None:
    llm = get_chat_llm("claude-sonnet-5-5", provider="anthropic", timeout=7)
    assert isinstance(llm, ChatAnthropic)
    assert llm.model == "claude-sonnet-5-5"
    assert llm.anthropic_api_url == ANTHROPIC_BASE_URL
    assert llm.anthropic_api_key.get_secret_value() == "sk-ant-test-not-a-real-key"
    assert llm.max_tokens == ANTHROPIC_MAX_TOKENS
    assert llm.default_request_timeout == 7


def test_workspace_id_rides_as_a_header(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not get_chat_llm("claude-opus-5-5", provider="anthropic").default_headers
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test")
    llm = get_chat_llm("claude-opus-5-5", provider="anthropic")
    assert llm.default_headers == {"anthropic-workspace-id": "wrkspc_test"}


def test_stray_anthropic_base_url_cannot_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example/v1")
    llm = get_chat_llm("claude-opus-5-5", provider="anthropic")
    assert llm.anthropic_api_url == ANTHROPIC_BASE_URL


def test_missing_anthropic_key_raises_instead_of_borrowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_chat_llm("claude-opus-5-5", provider="anthropic")


def test_no_temperature_is_sent() -> None:
    # Opus 5.5 / Sonnet 5.5 / Haiku 5.5 400 on any non-default sampling value.
    llm = get_chat_llm("claude-opus-5-5", provider="anthropic", temperature=0)
    assert llm.temperature is None
    assert "temperature" not in llm._get_request_payload([("human", "hi")])


def test_structured_output_uses_native_json_schema_on_anthropic() -> None:
    # Forced tool_choice (what function_calling means on ChatAnthropic) is a
    # 400 on the current Claude models; json_schema is output_config.format.
    llm = get_chat_llm("claude-opus-5-5", provider="anthropic")
    bound = structured(llm, _Schema).first
    assert "format" in bound.kwargs["output_config"]
    assert "tools" not in bound.kwargs
    assert "tool_choice" not in bound.kwargs


def test_structured_output_stays_function_calling_elsewhere() -> None:
    llm = get_chat_llm("gpt-4o-mini", provider="openai")
    bound = structured(llm, _Schema).first
    assert "tools" in bound.kwargs


def test_overview_routes_to_anthropic_with_a_claude_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OVERVIEW_PROVIDER", "anthropic")
    llm = get_overview_llm("gpt-4o-mini")
    assert isinstance(llm, ChatAnthropic)
    # The family's OpenAI default would 404 on Anthropic.
    assert llm.model == ANTHROPIC_DEFAULT_MODEL


def test_overview_model_var_wins_on_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_PROVIDER", "anthropic")
    monkeypatch.setenv("OVERVIEW_MODEL", "claude-haiku-5-5")
    assert get_overview_llm("gpt-4o-mini").model == "claude-haiku-5-5"


def test_lab_routes_to_anthropic_with_per_agent_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "anthropic")
    monkeypatch.setenv("LAB_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("LAB_SCANNER_MODEL", "claude-haiku-5-5")
    assert get_lab_llm("scanner", "llama-3.1-8b-instant").model == "claude-haiku-5-5"
    assert get_lab_llm("analyst", "openai/gpt-oss-120b").model == "claude-sonnet-5-5"


def test_lab_on_anthropic_without_a_model_var_uses_the_claude_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "anthropic")
    assert get_lab_llm("risk", "openai/gpt-oss-120b").model == ANTHROPIC_DEFAULT_MODEL


def test_an_anthropic_key_alone_reroutes_nothing() -> None:
    # A1: the key is inert until a family's provider var names anthropic.
    overview = get_overview_llm("gpt-4o-mini")
    assert isinstance(overview, ChatOpenAI)
    assert str(overview.root_client.base_url).rstrip("/") == OPENAI_OFFICIAL_BASE_URL
    assert not isinstance(get_lab_llm("scanner", "llama-3.1-8b-instant"), ChatAnthropic)


def test_provider_key_configured_reads_each_providers_own_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert provider_key_configured("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert not provider_key_configured("anthropic")
    assert provider_key_configured("openai")


def test_message_text_skips_anthropic_thinking_blocks() -> None:
    msg = AIMessage(
        content=[
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": "Two factual sentences."},
        ]
    )
    assert message_text(msg) == "Two factual sentences."
    assert message_text(AIMessage(content="plain")) == "plain"


def test_family_effort_vars_reach_output_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "anthropic")
    monkeypatch.setenv("LAB_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("LAB_EFFORT", "medium")
    monkeypatch.setenv("OVERVIEW_PROVIDER", "anthropic")
    monkeypatch.setenv("OVERVIEW_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("OVERVIEW_EFFORT", "HIGH")
    lab = get_lab_llm("analyst", "openai/gpt-oss-120b")
    overview = get_overview_llm("gpt-4o-mini")
    payload = lab._get_request_payload([("human", "hi")])
    assert payload["output_config"]["effort"] == "medium"
    assert overview._get_request_payload([("human", "hi")])["output_config"]["effort"] == "high"


def test_effort_survives_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # json_schema binds its own output_config; both keys must reach the request.
    llm = get_chat_llm("claude-opus-5-5", provider="anthropic", effort="medium")
    bound = structured(llm, _Schema).first
    payload = llm._get_request_payload([("human", "hi")], **bound.kwargs)
    assert payload["output_config"]["effort"] == "medium"
    assert "format" in payload["output_config"]


def test_no_effort_var_leaves_the_model_default() -> None:
    llm = get_chat_llm("claude-opus-5-5", provider="anthropic")
    assert "output_config" not in llm._get_request_payload([("human", "hi")])


def test_effort_typo_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "anthropic")
    monkeypatch.setenv("LAB_EFFORT", "meduim")
    with pytest.raises(ValueError, match="LAB_EFFORT"):
        get_lab_llm("analyst", "openai/gpt-oss-120b")


def test_effort_is_inert_off_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_EFFORT", "high")
    assert isinstance(get_overview_llm("gpt-4o-mini"), ChatOpenAI)
