from __future__ import annotations

import logging
import math

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot import db
from bot.roapp.client import RoAppClient
from bot.roapp.models import RoAppCategory, RoAppProduct
from bot.services.importer import _load_smartphone_categories
from bot.telegram.formatter import build_media_group, format_caption
from bot.telegram.publisher import publish_media_group, publish_text

router = Router()
logger = logging.getLogger(__name__)

DISPLAY_PER_PAGE = 5
SMARTPHONE_ROOT = "718966"

_smartphones: list[RoAppProduct] = []
_all_smartphones: list[RoAppProduct] = []  # unfiltered by subcategory
_selected_indices: set[int] = set()
_subcategories: list[RoAppCategory] = []
_selected_subcats: set[str] = set()  # selected subcategory IDs
_loading = False


async def _load_smartphones() -> list[RoAppProduct]:
    global _smartphones, _all_smartphones, _loading, _subcategories
    _loading = True
    _selected_indices.clear()
    api_token = await db.get_setting("roapp_api_token")
    if not api_token:
        _loading = False
        return []
    client = RoAppClient(api_token)
    try:
        smart_cats = await _load_smartphone_categories(client)

        # Load subcategories (direct children of Smartphones root)
        all_cats = await client.get_categories()
        _subcategories = sorted(
            [c for c in all_cats if c.parent_id == SMARTPHONE_ROOT],
            key=lambda c: c.title,
        )

        # Load from warehouse (has stock info)
        warehouse_id = await db.get_setting("warehouse_id")
        if warehouse_id:
            raw = await client._get_all_pages(f"/warehouse/goods/{warehouse_id}")
            from bot.roapp.client import normalize_product
            products = [normalize_product(item) for item in raw]
        else:
            products = await client.get_products()

        # Filter only smartphones that are in stock
        _all_smartphones = [p for p in products if p.category_id in smart_cats and p.stock > 0]
        _apply_subcat_filter()
        return _smartphones
    finally:
        _loading = False
        await client.close()


def _apply_subcat_filter():
    """Filter _all_smartphones by selected subcategories into _smartphones."""
    global _smartphones
    _selected_indices.clear()
    if not _selected_subcats:
        filtered = list(_all_smartphones)
    else:
        filtered = [p for p in _all_smartphones if p.category_id in _selected_subcats]
    # In-stock first, then sold
    _smartphones = sorted(filtered, key=lambda p: (p.stock <= 0, p.name))


def _total_pages() -> int:
    return max(1, math.ceil(len(_smartphones) / DISPLAY_PER_PAGE))


def _header() -> str:
    sel = len(_selected_indices)
    subcat_info = ""
    if _selected_subcats:
        names = [c.title for c in _subcategories if c.id in _selected_subcats]
        subcat_info = f"\nФільтр: {', '.join(names[:3])}{'…' if len(names) > 3 else ''}"
    return (
        f"<b>Смартфони</b> (всього: {len(_smartphones)}, обрано: {sel}):{subcat_info}\n"
        "Відмітьте та натисніть «Опублікувати обрані»."
    )


def _brands_with_stock() -> set[str]:
    """Category IDs that have at least one in-stock product."""
    return {p.category_id for p in _all_smartphones}


def _build_subcat_kb() -> types.InlineKeyboardMarkup:
    """Build subcategory (brand) selection keyboard. Only brands with stock."""
    in_stock = _brands_with_stock()
    buttons: list[list[types.InlineKeyboardButton]] = []
    for cat in _subcategories:
        if cat.id not in in_stock:
            continue
        check = "✅" if cat.id in _selected_subcats else "⬜"
        buttons.append([
            types.InlineKeyboardButton(
                text=f"{check} {cat.title}",
                callback_data=f"pr:sc:{cat.id}",
            )
        ])
    buttons.append([
        types.InlineKeyboardButton(text="Обрати всі", callback_data="pr:sca"),
        types.InlineKeyboardButton(text="Скинути", callback_data="pr:scc"),
    ])
    buttons.append([
        types.InlineKeyboardButton(text="✅ Показати товари", callback_data="pr:scok"),
    ])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_kb(page: int) -> types.InlineKeyboardMarkup:
    total = _total_pages()
    start = page * DISPLAY_PER_PAGE
    items = _smartphones[start: start + DISPLAY_PER_PAGE]

    buttons: list[list[types.InlineKeyboardButton]] = []
    for i, p in enumerate(items):
        idx = start + i
        name = p.name[:28] + ".." if len(p.name) > 28 else p.name
        price = f" | {int(p.price)}г." if p.price > 0 else ""
        check = "✅" if idx in _selected_indices else "⬜"
        buttons.append([
            types.InlineKeyboardButton(text=f"{check} {name}{price}", callback_data=f"pr:s:{idx}"),
            types.InlineKeyboardButton(text="👁", callback_data=f"pr:pre:{idx}"),
        ])

    nav: list[types.InlineKeyboardButton] = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"pr:p:{page - 1}"))
    nav.append(types.InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="pr:noop"))
    if page < total - 1:
        nav.append(types.InlineKeyboardButton(text="➡️", callback_data=f"pr:p:{page + 1}"))
    buttons.append(nav)

    buttons.append([
        types.InlineKeyboardButton(text="Обрати все на стор.", callback_data=f"pr:ap:{page}"),
        types.InlineKeyboardButton(text="Скинути", callback_data="pr:clr"),
    ])

    count = len(_selected_indices)
    if count > 0:
        buttons.append([
            types.InlineKeyboardButton(text=f"📢 Опублікувати обрані ({count})", callback_data="pr:pub"),
        ])

    buttons.append([
        types.InlineKeyboardButton(text="🔄 Оновити список", callback_data="pr:reload"),
        types.InlineKeyboardButton(text="📱 Бренди", callback_data="pr:brands"),
    ])

    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("products"))
