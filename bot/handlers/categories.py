from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from bot import db
from bot.roapp.client import RoAppClient

router = Router()

CATS_PER_PAGE = 8

# Cache: all categories (flat) and top-level only
_all_categories: list[dict] = []
_top_categories: list[dict] = []


def _build_categories_kb(
    categories: list[dict],
    selected_ids: set[str],
    page: int = 0,
    total_pages: int = 1,
) -> types.InlineKeyboardMarkup:
    buttons: list[list[types.InlineKeyboardButton]] = []
    for cat in categories:
        cid = cat["id"]
        name = cat["title"]
        children_count = cat.get("children_count", 0)
        suffix = f" ({children_count})" if children_count > 0 else ""
        check = "✅" if cid in selected_ids else "⬜"
        buttons.append([
            types.InlineKeyboardButton(
                text=f"{check} {name}{suffix}",
                callback_data=f"cat:t:{cid}:{page}",
            )
        ])

    nav: list[types.InlineKeyboardButton] = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"cat:p:{page - 1}"))
    nav.append(types.InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="cat:noop"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton(text="➡️", callback_data=f"cat:p:{page + 1}"))
    buttons.append(nav)

    buttons.append([
        types.InlineKeyboardButton(text="Выбрать все", callback_data="cat:all"),
        types.InlineKeyboardButton(text="Снять все", callback_data="cat:none"),
    ])
    buttons.append([
        types.InlineKeyboardButton(text="Готово ✅", callback_data="cat:done"),
    ])

    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def _get_children_ids(parent_id: str) -> set[str]:
    """Get all descendant category IDs for a parent (recursively)."""
    result: set[str] = set()
    queue = [parent_id]
    while queue:
        pid = queue.pop()
        for cat in _all_categories:
            if cat.get("parent_id") == pid and cat["id"] not in result:
                result.add(cat["id"])
                queue.append(cat["id"])
    return result


async def _load_categories() -> None:
    global _all_categories, _top_categories
    api_token = await db.get_setting("roapp_api_token")
    if not api_token:
        _all_categories = []
        _top_categories = []
        return
    client = RoAppClient(api_token)
    try:
        cats = await client.get_categories()
        _all_categories = [{"id": str(c.id), "title": c.title, "parent_id": str(c.parent_id) if c.parent_id else None} for c in cats]

        # Build top-level list with children count
        all_ids = {c["id"] for c in _all_categories}
        top: list[dict] = []
        for c in _all_categories:
            if not c.get("parent_id") or c["parent_id"] not in all_ids:
                children = _get_children_ids(c["id"])
                top.append({**c, "children_count": len(children)})
        _top_categories = sorted(top, key=lambda x: x["title"])
    finally:
        await client.close()


@router.message(Command("categories"))
async def cmd_categories(message: Message) -> None:
    msg = await message.answer("Загружаю категорії...")
    await _load_categories()
    if not _top_categories:
        await msg.edit_text("Категорії не знайдено. Перевірте налаштування API-токена (/setup)")
        return

    selected = await db.get_selected_category_ids()
    total_pages = max(1, (len(_top_categories) + CATS_PER_PAGE - 1) // CATS_PER_PAGE)
    page_cats = _top_categories[:CATS_PER_PAGE]

    await msg.edit_text(
        f"<b>Категорії</b> (всього: {len(_top_categories)}, обрано: {len(selected)}):\n\n"
        "Оберіть категорії для фільтрації товарів.\n"
        "Якщо нічого не обрано — імпортуються всі товари.",
        parse_mode="HTML",
        reply_markup=_build_categories_kb(page_cats, selected, 0, total_pages),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cat:"))
async def process_category_callback(callback: types.CallbackQuery) -> None:
    data = callback.data
    action = data.split(":")[1]

    if not _top_categories:
        await callback.answer("Натисніть /categories для завантаження")
        return

    total_pages = max(1, (len(_top_categories) + CATS_PER_PAGE - 1) // CATS_PER_PAGE)

    if action == "noop":
        await callback.answer()
        return

    page = 0

    if action == "t":  # toggle
        parts = data.split(":")
        cat_id = parts[2]
        page = int(parts[3])
        cat = next((c for c in _top_categories if c["id"] == cat_id), None)
        if cat:
            added = await db.toggle_category(cat_id, cat["title"], cat.get("parent_id"))
            # Also toggle all children
            children_ids = _get_children_ids(cat_id)
            if added:
                children_data = [
                    {"category_id": c["id"], "name": c["title"], "parent_id": c.get("parent_id")}
                    for c in _all_categories if c["id"] in children_ids
                ]
                if children_data:
                    await db.add_categories_bulk(children_data)
            else:
                for cid in children_ids:
                    await db.toggle_category(cid, "", None)  # remove if exists

    elif action == "p":  # page
        page = int(data.split(":")[2])

    elif action == "all":
        await db.clear_selected_categories()
        await db.add_categories_bulk([
            {"category_id": c["id"], "name": c["title"], "parent_id": c.get("parent_id")}
            for c in _all_categories
        ])

    elif action == "none":
        await db.clear_selected_categories()

    elif action == "done":
        selected = await db.get_selected_category_ids()
        text = f"Обрано категорій: {len(selected)}"
        if not selected:
            text = "Фільтр за категоріями вимкнено — імпортуються всі товари."
        await callback.message.edit_text(text)
        await callback.answer()
        return

    else:
        await callback.answer()
        return

    selected = await db.get_selected_category_ids()
    page = min(page, total_pages - 1)
    start = page * CATS_PER_PAGE
    page_cats = _top_categories[start: start + CATS_PER_PAGE]

    try:
        await callback.message.edit_text(
            f"<b>Категорії</b> (всього: {len(_top_categories)}, обрано: {len(selected)}):\n\n"
            "Оберіть категорії для фільтрації товарів.\n"
            "Якщо нічого не обрано — імпортуються всі товари.",
            parse_mode="HTML",
            reply_markup=_build_categories_kb(page_cats, selected, page, total_pages),
        )
    except Exception:
        await callback.message.edit_reply_markup(
            reply_markup=_build_categories_kb(page_cats, selected, page, total_pages),
        )
    await callback.answer()
