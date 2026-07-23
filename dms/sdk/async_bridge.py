from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar


T = TypeVar("T")


def run_coroutine(coroutine: Coroutine[object, object, T]) -> T:
    """Run a core async lifecycle operation from the synchronous DMS API."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    # A synchronous API cannot drive the caller's already-running event loop.
    # Use an isolated thread so sync DMS calls remain valid in async hosts.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dms-core") as executor:
        return executor.submit(asyncio.run, coroutine).result()
