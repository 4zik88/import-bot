from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.db import init_db
from bot.handlers import get_root_router
from bot.handlers.schedule import set_scheduler
from bot.services.scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(get_root_router())

    scheduler = Scheduler(bot)
    set_scheduler(scheduler)

    async def on_startup() -> None:
        me = await bot.get_me()
        logger.info("Bot started: @%s", me.username)
        await scheduler.restore()

    async def on_shutdown() -> None:
        await scheduler.stop()
        logger.info("Bot stopped")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
