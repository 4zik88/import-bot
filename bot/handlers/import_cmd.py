from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot import db
from bot.services.importer import run_import
from bot.telegram.publisher import delete_message

router = Router()


@router.message(Command("import"))
async def cmd_import(message: Message) -> None:
    api_token = await db.get_setting("roapp_api_token")
    channel_id = await db.get_setting("channel_id")
    if not api_token or not channel_id:
        await message.answer("Сначала настройте бота: /setup")
        return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Запустить импорт", callback_data="imp:start"),
            types.InlineKeyboardButton(text="Отмена", callback_data="imp:cancel"),
        ]
    ])

    selected = await db.get_selected_categories()
    posted = await db.get_posted_products_count()

    await message.answer(
        f"<b>Импорт товаров</b>\n\n"
        f"Канал: <code>{channel_id}</code>\n"
        f"Фильтр категорий: {len(selected) if selected else 'все'}\n"
        f"Уже опубликовано: {posted}\n\n"
        f"Запустить импорт?",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("imp:"))
async def process_import_callback(callback: types.CallbackQuery) -> None:
    action = callback.data.split(":")[1]

    if action == "cancel":
        await callback.message.edit_text("Импорт отменён.")
        await callback.answer()
        return

    if action == "start":
        await callback.message.edit_text("Импорт запущен...")
        await callback.answer()

        async def progress(result, current, total):
            try:
                await callback.message.edit_text(
                    f"Импорт: {current}/{total}\n{result.summary}"
                )
            except Exception:
                pass

        try:
            result = await run_import(callback.bot, trigger_type="manual", progress_callback=progress)
            await callback.message.edit_text(
                f"<b>Импорт завершён!</b>\n\n{result.summary}",
                parse_mode="HTML",
            )
        except ValueError as e:
            await callback.message.edit_text(f"Ошибка: {e}")
        except Exception as e:
            await callback.message.edit_text(f"Ошибка импорта: {e}")


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    history = await db.get_import_history(10)
    if not history:
        await message.answer("История импортов пуста.")
        return

    lines = ["<b>История импортов:</b>\n"]
    for h in history:
        status_icon = "✅" if h["status"] == "completed" else "⚠️" if "error" in h["status"] else "🔄"
        trigger = "⚡" if h["trigger_type"] == "manual" else "🔄"
        lines.append(
            f"{status_icon}{trigger} {h['started_at']}\n"
            f"   Найдено: {h['products_found']}, "
            f"Опубл.: {h['products_posted']}, "
            f"Проп.: {h['products_skipped']}, "
            f"Ошибок: {h['errors']}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Да, сбросить", callback_data="reset:confirm"),
            types.InlineKeyboardButton(text="Отмена", callback_data="reset:cancel"),
        ]
    ])

    count = await db.get_posted_products_count()
    await message.answer(
        f"Сбросить историю публикаций ({count} записей)?\n"
        "После сброса все товары могут быть опубликованы повторно.",
        reply_markup=kb,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("reset:"))
async def process_reset_callback(callback: types.CallbackQuery) -> None:
    action = callback.data.split(":")[1]
    if action == "confirm":
        deleted = await db.clear_posted_products()
        await callback.message.edit_text(f"Удалено {deleted} записей. История очищена.")
    else:
        await callback.message.edit_text("Сброс отменён.")
    await callback.answer()


@router.message(Command("clear_channel"))
async def cmd_clear_channel(message: Message) -> None:
    count = await db.get_posted_products_count()
    if count == 0:
        await message.answer("Немає опублікованих товарів для видалення.")
        return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text=f"Так, видалити {count} постів", callback_data="clch:confirm"),
            types.InlineKeyboardButton(text="Скасувати", callback_data="clch:cancel"),
        ]
    ])
    await message.answer(
        f"<b>Очистити канал?</b>\n\n"
        f"Буде видалено {count} постів з каналу та очищено базу.\n"
        f"Після цього можна запустити /import заново.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("clch:"))
async def process_clear_channel(callback: types.CallbackQuery) -> None:
    action = callback.data.split(":")[1]

    if action == "cancel":
        await callback.message.edit_text("Скасовано.")
        await callback.answer()
        return

    if action == "confirm":
        await callback.answer()
        posted = await db.get_all_posted_products()
        total = len(posted)
        deleted = 0
        errors = 0

        await callback.message.edit_text(f"Видаляю {total} постів з каналу...")

        for pp in posted:
            msg_id = pp.get("message_id")
            ch_id = pp.get("channel_id")
            sku = pp.get("sku", "")
            if msg_id and ch_id:
                ok = await delete_message(callback.bot, ch_id, msg_id)
                if ok:
                    deleted += 1
                else:
                    errors += 1
            if sku:
                await db.delete_posted_product(sku)

        await callback.message.edit_text(
            f"<b>Канал очищено!</b>\n\n"
            f"Видалено постів: {deleted}\n"
            f"Помилок: {errors}\n\n"
            f"Тепер можна запустити /import",
            parse_mode="HTML",
        )