async def cmd_products(message: Message) -> None:
    _selected_indices.clear()
    _selected_subcats.clear()
    msg = await message.answer("Завантажую смартфони...")
    await _load_smartphones()
    if not _all_smartphones:
        await msg.edit_text("Смартфони не знайдено. Перевірте /setup")
        return
    if _subcategories:
        await msg.edit_text(
            f"<b>Оберіть бренди</b> (підкатегорії):\n"
            f"Всього смартфонів: {len(_all_smartphones)}",
            parse_mode="HTML",
            reply_markup=_build_subcat_kb(),
        )
    else:
        await msg.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(0))


@router.callback_query(lambda c: c.data and c.data.startswith("pr:"))
async def on_callback(callback: types.CallbackQuery) -> None:
    parts = callback.data.split(":")
    act = parts[1]

    if act == "noop":
        await callback.answer()
        return

    # Subcategory selection handlers
    if act == "sc":
        cat_id = parts[2]
        _selected_subcats.symmetric_difference_update({cat_id})
        await callback.message.edit_reply_markup(reply_markup=_build_subcat_kb())
        await callback.answer()
        return

    if act == "sca":
        _selected_subcats.update(c.id for c in _subcategories)
        await callback.message.edit_reply_markup(reply_markup=_build_subcat_kb())
        await callback.answer("Всі обрані")
        return

    if act == "scc":
        _selected_subcats.clear()
        await callback.message.edit_reply_markup(reply_markup=_build_subcat_kb())
        await callback.answer("Скинуто")
        return

    if act == "scok":
        _apply_subcat_filter()
        if not _smartphones:
            await callback.answer("Немає товарів для обраних брендів", show_alert=True)
            return
        await callback.message.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(0))
        await callback.answer()
        return

    if act == "brands":
        # Go back to subcategory selection
        _selected_indices.clear()
        await callback.message.edit_text(
            f"<b>Оберіть бренди</b> (підкатегорії):\n"
            f"Всього смартфонів: {len(_all_smartphones)}",
            parse_mode="HTML",
            reply_markup=_build_subcat_kb(),
        )
        await callback.answer()
        return

    if act == "reload":
        await callback.message.edit_text("Завантажую смартфони...")
        saved_subcats = set(_selected_subcats)
        _selected_indices.clear()
        await _load_smartphones()
        _selected_subcats.update(saved_subcats)
        _apply_subcat_filter()
        if not _smartphones:
            await callback.message.edit_text("Смартфони не знайдено.")
            return
        await callback.message.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(0))
        await callback.answer("Оновлено")
        return

    if act == "p":
        pg = int(parts[2])
        await callback.message.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(pg))
        await callback.answer()
        return

    if act == "s":
        idx = int(parts[2])
        _selected_indices.symmetric_difference_update({idx})
        pg = idx // DISPLAY_PER_PAGE
        await callback.message.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(pg))
        await callback.answer()
        return

    if act == "ap":
        pg = int(parts[2])
        start = pg * DISPLAY_PER_PAGE
        end = min(start + DISPLAY_PER_PAGE, len(_smartphones))
        for i in range(start, end):
            _selected_indices.add(i)
        await callback.message.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(pg))
        await callback.answer(f"Обрано {end - start}")
        return

    if act == "clr":
        _selected_indices.clear()
        await callback.message.edit_text(_header(), parse_mode="HTML", reply_markup=_build_kb(0))
        await callback.answer("Скинуто")
        return

    if act == "pre":
        idx = int(parts[2])
        if idx >= len(_smartphones):
            await callback.answer("Не знайдено")
            return
        product = _smartphones[idx]
        caption = format_caption(product)
        posted = await db.is_product_posted(product.sku) if product.sku else False
        status = "✅ Вже опубліковано" if posted else "⬜ Не опубліковано"
        await callback.message.answer(f"{caption}\n\n<i>{status}</i>", parse_mode="HTML")
        await callback.answer()
        return

    if act == "pub":
        if not _selected_indices:
            await callback.answer("Нічого не обрано!", show_alert=True)
            return
        channel_id = await db.get_setting("channel_id")
        if not channel_id:
            await callback.answer("Канал не налаштовано! /setup", show_alert=True)
            return

        total = len(_selected_indices)
        await callback.message.edit_text(f"Публікую {total} смартфонів...")
        await callback.answer()

        published = 0
        skipped = 0
        errors = 0
        bot = callback.bot

        for idx in sorted(_selected_indices):
            if idx >= len(_smartphones):
                errors += 1
                continue
            product = _smartphones[idx]
            if product.sku and await db.is_product_posted(product.sku):
                skipped += 1
                continue
            try:
                media = await build_media_group(product)
                if media:
                    msgs = await publish_media_group(bot, channel_id, media)
                    mid = str(msgs[0].message_id) if msgs else None
                else:
                    caption = format_caption(product)
                    m = await publish_text(bot, channel_id, caption)
                    mid = str(m.message_id) if m else None
                if mid and product.sku:
                    await db.add_posted_product(product.sku, product.id, product.name, product.price, mid, channel_id, product.stock)
                    published += 1
                elif mid:
                    published += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error("Publish error %s: %s", product.sku, e)
                errors += 1

        _selected_indices.clear()
        await callback.message.edit_text(
            f"<b>Публікацію завершено!</b>\n\n"
            f"Опубліковано: {published}\n"
            f"Пропущено (дублі): {skipped}\n"
            f"Помилок: {errors}",
            parse_mode="HTML",
        )
