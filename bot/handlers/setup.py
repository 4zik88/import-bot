from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import db
from bot.roapp.client import RoAppClient

router = Router()


class SetupStates(StatesGroup):
    waiting_api_token = State()
    waiting_channel = State()
    waiting_warehouse = State()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("Дію скасовано.")
    else:
        await message.answer("Немає активних дій.")


@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext) -> None:
    current_token = await db.get_setting("roapp_api_token")
    text = "Введите API-токен RoApp:"
    if current_token:
        masked = current_token[:8] + "..." + current_token[-4:]
        text = f"Текущий токен: <code>{masked}</code>\n\nВведите новый API-токен или /skip для пропуска:"
    await state.set_state(SetupStates.waiting_api_token)
    await message.answer(text, parse_mode="HTML")


@router.message(SetupStates.waiting_api_token)
async def process_api_token(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip() == "/skip":
        current = await db.get_setting("roapp_api_token")
        if not current:
            await message.answer("Токен не настроен, пропустить нельзя. Введите API-токен:")
            return
        await _ask_channel(message, state)
        return

    token = message.text.strip() if message.text else ""
    if not token or len(token) < 10:
        await message.answer("Токен слишком короткий. Попробуйте ещё раз:")
        return

    msg = await message.answer("Проверяю соединение...")
    client = RoAppClient(token)
    try:
        ok = await client.test_connection()
    finally:
        await client.close()

    if not ok:
        await msg.edit_text("Не удалось подключиться к RoApp. Проверьте токен и попробуйте снова:")
        return

    await db.set_setting("roapp_api_token", token)
    await msg.edit_text("Токен принят!")
    await _ask_channel(message, state)


async def _ask_channel(message: Message, state: FSMContext) -> None:
    current_channel = await db.get_setting("channel_id")
    text = "Введите ID или @username канала:"
    if current_channel:
        text = f"Текущий канал: <code>{current_channel}</code>\n\nВведите новый канал или /skip:"
    await state.set_state(SetupStates.waiting_channel)
    await message.answer(text, parse_mode="HTML")


@router.message(SetupStates.waiting_channel)
async def process_channel(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip() == "/skip":
        current = await db.get_setting("channel_id")
        if not current:
            await message.answer("Канал не настроен, пропустить нельзя. Введите ID или @username канала:")
            return
        await _ask_warehouse(message, state)
        return

    channel = message.text.strip() if message.text else ""
    if not channel:
        await message.answer("Введите ID канала (например -1001234567890) или @username:")
        return

    if not channel.startswith("@") and not channel.startswith("-"):
        await message.answer("ID канала должен начинаться с - или @. Попробуйте ещё раз:")
        return

    # Auto-fix: add -100 prefix for supergroups/channels if missing
    if channel.startswith("-") and not channel.startswith("-100"):
        channel = "-100" + channel.lstrip("-")

    # Validate that bot can access the channel
    try:
        chat = await message.bot.get_chat(channel)
        channel = str(chat.id)  # Use the resolved numeric ID
    except Exception:
        await message.answer("Бот не может найти этот канал. Убедитесь что бот добавлен как администратор.")
        return

    await db.set_setting("channel_id", channel)
    await db.set_setting("admin_chat_id", str(message.from_user.id))
    await message.answer(f"Канал установлен: <code>{channel}</code>", parse_mode="HTML")
    await _ask_warehouse(message, state)


async def _ask_warehouse(message: Message, state: FSMContext) -> None:
    api_token = await db.get_setting("roapp_api_token")
    if not api_token:
        await state.clear()
        return

    msg = await message.answer("Загружаю список складов...")
    client = RoAppClient(api_token)
    try:
        warehouses = await client.get_warehouses()
    finally:
        await client.close()

    if not warehouses:
        await msg.edit_text("Складов не найдено. Настройка завершена.")
        await state.clear()
        return

    if len(warehouses) == 1:
        await db.set_setting("warehouse_id", warehouses[0].id)
        await msg.edit_text(f"Склад выбран автоматически: {warehouses[0].name}\n\nНастройка завершена!")
        await state.clear()
        return

    buttons = []
    for w in warehouses:
        buttons.append([types.InlineKeyboardButton(text=w.name, callback_data=f"wh:{w.id}")])
    buttons.append([types.InlineKeyboardButton(text="Пропустить", callback_data="wh:skip")])

    await state.set_state(SetupStates.waiting_warehouse)
    await msg.edit_text(
        "Выберите склад для данных о наличии:",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(SetupStates.waiting_warehouse, lambda c: c.data and c.data.startswith("wh:"))
async def process_warehouse(callback: types.CallbackQuery, state: FSMContext) -> None:
    wh_id = callback.data.split(":", 1)[1]
    if wh_id != "skip":
        await db.set_setting("warehouse_id", wh_id)
        await callback.message.edit_text(f"Склад выбран. Настройка завершена!")
    else:
        await callback.message.edit_text("Склад не выбран. Настройка завершена!")
    await state.clear()
    await callback.answer()
