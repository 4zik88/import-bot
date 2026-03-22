from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot import db
from bot.services.scheduler import INTERVAL_LABELS, Scheduler

router = Router()

_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler | None:
    return _scheduler


def set_scheduler(scheduler: Scheduler) -> None:
    global _scheduler
    _scheduler = scheduler


@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    if not _scheduler:
        await message.answer("Планировщик не инициализирован.")
        return

    is_running = _scheduler.is_running
    interval = await db.get_setting("auto_import_interval")
    label = INTERVAL_LABELS.get(interval, interval) if interval else "не выбран"

    buttons: list[list[types.InlineKeyboardButton]] = []
    row: list[types.InlineKeyboardButton] = []
    for key, name in INTERVAL_LABELS.items():
        check = "✅ " if interval == key and is_running else ""
        row.append(types.InlineKeyboardButton(text=f"{check}{name}", callback_data=f"sch:set:{key}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if is_running:
        buttons.append([types.InlineKeyboardButton(text="⏹ Остановить", callback_data="sch:stop")])
    buttons.append([types.InlineKeyboardButton(text="Закрыть", callback_data="sch:close")])

    status = f"✅ Включён (каждые {label})" if is_running else "❌ Выключен"

    await message.answer(
        f"<b>Автоимпорт:</b> {status}\n\nВыберите интервал:",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("sch:"))
async def process_schedule_callback(callback: types.CallbackQuery) -> None:
    if not _scheduler:
        await callback.answer("Планировщик не инициализирован.")
        return

    parts = callback.data.split(":")
    action = parts[1]

    if action == "close":
        await callback.message.edit_text("Настройка автоимпорта закрыта.")
        await callback.answer()
        return

    if action == "stop":
        await _scheduler.stop()
        await callback.message.edit_text("Автоимпорт остановлен.")
        await callback.answer()
        return

    if action == "set":
        interval_key = parts[2]
        label = INTERVAL_LABELS.get(interval_key, interval_key)

        api_token = await db.get_setting("roapp_api_token")
        channel_id = await db.get_setting("channel_id")
        if not api_token or not channel_id:
            await callback.answer("Сначала настройте бота: /setup", show_alert=True)
            return

        await _scheduler.start(interval_key)
        await callback.message.edit_text(
            f"✅ Автоимпорт включён: каждые {label}\n\n"
            f"Первый импорт будет выполнен через {label}."
        )
        await callback.answer()
