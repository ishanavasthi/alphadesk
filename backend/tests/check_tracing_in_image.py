"""Standalone tracing check runnable inside the Docker image (no pytest).

The image resolves transitive deps freshly, so it can carry a *different*
langchain-core than the dev venv (1.5.5 vs 1.4.9 when F1 shipped) — and
`graph.portfolio_config` leans on a langchain-core internal. This script is the
cheap way to re-prove the kill switch against whatever the image actually
installed:

    docker build -t alphadesk-f1 .
    docker run --rm -e LANGCHAIN_TRACING_V2=true -e LANGCHAIN_API_KEY=dummy \
      alphadesk-f1 python -m tests.check_tracing_in_image

Exits non-zero with a diagnostic if a live tracer would be attached.
"""

from __future__ import annotations

import sys

from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.config import get_callback_manager_for_config
from langchain_core.tracers.langchain import LangChainTracer

from graph.portfolio_config import (
    TracingDisabledTracer,
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

    handler = tracing_disabled_handler()
    before = len(handler.client.calls)
    result = (RunnableLambda(lambda v: v * 2) | RunnableLambda(lambda v: v + 1)).invoke(
        3, config
    )
    calls = handler.client.calls[before:]
    print(f"invoke result               : {result}")
    print(f"langsmith client calls      : {calls}")
    if result != 7 or calls:
        print("FAIL: invocation misbehaved or touched the LangSmith client")
        return 1

    print("OK: portfolio_runnable_config() suppresses tracing in this image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
