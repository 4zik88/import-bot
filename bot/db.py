from __future__ import annotations

import aiosqlite

from bot.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posted_products (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sku        TEXT NOT NULL UNIQUE,
    roapp_id   TEXT NOT NULL,
    name       TEXT NOT NULL,
    price      REAL,
    stock      INTEGER DEFAULT 0,
    message_id TEXT,
    channel_id TEXT,
    is_sold    INTEGER DEFAULT 0,
    posted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS selected_categories (
    category_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    parent_id   TEXT
);

CREATE TABLE IF NOT EXISTS import_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at      TIMESTAMP,
    trigger_type     TEXT NOT NULL CHECK(trigger_type IN ('manual', 'auto')),
    products_found   INTEGER DEFAULT 0,
    products_posted  INTEGER DEFAULT 0,
    products_skipped INTEGER DEFAULT 0,
    errors           INTEGER DEFAULT 0,
    status           TEXT DEFAULT 'running'
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(settings.db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(_SCHEMA)
        # Migrations: add columns if missing
        try:
            await db.execute("ALTER TABLE posted_products ADD COLUMN stock INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE posted_products ADD COLUMN is_sold INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE posted_products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        await db.commit()
    finally:
        await db.close()

    # Seed settings from env vars if DB is empty
    from bot.config import settings as cfg
    for db_key, attr in [("roapp_api_token", "roapp_api_token"), ("channel_id", "channel_id"), ("warehouse_id", "warehouse_id")]:
        val = getattr(cfg, attr, "")
        if val:
            existing = await get_setting(db_key)
            if not existing:
                await set_setting(db_key, val)


# --- settings CRUD ---

_ENV_FALLBACKS = {
    "roapp_api_token": "roapp_api_token",
    "channel_id": "channel_id",
    "warehouse_id": "warehouse_id",
}


async def get_setting(key: str) -> str | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        if row:
            return row["value"]
    finally:
        await db.close()
    # Fallback to env vars for persistent settings
    if key in _ENV_FALLBACKS:
        from bot.config import settings as cfg
        val = getattr(cfg, _ENV_FALLBACKS[key], "")
        return val if val else None
    return None


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_setting(key: str) -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await db.commit()
    finally:
        await db.close()


# --- posted_products ---

async def is_product_posted(sku: str) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("SELECT 1 FROM posted_products WHERE sku = ?", (sku,))
        return await cur.fetchone() is not None
    finally:
        await db.close()


async def add_posted_product(
    sku: str, roapp_id: str, name: str, price: float | None,
    message_id: str | None, channel_id: str | None,
    stock: int = 0,
) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO posted_products (sku, roapp_id, name, price, stock, message_id, channel_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sku, roapp_id, name, price, stock, message_id, channel_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_posted_product(sku: str) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM posted_products WHERE sku = ?", (sku,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_posted_product(sku: str, price: float | None = None, stock: int | None = None,
                                 is_sold: bool | None = None, message_id: str | None = None) -> None:
    db = await get_db()
    try:
        updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: list = []
        if price is not None:
            updates.append("price = ?")
            params.append(price)
        if stock is not None:
            updates.append("stock = ?")
            params.append(stock)
        if is_sold is not None:
            updates.append("is_sold = ?")
            params.append(1 if is_sold else 0)
        if message_id is not None:
            updates.append("message_id = ?")
            params.append(message_id)
        params.append(sku)
        await db.execute(f"UPDATE posted_products SET {', '.join(updates)} WHERE sku = ?", params)
        await db.commit()
    finally:
        await db.close()


async def delete_posted_product(sku: str) -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM posted_products WHERE sku = ?", (sku,))
        await db.commit()
    finally:
        await db.close()


async def get_all_posted_products() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM posted_products")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_posted_products_count() -> int:
    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) as cnt FROM posted_products")
        row = await cur.fetchone()
        return row["cnt"]
    finally:
        await db.close()


async def clear_posted_products() -> int:
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM posted_products")
        await db.commit()
        return cur.rowcount
    finally:
        await db.close()


# --- selected_categories ---

async def get_selected_categories() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT category_id, name, parent_id FROM selected_categories")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_selected_category_ids() -> set[str]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT category_id FROM selected_categories")
        rows = await cur.fetchall()
        return {r["category_id"] for r in rows}
    finally:
        await db.close()


async def toggle_category(category_id: str, name: str, parent_id: str | None) -> bool:
    """Toggle category selection. Returns True if added, False if removed."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT 1 FROM selected_categories WHERE category_id = ?", (category_id,))
        exists = await cur.fetchone()
        if exists:
            await db.execute("DELETE FROM selected_categories WHERE category_id = ?", (category_id,))
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO selected_categories (category_id, name, parent_id) VALUES (?, ?, ?)",
                (category_id, name, parent_id),
            )
            await db.commit()
            return True
    finally:
        await db.close()


async def clear_selected_categories() -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM selected_categories")
        await db.commit()
    finally:
        await db.close()


async def add_categories_bulk(categories: list[dict]) -> None:
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO selected_categories (category_id, name, parent_id) VALUES (?, ?, ?)",
            [(c["category_id"], c["name"], c.get("parent_id")) for c in categories],
        )
        await db.commit()
    finally:
        await db.close()


# --- import_log ---

async def create_import_log(trigger_type: str) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO import_log (trigger_type) VALUES (?)", (trigger_type,)
        )
        await db.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        await db.close()


async def finish_import_log(
    log_id: int, products_found: int, products_posted: int,
    products_skipped: int, errors: int, status: str,
) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE import_log SET finished_at = CURRENT_TIMESTAMP, "
            "products_found = ?, products_posted = ?, products_skipped = ?, "
            "errors = ?, status = ? WHERE id = ?",
            (products_found, products_posted, products_skipped, errors, status, log_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_import_history(limit: int = 10) -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM import_log ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
