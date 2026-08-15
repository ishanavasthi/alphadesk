"""Config-level LangSmith kill switch for the portfolio graph.

The research pipeline (`graph.graph`) *should* be traced — that is how the
Bloomberg-terminal run view is debugged. The portfolio graph must not be: it
handles a user's real holdings, and shipping those to LangSmith is not
something a `LANGCHAIN_TRACING_V2` env var should be able to switch on by
accident. Env-var kill switches get flipped by the next debugging session;
this one is carried by the config the graph is invoked with, so it travels
with the call.

Usage — every portfolio-graph invocation goes through it:

    from graph.portfolio_config import portfolio_runnable_config

    result = await alphaDesk_portfolio_graph.ainvoke(
        state, portfolio_runnable_config(thread_id=run_id)
    )

Child runnables inherit it: `callbacks` is an *inheritable* config key, so
nested nodes, tools and LLM calls inside the graph are covered by the one
config passed at the top.

---

How it works, and why it looks like this
----------------------------------------

Verified against langchain-core 1.4.9 / langsmith 0.10.3 (the pinned
versions): **there is no `RunnableConfig` field that turns tracing off.**
`RunnableConfig` allows exactly `tags, metadata, callbacks, run_name,
max_concurrency, recursion_limit, configurable, run_id`, and
`CallbackManager.configure()` decides to attach a tracer from
`langsmith.utils.tracing_is_enabled()` — a contextvar/global/env lookup that
ignores the config entirely. Passing `callbacks=[]` or an empty
`CallbackManager` does not help; both still come back with a live
`LangChainTracer` attached (probed, not assumed).

The one seam `_configure()` does leave is this guard:

    if tracing_v2_enabled_ and not any(
        isinstance(handler, LangChainTracer)
        for handler in callback_manager.handlers
    ):
        ...attach a live LangChainTracer...

So the config ships an inert `LangChainTracer` subclass. It occupies the slot,
so no live tracer is ever constructed or attached, and it is wired to receive
nothing: every `ignore_*` flag is `True`, so `handle_event` skips it for every
callback the manager dispatches, and its LangSmith client is a null object
that counts calls instead of making them (`tracer.client.calls` is asserted to
stay at 0 in `tests/test_portfolio_config.py`).

Consequence to be aware of: the resolved callback manager contains an object
that *is* a `LangChainTracer` by `isinstance`. Assert on
`is_tracing_disabled(...)` / `has_live_tracer(...)` below rather than on
`isinstance`, and re-run the tests after any langchain-core bump — this
depends on an internal guard, so a bump is exactly when it could rot.
"""

from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.callbacks.base import BaseCallbackManager
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import get_callback_manager_for_config
from langchain_core.tracers.langchain import LangChainTracer

__all__ = [
    "PORTFOLIO_TRACING_TAG",
    "disabled_tracers",
    "has_live_tracer",
    "is_tracing_disabled",
    "portfolio_runnable_config",
    "tracing_disabled_handler",
]

#: Tag stamped on every portfolio-graph config, so a stray traced run is
#: identifiable at a glance if this ever regresses.
PORTFOLIO_TRACING_TAG = "alphaDesk_portfolio_no_trace"


class _NullLangSmithClient:
    """Stand-in for `langsmith.Client` that makes no calls and records attempts.

    Silent rather than raising: if a future langchain-core starts poking the
    client on an ignored handler, the portfolio graph should keep working. The
    call log is what turns that silence into a test assertion.

    **`calls` is class-level on purpose.** langchain re-instantiates the
    handler (`self.__class__(...)` in `copy_with_metadata_defaults()`) whenever
    a config carries metadata, which hands the copy a *fresh* client — so a log
    kept per instance would leave the singleton's list empty no matter what the
    handler that actually ran did, and the assertion would be vacuous. One
    shared list means any copy's activity is visible from anywhere.
    """

    #: Shared across every instance — see the class docstring.
    calls: ClassVar[list[str]] = []

    def __getattr__(self, name: str) -> Any:
        def _record(*_args: Any, **_kwargs: Any) -> None:
            type(self).calls.append(name)
            return None

        return _record


