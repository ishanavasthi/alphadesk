"""Standalone tracing check runnable inside the Docker image (no pytest).

`graph.portfolio_config` leans on a langchain-core internal, so the switch is
re-proved against whatever the image actually installed. The `Dockerfile` runs
this as a **build-time gate**, so a bad dependency resolution fails the build
instead of shipping a portfolio graph that quietly traces.

To run it by hand against a built image (note `-w /app/backend` — the module
imports resolve with `backend/` as the root):

    docker build -t alphadesk-f1 .
    docker run --rm -e LANGCHAIN_TRACING_V2=true -e LANGCHAIN_API_KEY=dummy \
      -w /app/backend alphadesk-f1 python -m tests.check_tracing_in_image

Exits non-zero with a diagnostic if a live tracer would be attached.
"""

from __future__ import annotations

import sys

from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.config import get_callback_manager_for_config
from langchain_core.tracers.langchain import LangChainTracer

from graph.portfolio_config import (
    TracingDisabledTracer,
    disabled_tracers,
    portfolio_runnable_config,
    tracing_disabled_handler,
)


def main() -> int:
    import langchain_core

    print(f"langchain-core {langchain_core.__version__}")

    baseline = [type(h).__name__ for h in get_callback_manager_for_config({}).handlers]
    print(f"baseline (no config)        : {baseline}")
    if "LangChainTracer" not in baseline:
        print("FAIL: control case — tracing is not actually on in this env")
        return 1

    # thread_id on purpose: `configurable` entries become langsmith-inheritable
    # metadata, which sends _configure() through copy_with_metadata_defaults()
    # and hands the resolved manager a *copy* of the handler. Every real
    # portfolio-graph invocation passes a thread_id, so this is the live path.
    config = portfolio_runnable_config(thread_id="image-check", metadata={"k": "v"})
    handlers = get_callback_manager_for_config(config).handlers
    print(f"portfolio_runnable_config() : {[type(h).__name__ for h in handlers]}")
    live = [
        h
        for h in handlers
        if isinstance(h, LangChainTracer) and not isinstance(h, TracingDisabledTracer)
    ]
    if live:
        print(f"FAIL: live tracer attached: {live}")
        return 1

    # Assert on the handler that would actually have written, not on the
    # module singleton — they are different objects once a copy is made.
    resolved = disabled_tracers(config)
    if not resolved:
        print("FAIL: no TracingDisabledTracer survived config resolution")
        return 1
    client = resolved[0].client
    before = len(client.calls)

    result = (RunnableLambda(lambda v: v * 2) | RunnableLambda(lambda v: v + 1)).invoke(
        3, config
    )
    calls = client.calls[before:]
    is_copy = resolved[0] is not tracing_disabled_handler()
    print(f"handler observed is a copy  : {is_copy}")
    print(f"invoke result               : {result}")
    print(f"langsmith client calls      : {calls}")
    if result != 7 or calls:
        print("FAIL: invocation misbehaved or touched the LangSmith client")
        return 1

    print("OK: portfolio_runnable_config() suppresses tracing in this image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
