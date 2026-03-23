from __future__ import annotations

import logging

from aiogram import Bot

from bot import db
from bot.roapp.client import RoAppClient
from bot.roapp.models import RoAppProduct
from bot.telegram.formatter import (
    CAT_LAPTOPS, CAT_SMARTPHONES, CAT_TABLETS,
    build_media_group, format_caption, set_category_tree,
)
from bot.telegram.publisher import delete_message, edit_caption, edit_text, publish_media_group, publish_text

logger = logging.getLogger(__name__)

# Root category IDs
CATEGORY_ROOTS = {
    CAT_SMARTPHONES: "Смартфони",
    CAT_TABLETS: "Планшети",
    CAT_LAPTOPS: "Ноутбуки",
}

# Cached category trees: {root_id: set of all child IDs}
_category_trees: dict[str, set[str]] = {}


async def _load_category_trees(client: RoAppClient) -> dict[str, set[str]]:
    """Load category trees for all supported root categories."""
    global _category_trees
    if _category_trees:
        return _category_trees

    cats = await client.get_categories()
    all_cats = {str(c.id): str(c.parent_id) if c.parent_id else None for c in cats}

    for root_id in CATEGORY_ROOTS:
        result = {root_id}
        queue = [root_id]
        while queue:
            pid = queue.pop()
            for cid, parent in all_cats.items():
                if parent == pid and cid not in result:
                    result.add(cid)
                    queue.append(cid)
        _category_trees[root_id] = result
        set_category_tree(root_id, result)

    return _category_trees


def _get_all_allowed_ids() -> set[str]:
    """Get all category IDs across all supported trees."""
    result: set[str] = set()
    for ids in _category_trees.values():
        result |= ids
    return result


# Keep backward compatibility
async def _load_smartphone_categories(client: RoAppClient) -> set[str]:
    trees = await _load_category_trees(client)
    return trees.get(CAT_SMARTPHONES, set())


class ImportResult:
    def __init__(self) -> None:
        self.found = 0
        self.posted = 0
        self.skipped = 0
        self.updated = 0
        self.removed = 0
        self.errors = 0

    @property
    def summary(self) -> str:
        lines = [
            f"Знайдено: {self.found}",
            f"Опубліковано: {self.posted}",
            f"Оновлено: {self.updated}",
            f"Видалено (продано): {self.removed}",
            f"Пропущено: {self.skipped}",
            f"Помилок: {self.errors}",
        ]
        return "\n".join(lines)


async def run_import(
    bot: Bot,
    trigger_type: str = "manual",
    progress_callback=None,
) -> ImportResult:
    result = ImportResult()
    log_id = await db.create_import_log(trigger_type)

    api_token = await db.get_setting("roapp_api_token")
    channel_id = await db.get_setting("channel_id")

    if not api_token or not channel_id:
        await db.finish_import_log(log_id, 0, 0, 0, 0, "error")
        raise ValueError("API-токен або канал не налаштовані. /setup")

    client = RoAppClient(api_token)
    try:
        # Load all category trees (smartphones, tablets, laptops)
        await _load_category_trees(client)
        allowed_ids = _get_all_allowed_ids()

        # Load from warehouse endpoint (has stock + images)
        warehouse_id = await db.get_setting("warehouse_id")
        if warehouse_id:
            from bot.roapp.client import normalize_product
            raw = await client._get_all_pages(f"/warehouse/goods/{warehouse_id}")
            products = [normalize_product(item) for item in raw]
        else:
            products = await client.get_products()

        # Filter: only smartphones, tablets, laptops
        products = [p for p in products if p.category_id in allowed_ids]
        result.found = len(products)

        # Build SKU map
        current_skus: dict[str, RoAppProduct] = {}
        for p in products:
            if p.sku:
                current_skus[p.sku] = p

        # Check previously posted products — remove sold ones, update prices
        posted = await db.get_all_posted_products()
        for pp in posted:
            sku = pp.get("sku", "")
            msg_id = pp.get("message_id")
            ch_id = pp.get("channel_id")
            if not sku or not msg_id or not ch_id:
                continue

            prod = current_skus.get(sku)
            if not prod or prod.stock <= 0:
                deleted = await delete_message(bot, ch_id, msg_id)
                if deleted:
                    await db.delete_posted_product(sku)
                    result.removed += 1
                continue

            old_price = pp.get("price") or 0
            if abs(old_price - prod.price) > 0.01:
                updated = await _update_post(bot, ch_id, msg_id, prod, old_price=old_price)
                if updated:
                    await db.update_posted_product(
                        sku, price=prod.price, stock=prod.stock, is_sold=False,
                    )
                    result.updated += 1

        # Publish new products (in stock only)
        for i, product in enumerate(products):
            if not product.sku or product.stock <= 0:
                continue
            try:
                if await db.is_product_posted(product.sku):
                    result.skipped += 1
                    continue

                media = await build_media_group(product)
                if media:
                    messages = await publish_media_group(bot, channel_id, media)
                    msg_id = str(messages[0].message_id) if messages else None
                else:
                    caption = format_caption(product)
                    msg = await publish_text(bot, channel_id, caption)
                    msg_id = str(msg.message_id) if msg else None

                if msg_id:
                    await db.add_posted_product(
                        sku=product.sku, roapp_id=product.id,
                        name=product.name, price=product.price,
                        message_id=msg_id, channel_id=channel_id,
                        stock=product.stock,
                    )
                    result.posted += 1
                else:
                    result.errors += 1

                if progress_callback and (i + 1) % 5 == 0:
                    await progress_callback(result, i + 1, len(products))

            except Exception as e:
                logger.error("Error importing product %s: %s", product.sku, e)
                result.errors += 1

    finally:
        await client.close()

    status = "completed" if result.errors == 0 else "completed_with_errors"
    await db.finish_import_log(
        log_id, result.found, result.posted, result.skipped, result.errors, status,
    )
    return result


async def _update_post(
    bot: Bot, channel_id: str, message_id: str, product: RoAppProduct,
    old_price: float | None = None,
) -> bool:
    caption = format_caption(product, old_price=old_price)
    if await edit_caption(bot, channel_id, message_id, caption):
        return True
    if await edit_text(bot, channel_id, message_id, caption):
        return True
    logger.warning("Could not update message %s", message_id)
    return False