class TracingDisabledTracer(LangChainTracer):
    """An inert `LangChainTracer` whose only job is to keep a real one out.

    See the module docstring. Every `ignore_*` flag is set so
    `langchain_core.callbacks.manager.handle_event` never dispatches to it,
    and the trace-writing hooks are no-ops as a second line of defence.
    """

    # handle_event() checks these before calling any handler method; with all
    # of them True the manager never dispatches an event here.
    ignore_llm = True
    ignore_chat_model = True
    ignore_chain = True
    ignore_agent = True
    ignore_retriever = True
    ignore_retry = True
    ignore_custom_event = True

    def __init__(self, **kwargs: Any) -> None:
        # `**kwargs` because langchain-core re-instantiates the handler via
        # `self.__class__(...)` in `copy_with_metadata_defaults()` whenever a
        # config carries metadata/tags. The client and project are forced, so
        # a copy is just as inert as the original.
        kwargs.pop("client", None)
        kwargs.pop("project_name", None)
        super().__init__(
            client=_NullLangSmithClient(),
            project_name="alphaDesk-portfolio-tracing-disabled",
            **kwargs,
        )

    # `on_text` is the one event dispatched without an ignore_* guard.
    def on_text(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    # Belt and braces: even if an event did get through, nothing is written.
    def _start_trace(self, run: Any) -> None:
        return None

    def _end_trace(self, run: Any) -> None:
        return None

    def _persist_run(self, run: Any) -> None:
        return None

    def _persist_run_single(self, run: Any) -> None:
        return None

    @staticmethod
    def _update_run_single(run: Any) -> None:
        return None

    def wait_for_futures(self) -> None:
        return None


_HANDLER = TracingDisabledTracer()


def tracing_disabled_handler() -> TracingDisabledTracer:
    """The process-wide inert tracer instance carried by every portfolio config.

    Stateless, so one instance is shared by every config. Exposed for tests
    (`handler.client.calls` must stay empty).
    """
    return _HANDLER


def portfolio_runnable_config(
    *,
    thread_id: str | None = None,
    run_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    configurable: dict[str, Any] | None = None,
    recursion_limit: int | None = None,
) -> RunnableConfig:
    """A `RunnableConfig` for the portfolio graph, with LangSmith tracing off.

    Tracing stays off even when `LANGCHAIN_TRACING_V2=true` /
    `LANGSMITH_TRACING=true` is exported — the config wins over the
    environment, which is the whole point.

    Args:
        thread_id: LangGraph checkpointer thread id (goes in `configurable`).
        run_name: Optional display name for the root run.
        tags: Extra tags, appended to `PORTFOLIO_TRACING_TAG`.
        metadata: Extra metadata. Never put credentials here.
        configurable: Extra `configurable` entries, merged after `thread_id`.
        recursion_limit: Override LangGraph's default recursion limit.
    """
    config: RunnableConfig = {
        "callbacks": [_HANDLER],
        "tags": [PORTFOLIO_TRACING_TAG, *(tags or [])],
    }

    conf: dict[str, Any] = {}
    if thread_id is not None:
        conf["thread_id"] = thread_id
    if configurable:
        conf.update(configurable)
    if conf:
        config["configurable"] = conf

    if metadata:
        config["metadata"] = dict(metadata)
    if run_name is not None:
        config["run_name"] = run_name
    if recursion_limit is not None:
        config["recursion_limit"] = recursion_limit

    return config


def _handlers(callbacks: Any) -> list[Any]:
    """Resolve `callbacks` (a RunnableConfig, manager or list) to a handler list."""
    if isinstance(callbacks, dict):  # a RunnableConfig
        callbacks = get_callback_manager_for_config(callbacks)
    if isinstance(callbacks, BaseCallbackManager):
        return list(callbacks.handlers)
    return list(callbacks or [])


def disabled_tracers(callbacks: Any) -> list[TracingDisabledTracer]:
    """The inert tracers actually present after `callbacks` is resolved.

    Use this rather than `tracing_disabled_handler()` when asserting on the
    null client's call log: langchain may hand the resolved manager a *copy* of
    the handler, and it is the copy that would have done any writing.
    """
    return [h for h in _handlers(callbacks) if isinstance(h, TracingDisabledTracer)]


def has_live_tracer(callbacks: Any) -> bool:
    """True if `callbacks` carries a tracer that would ship runs to LangSmith.

    Accepts a `RunnableConfig`, a `BaseCallbackManager` or a handler list.
    `TracingDisabledTracer` instances do not count — they never write.
    """
    return any(
        isinstance(handler, LangChainTracer)
        and not isinstance(handler, TracingDisabledTracer)
        for handler in _handlers(callbacks)
    )


def is_tracing_disabled(config: RunnableConfig) -> bool:
    """True if invoking with `config` produces no LangSmith-writing tracer."""
    return not has_live_tracer(config)
