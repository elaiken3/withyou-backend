import asyncio
from datetime import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .services.scheduler import tick
from .services.apns import close_client



async def main():
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scheduler.add_job(
        tick,
        "interval",
        seconds=settings.scheduler_interval_seconds,
        id="tick",
        replace_existing=True,
    )
    scheduler.start()

    try:
        # keep process alive
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        close_client()
        scheduler.shutdown(wait=False)

if __name__ == "__main__":
    asyncio.run(main())
