"""Start Playwright sync API from a worker thread.

run_engine.py runs asyncio on the main thread. Playwright's sync
client refuses to start if the current thread can see that running
loop. Worker threads must isolate themselves first.
"""

from __future__ import annotations

import asyncio


def isolate_from_running_asyncio_loop() -> bool:
    """Detach this thread from a visible running asyncio loop.

    Returns True if a running loop was visible and replaced.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    asyncio.set_event_loop(asyncio.new_event_loop())
    return True


def start_sync_playwright():
    isolate_from_running_asyncio_loop()
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()
