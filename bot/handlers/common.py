from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings

router = Router()


@router.message.outer_middleware()
async def admin_middleware(handler, event: Message, data: dict):
    if event.from_user and event.from_user.id not in settings.all_admin_ids:
        return
    return await handler(event, data)


@router.callback_query.outer_middleware()
async def admin_callback_middleware(handler, event: types.CallbackQuery, data: dict):
    if event.from_user and event.from_user.id not in settings.all_admin_ids:
        await event.answer("Доступ заборонено", show_alert=True)
        return
    return await handler(event, data)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>SOTIK — Імпорт смартфонів</b>\n\n"
        "Бот для публікації смартфонів з RoApp у Telegram-канал.\n\n"
        "<b>Команди:</b>\n"
        "/setup — Налаштування API-токена і каналу\n"
        "/products — Перегляд смартфонів\n"
        "/import — Запустити імпорт\n"
        "/history — Історія імпортів\n"
        "/clear_channel — Видалити всі пости з каналу\n"
        "/reset — Скинути історію публікацій\n"
        "/schedule — Налаштування автоімпорту\n"
        "/status — Поточний статус\n"
        "/help — Допомога",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Інструкція:</b>\n\n"
        "1. /setup — Введіть API-токен RoApp та вкажіть канал\n"
        "2. /products — Перегляньте смартфони, оберіть та опублікуйте\n"
        "3. /import — Масовий імпорт усіх нових смартфонів\n"
        "4. /schedule — Автоімпорт з оновленням цін та статусів\n\n"
        "<b>Можливості:</b>\n"
        "• Тільки категорія Смартфони\n"
        "• До 10 фото в одному пості\n"
        "• Відстеження змін: ціна, статус (продано)\n"
        "• Автоматичне оновлення постів у каналі\n"
        "• /reset — скинути для повторної публікації",
        parse_mode="HTML",
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    from bot import db
    from bot.services.scheduler import INTERVAL_LABELS

    api_token = await db.get_setting("roapp_api_token")
    channel_id = await db.get_setting("channel_id")
    posted_count = await db.get_posted_products_count()
    auto_enabled = await db.get_setting("auto_import_enabled")
    auto_interval = await db.get_setting("auto_import_interval")

    lines = ["<b>Статус бота:</b>\n"]
    lines.append(f"API-токен: {'✅ налаштовано' if api_token else '❌ не налаштовано'}")
    lines.append(f"Канал: {channel_id or '❌ не налаштовано'}")
    lines.append(f"Товарів опубліковано: {posted_count}")

    if auto_enabled == "1" and auto_interval:
        label = INTERVAL_LABELS.get(auto_interval, auto_interval)
        lines.append(f"Автоімпорт: ✅ кожні {label}")
    else:
        lines.append("Автоімпорт: ❌ вимкнено")

    await message.answer("\n".join(lines), parse_mode="HTML")
