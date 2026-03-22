from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot import db
from bot.services.importer import run_import

logger = logging.getLogger(__name__)

INTERVALS = {
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "6h": 6 * 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
}

INTERVAL_LABELS = {
    "30m": "30 минут",
    "1h": "1 час",
    "2h": "2 часа",
    "6h": "6 часов",
    "12h": "12 часов",
    "24h": "24 часа",
}


class Scheduler:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self, interval_key: str) -> None:
        await self.stop()
        seconds = INTERVALS.get(interval_key)
        if not seconds:
            raise ValueError(f"Неизвестный интервал: {interval_key}")

        await db.set_setting("auto_import_interval", interval_key)
        await db.set_setting("auto_import_enabled", "1")
        self._running = True
        self._task = asyncio.create_task(self._loop(seconds))
        logger.info("Scheduler started with interval %s (%ds)", interval_key, seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        await db.set_setting("auto_import_enabled", "0")
        logger.info("Scheduler stopped")

    async def _loop(self, interval: int) -> None:
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                admin_id = await db.get_setting("admin_chat_id")
                result = await run_import(self.bot, trigger_type="auto")
                if admin_id and result.posted > 0:
                    await self.bot.send_message(
                        chat_id=int(admin_id),
                        text=f"Авто-импорт завершён:\n{result.summary}",
                    )
            except Exception as e:
                logger.error("Auto-import error: %s", e)
                admin_id = await db.get_setting("admin_chat_id")
                if admin_id:
                    try:
                        await self.bot.send_message(
                            chat_id=int(admin_id),
                            text=f"Ошибка авто-импорта: {e}",
                        )
                    except Exception:
                        pass

    async def restore(self) -> None:
        """Restore scheduler state from DB on startup."""
        enabled = await db.get_setting("auto_import_enabled")
        interval = await db.get_setting("auto_import_interval")
        if enabled == "1" and interval and interval in INTERVALS:
            await self.start(interval)
