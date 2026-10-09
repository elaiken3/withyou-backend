import asyncio
import logging
import signal
from datetime import UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .services.apns import close_client
from .services.scheduler import tick

logger = logging.getLogger("withyou.worker")


async def main():
    logging.basicConfig(level=logging.INFO)
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        tick,
        "interval",
        seconds=settings.scheduler_interval_seconds,
        id="tick",
        replace_existing=True,
    )
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, sig), stop_event.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        logger.info("shutting down worker")
        await close_client()
        scheduler.shutdown(wait=False)

if __name__ == "__main__":
    asyncio.run(main())
