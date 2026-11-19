import asyncio

from engine.sync_playwright_thread import isolate_from_running_asyncio_loop


def test_isolate_is_noop_without_running_loop():
    assert isolate_from_running_asyncio_loop() is False


def test_isolate_reports_visible_running_loop():
    result = {}

    async def _probe():
        result["isolated"] = isolate_from_running_asyncio_loop()

    asyncio.run(_probe())
    assert result["isolated"] is True
