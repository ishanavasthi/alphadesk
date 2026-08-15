"""`graph.portfolio_config` — the portfolio graph must never reach LangSmith.

Every test here runs with `LANGCHAIN_TRACING_V2=true` (and `LANGSMITH_TRACING`
+ an API key) exported, i.e. the exact situation the helper exists for: someone
turned tracing on in the environment for a debugging session, and the portfolio
graph must stay dark anyway.

Assertions are on the resolved callback manager and on the null client's call
log — no network is involved either way.
"""

from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.config import get_callback_manager_for_config
from langchain_core.tracers.langchain import LangChainTracer

from graph.portfolio_config import (
    PORTFOLIO_TRACING_TAG,
    TracingDisabledTracer,
    has_live_tracer,
    is_tracing_disabled,
    portfolio_runnable_config,
    tracing_disabled_handler,
)


@pytest.fixture(autouse=True)
def tracing_on_in_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "lsv2_pt_not_a_real_key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_not_a_real_key")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "alphaDesk-test")


def _handler_names(config) -> list[str]:
    return [type(h).__name__ for h in get_callback_manager_for_config(config).handlers]


def test_the_env_var_really_would_enable_tracing() -> None:
    """Control case. Without this, every other test in the file proves nothing."""
    default_config = {}
    assert any(
        isinstance(handler, LangChainTracer)
        and not isinstance(handler, TracingDisabledTracer)
        for handler in get_callback_manager_for_config(default_config).handlers
    ), f"expected a live LangChainTracer, got {_handler_names(default_config)}"
    assert has_live_tracer(default_config) is True


def test_empty_callbacks_are_not_enough() -> None:
    """Documents *why* the helper is not simply `{"callbacks": []}`."""
    assert has_live_tracer({"callbacks": []}) is True
    assert has_live_tracer({"callbacks": None}) is True


def test_portfolio_config_resolves_to_no_live_tracer() -> None:
    config = portfolio_runnable_config()
    manager = get_callback_manager_for_config(config)
    live = [
        h
        for h in manager.handlers
        if isinstance(h, LangChainTracer) and not isinstance(h, TracingDisabledTracer)
    ]
    assert live == [], f"a live tracer got attached: {_handler_names(config)}"
    assert is_tracing_disabled(config) is True


def test_invoking_a_runnable_with_the_config_writes_nothing() -> None:
    handler = tracing_disabled_handler()
    before = len(handler.client.calls)

    seen: list[list[str]] = []

    def _inner(value: int) -> int:
        # Children inherit `callbacks`, so a nested runnable must be dark too.
        from langchain_core.runnables.config import var_child_runnable_config

        child = var_child_runnable_config.get() or {}
        seen.append([type(h).__name__ for h in getattr(child.get("callbacks"), "handlers", [])])
        return value + 1

    chain = RunnableLambda(lambda v: v * 2) | RunnableLambda(_inner)
    assert chain.invoke(3, portfolio_runnable_config(run_name="portfolio-test")) == 7

    assert handler.client.calls[before:] == [], (
        "the inert tracer's LangSmith client was called: "
        f"{handler.client.calls[before:]}"
    )
    assert seen, "the nested runnable never ran"
    for handlers in seen:
        assert "LangChainTracer" not in handlers
        assert handlers == ["TracingDisabledTracer"]


def test_tags_and_configurable_are_carried_through() -> None:
    config = portfolio_runnable_config(
        thread_id="run-123",
        tags=["portfolio"],
        metadata={"user_id": "user_local"},
        run_name="portfolio-graph",
        configurable={"checkpoint_ns": "portfolio"},
        recursion_limit=42,
    )
    assert config["tags"] == [PORTFOLIO_TRACING_TAG, "portfolio"]
    assert config["configurable"] == {
        "thread_id": "run-123",
        "checkpoint_ns": "portfolio",
    }
    assert config["metadata"] == {"user_id": "user_local"}
    assert config["run_name"] == "portfolio-graph"
    assert config["recursion_limit"] == 42
    assert is_tracing_disabled(config) is True


def test_helper_does_not_disable_tracing_globally() -> None:
    """The kill switch is scoped to the config — the research graph still traces."""
    portfolio_runnable_config()
    assert has_live_tracer({}) is True


def test_inert_tracer_ignores_every_callback_category() -> None:
    handler = tracing_disabled_handler()
    for flag in (
        "ignore_llm",
        "ignore_chat_model",
        "ignore_chain",
        "ignore_agent",
        "ignore_retriever",
        "ignore_retry",
        "ignore_custom_event",
    ):
        assert getattr(handler, flag) is True, f"{flag} is not set"
