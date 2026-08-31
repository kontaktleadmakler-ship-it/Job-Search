
import asyncio
import logging

log = logging.getLogger(__name__)

class ScanScheduler:
    """Tiny dependency-free interval scheduler for one background job."""
    def __init__(self, scan_callback, interval_minutes: int):
        self.scan_callback = scan_callback
        self.interval_minutes = interval_minutes
        self.task = None
        self.running = False

    def start(self):
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())

    def stop(self):
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()

    async def _loop(self):
        while self.running:
            try:
                await asyncio.sleep(max(60, self.interval_minutes * 60))
                if self.running:
                    await self.scan_callback()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("scheduled scan failed")
