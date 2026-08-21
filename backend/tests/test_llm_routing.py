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

from agents.llm import (
    OPENAI_OFFICIAL_BASE_URL,
    OPENROUTER_BASE_URL,
    get_chat_llm,
    get_lab_llm,
    get_overview_llm,
    lab_model,
    lab_provider,
    overview_model,
    overview_provider,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_MODEL", raising=False)
    # The per-family vars, cleared so a developer's .env (which test_overview_live
    # load_dotenv()s into os.environ for the whole session) cannot leak in here.
    for var in (
        "OVERVIEW_PROVIDER",
        "OVERVIEW_MODEL",
        "OPENAI_OVERVIEW_MODEL",
        "LAB_PROVIDER",
        "LAB_MODEL",
        "LAB_SCANNER_MODEL",
        "LAB_RESEARCH_MODEL",
        "LAB_ANALYST_MODEL",
        "LAB_RISK_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


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


def test_openai_provider_applies_request_timeout() -> None:
    llm = get_chat_llm("gpt-4o-mini", provider="openai", timeout=30)
    assert llm.request_timeout == 30.0


def test_overview_factory_sets_a_timeout() -> None:
    from agents.portfolio.agents import default_llm_factory

    assert default_llm_factory().request_timeout == 30.0


# ---------------------------------------------------------------------------
# OpenRouter (provider="openrouter")
# ---------------------------------------------------------------------------


def test_openrouter_pins_its_endpoint_and_its_own_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ambient OpenAI vars must not touch this path — and specifically the real
    # OPENAI_API_KEY must never be the key sent to a third party.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "some-compat-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-distinct")
    llm = get_chat_llm("stealth/ox-alpha", provider="openrouter")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "stealth/ox-alpha"  # NOT the compat model name
    assert _base_url(llm).rstrip("/") == OPENROUTER_BASE_URL
    assert llm.openai_api_key.get_secret_value() == "sk-or-v1-distinct"


def test_openrouter_without_a_key_raises_rather_than_borrowing_openais(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_chat_llm("stealth/ox-alpha", provider="openrouter")


def test_openrouter_applies_request_timeout() -> None:
    assert get_chat_llm("stealth/ox-alpha", provider="openrouter", timeout=30).request_timeout == 30.0


# ---------------------------------------------------------------------------
# Per-family config: defaults preserve the pre-existing routing exactly
# ---------------------------------------------------------------------------


def test_overview_defaults_are_unchanged() -> None:
    assert overview_provider() == "openai"
    assert overview_model("gpt-4o-mini") == "gpt-4o-mini"
    llm = get_overview_llm("gpt-4o-mini")
    assert isinstance(llm, ChatOpenAI)
    assert _base_url(llm).rstrip("/") == OPENAI_OFFICIAL_BASE_URL


def test_lab_defaults_are_unchanged() -> None:
    assert lab_provider() is None
    assert lab_model("scanner", "llama-3.1-8b-instant") == "llama-3.1-8b-instant"
    assert isinstance(get_lab_llm("scanner", "llama-3.1-8b-instant"), ChatGroq)


def test_stray_openai_base_url_still_cannot_reroute_the_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The A1 invariant, restated for the env-driven world: only the family's OWN
    # variable reroutes it. The ambient leftovers stay inert.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "some-compat-model")
    llm = get_overview_llm("gpt-4o-mini")
    assert _base_url(llm).rstrip("/") == OPENAI_OFFICIAL_BASE_URL
    assert llm.model_name == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Per-family config: the swaps the vars are there to make
# ---------------------------------------------------------------------------


def test_overview_provider_and_model_swap_to_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OVERVIEW_PROVIDER", "openrouter")
    monkeypatch.setenv("OVERVIEW_MODEL", "stealth/ox-alpha")
    llm = get_overview_llm("gpt-4o-mini")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "stealth/ox-alpha"
    assert _base_url(llm).rstrip("/") == OPENROUTER_BASE_URL


def test_overview_provider_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_PROVIDER", "OpenRouter")
    assert overview_provider() == "openrouter"


def test_overview_model_falls_back_to_the_legacy_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OVERVIEW_MODEL", "gpt-4o")
    assert overview_model("gpt-4o-mini") == "gpt-4o"
    # ...and the new var wins when both are set.
    monkeypatch.setenv("OVERVIEW_MODEL", "gpt-4.1-mini")
    assert overview_model("gpt-4o-mini") == "gpt-4.1-mini"


def test_lab_blanket_model_swaps_every_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "openrouter")
    monkeypatch.setenv("LAB_MODEL", "stealth/ox-alpha")
    for agent in ("scanner", "research", "analyst", "risk"):
        llm = get_lab_llm(agent, "llama-3.1-8b-instant")
        assert isinstance(llm, ChatOpenAI), agent
        assert llm.model_name == "stealth/ox-alpha", agent
        assert _base_url(llm).rstrip("/") == OPENROUTER_BASE_URL, agent


def test_per_agent_model_beats_the_blanket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_MODEL", "stealth/ox-alpha")
    monkeypatch.setenv("LAB_ANALYST_MODEL", "openai/gpt-oss-120b")
    assert lab_model("analyst", "default-x") == "openai/gpt-oss-120b"
    assert lab_model("scanner", "default-x") == "stealth/ox-alpha"  # blanket still applies


def test_lab_provider_swap_keeps_the_historical_tiers_when_no_model_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Swapping only the provider must not silently rewrite the per-agent tiers.
    monkeypatch.setenv("LAB_PROVIDER", "openrouter")
    assert get_lab_llm("scanner", "llama-3.1-8b-instant").model_name == "llama-3.1-8b-instant"
    assert get_lab_llm("analyst", "openai/gpt-oss-120b").model_name == "openai/gpt-oss-120b"


def test_lab_provider_overrides_the_ambient_compat_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LAB_PROVIDER is the family's own var, so it beats OPENAI_BASE_URL.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.com/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "some-compat-model")
    monkeypatch.setenv("LAB_PROVIDER", "groq")
    assert isinstance(get_lab_llm("scanner", "llama-3.1-8b-instant"), ChatGroq)


def test_the_two_families_are_configured_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "openrouter")
    monkeypatch.setenv("LAB_MODEL", "stealth/ox-alpha")
    # Lab moved; the overview did not.
    assert _base_url(get_lab_llm("scanner", "x")).rstrip("/") == OPENROUTER_BASE_URL
    assert _base_url(get_overview_llm("gpt-4o-mini")).rstrip("/") == OPENAI_OFFICIAL_BASE_URL


# ---------------------------------------------------------------------------
# Bad input fails loudly rather than billing the wrong provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("var,resolve", [
    ("OVERVIEW_PROVIDER", overview_provider),
    ("LAB_PROVIDER", lab_provider),
])
def test_a_typo_in_a_provider_var_raises(
    monkeypatch: pytest.MonkeyPatch, var: str, resolve
) -> None:
    monkeypatch.setenv(var, "opencrouter")
    with pytest.raises(ValueError, match="not a known provider"):
        resolve()


def test_blank_provider_var_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_PROVIDER", "   ")
    monkeypatch.setenv("OVERVIEW_PROVIDER", "")
    assert lab_provider() is None
    assert overview_provider() == "openai"


def test_unknown_lab_agent_name_raises() -> None:
    with pytest.raises(ValueError, match="unknown Lab agent"):
        lab_model("execution", "x")


# ---------------------------------------------------------------------------
# Structured output must use tool-calling on every provider
# ---------------------------------------------------------------------------


def test_structured_pins_function_calling() -> None:
    """The default (strict ``json_schema``) is silently wrong off real OpenAI.

    Many models behind OpenRouter/compat advertise ``tools`` but not
    ``structured_outputs``; they ignore a json_schema response format and answer
    in prose. Both Lab callers swallow the parse error as "skip this stock", so
    the whole run comes back empty with no error anywhere. Pin tool-calling.
    """
    from agents.llm import structured

    captured: dict[str, object] = {}

    class _FakeLLM:
        def with_structured_output(self, schema, **kwargs):
            captured["schema"] = schema
            captured["kwargs"] = kwargs
            return "bound"

    class _Schema:
        pass

    assert structured(_FakeLLM(), _Schema) == "bound"
    assert captured["schema"] is _Schema
    assert captured["kwargs"] == {"method": "function_calling"}


def test_every_lab_structured_call_site_goes_through_the_helper() -> None:
    """No agent may call ``with_structured_output`` directly.

    A direct call re-introduces the provider-dependent default. This is the same
    style of source scan the frontend uses to keep Clerk imports contained.
    """
    import pathlib

    agents_dir = pathlib.Path(__file__).resolve().parent.parent / "agents"
    offenders = [
        path.relative_to(agents_dir.parent)
        for path in agents_dir.rglob("*.py")
        if path.name != "llm.py" and "with_structured_output" in path.read_text()
    ]
    assert not offenders, f"call agents.llm.structured() instead: {offenders}"
