from __future__ import annotations

import aiohttp
from aiogram.types import BufferedInputFile, InputMediaPhoto

from bot.roapp.models import RoAppProduct

MAX_CAPTION = 1024

# Category root IDs
CAT_SMARTPHONES = "718966"
CAT_TABLETS = "933502"
CAT_LAPTOPS = "933503"

# RoApp custom field IDs -> internal keys
FIELD_MAP = {
    "f6601600": "processor",
    "f6601601": "camera",
    "f6601602": "screen",
    "f6601603": "battery",
    "f6601660": "manufactured",
    "f6617797": "condition",
    "f6617798": "complect",
    "f6953535": "nfc",
    "f10328326": "screen_condition",
    "f10328327": "body_condition",
}

# All category IDs loaded at runtime (filled by importer)
_all_cat_ids: dict[str, set[str]] = {}

TELEGRAM_CONTACT = "https://t.me/sotik_ua"

FOOTER = (
    "━━━━━━━━━━━━━━━\n"
    "🔧 Ремонт телефонів, планшетів, ноутбуків\n"
    "📱 Продаж нової та б/у техніки\n"
    "♻️ Обмін • Викуп\n"
    '🌐 <a href="https://sotik.in.ua">SOTIK.in.ua</a> - Ціни нижче ніж задарма!\n'
    "📍 м. Козятин, Героїв Майдану 20\n"
    f'📞 097 985 09 92 (<a href="{TELEGRAM_CONTACT}">Напиши в Telegram</a>)'
)


def set_category_tree(cat_root: str, ids: set[str]) -> None:
    _all_cat_ids[cat_root] = ids


def _get_cf(product: RoAppProduct, internal_key: str) -> str:
    for fid, key in FIELD_MAP.items():
        if key == internal_key:
            val = product.custom_attributes.get(fid, "")
            if not val:
                for k, v in product.custom_attributes.items():
                    if k.lower().strip() == internal_key:
                        return str(v)
            if isinstance(val, bool):
                return ""
            return str(val) if val else ""
    for k, v in product.custom_attributes.items():
        if k.lower().strip() == internal_key and v:
            return str(v)
    return ""


def _detect_product_type(product: RoAppProduct) -> str:
    """Detect product type by category tree."""
    cid = product.category_id
    for root, ids in _all_cat_ids.items():
        if cid in ids:
            return root
    # Fallback: detect by name
    name = product.name.lower()
    if any(kw in name for kw in ["ipad", "планшет", "tablet", "tab "]):
        return CAT_TABLETS
    if any(kw in name for kw in ["ноутбук", "notebook", "laptop", "macbook", "book"]):
        return CAT_LAPTOPS
    return CAT_SMARTPHONES


def _is_usa(product: RoAppProduct) -> bool:
    name = product.name.lower()
    return any(kw in name for kw in ["esim", "usa", "e-sim", "єсім", "есім", "сша"])


def _is_apple(product: RoAppProduct) -> bool:
    name = product.name.lower()
    return any(kw in name for kw in ["apple", "iphone", "ipad", "macbook"])


def _has_lte(product: RoAppProduct) -> bool:
    name = product.name.lower()
    return any(kw in name for kw in ["lte", "cellular", "4g", "5g", "sim"])


def _detect_os(product: RoAppProduct) -> str:
    name = product.name.lower()
    if any(kw in name for kw in ["macbook", "apple"]):
        return "Mac OS"
    return "Windows"


def _battery_replaced(product: RoAppProduct) -> bool:
    battery = _get_cf(product, "battery")
    return any(kw in battery.lower() for kw in ["замін", "нова", "замен", "replace"]) if battery else False


def format_caption(product: RoAppProduct, old_price: float | None = None) -> str:
    ptype = _detect_product_type(product)
    if ptype == CAT_LAPTOPS:
        return _format_laptop(product, old_price)
    elif ptype == CAT_TABLETS:
        return _format_tablet(product, old_price)
    else:
        return _format_smartphone(product, old_price)


def _format_smartphone(product: RoAppProduct, old_price: float | None = None) -> str:
    lines: list[str] = []

    # Title
    lines.append(f"✅ {_escape(product.name)} ✅")
    lines.append("")

    # Price
    lines.append(_price_line(product, old_price))
    lines.append("")

    # Version & SIM — only for Apple
    if _is_apple(product):
        if _is_usa(product):
            lines.append("🌍 Версія: США")
            lines.append("📶 SIM: тільки eSIM (без фізичної SIM)")
        else:
            lines.append("🌍 Версія: Європа")
            lines.append("📶 SIM: 1 фізична SIM + eSIM")
        lines.append("🔓 Neverlock (працює з будь-яким оператором)")
        lines.append("🔒 iCloud: чистий")
    else:
        lines.append("🔒 Google акаунт: чистий")
    lines.append("")

    # Condition
    _add_condition(lines, product)

    # Screen
    screen = _get_cf(product, "screen")
    if screen:
        lines.append(f"🖥 Екран: {screen}")

    # Processor
    processor = _get_cf(product, "processor")
    if processor:
        lines.append(f"⚡ Процесор: {processor}")
    lines.append("")

    # Camera
    camera = _get_cf(product, "camera")
    if camera:
        lines.append("📸 Камера:")
        lines.append(f" • {camera}")
        lines.append("")

    # Battery
    battery = _get_cf(product, "battery")
    if battery:
        lines.append(f"🔋 АКБ: {battery}")
        lines.append("")

    # Checked
    checks = ["Face ID", "Камери", "Динаміки", "Мікрофони", "NFC"] if _is_apple(product) else ["Камери", "Динаміки", "Мікрофони", "NFC"]
    lines.append("✅ Повністю перевірений:")
    lines.append(" • ".join(checks))
    lines.append("")

    # Complect
    complect = _get_cf(product, "complect")
    if complect:
        lines.append(f"📦 Комплект: {complect}")

    # Warranty
    lines.append("🛡 Гарантія: 1 місяць на пристрій")
    if _battery_replaced(product):
        lines.append("                         6 місяців на АКБ")

    lines.append("━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(FOOTER)

    return _finalize(lines)


def _format_tablet(product: RoAppProduct, old_price: float | None = None) -> str:
    lines: list[str] = []

    lines.append(f"✅ {_escape(product.name)} ✅")
    lines.append("")

    lines.append(_price_line(product, old_price))
    lines.append("")

    # SIM / WiFi
    if _has_lte(product):
        lines.append("📶 SIM: LTE (SIM)")
    else:
        lines.append("📶 SIM: WiFi only")

    # iCloud / Google
    if _is_apple(product):
        lines.append("🔒 iCloud: чистий")
    else:
        lines.append("🔒 Google акаунт: чистий")
    lines.append("")

    # Condition
    _add_condition(lines, product)

    # Screen
    screen = _get_cf(product, "screen")
    if screen:
        lines.append(f"🖥 Екран: {screen}")

    # Processor
    processor = _get_cf(product, "processor")
    if processor:
        lines.append(f"⚡ Процесор: {processor}")
    lines.append("")

    # Camera
    camera = _get_cf(product, "camera")
    if camera:
        lines.append(f"📸 Камера: {camera}")
        lines.append("")

    # Battery
    battery = _get_cf(product, "battery")
    if battery:
        lines.append(f"🔋 АКБ: {battery}")
        lines.append("")

    # Checked
    lines.append("✅ Повністю перевірений:")
    lines.append("Екран • Сенсор • Камери • Динаміки • Wi-Fi")
    lines.append("")

    # Complect
    complect = _get_cf(product, "complect")
    if complect:
        lines.append(f"📦 Комплект: {complect}")

    lines.append("🛡 Гарантія: 1 місяць на пристрій")

    lines.append("━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(FOOTER)

    return _finalize(lines)


def _format_laptop(product: RoAppProduct, old_price: float | None = None) -> str:
    lines: list[str] = []

    lines.append(f"✅ {_escape(product.name)} ✅")
    lines.append("")

    lines.append(_price_line(product, old_price))
    lines.append("")

    # Condition
    _add_condition(lines, product)

    # Screen
    screen = _get_cf(product, "screen")
    if screen:
        lines.append(f"🖥 Екран: {screen}")

    # Processor
    processor = _get_cf(product, "processor")
    if processor:
        lines.append(f"⚡ Процесор: {processor}")
    lines.append("")

    # Battery
    battery = _get_cf(product, "battery")
    if battery:
        lines.append(f"🔋 АКБ: {battery}")
        lines.append("")

    # Checked
    lines.append("✅ Повністю перевірений:")
    lines.append("Клавіатура • Тачпад • Екран • Батарея • Порти • Wi-Fi")
    lines.append("")

    # OS
    lines.append(f"🌐 ОС: {_detect_os(product)}")
    lines.append("")

    # Complect
    complect = _get_cf(product, "complect")
    if complect:
        lines.append(f"📦 Комплект: {complect}")

    lines.append("🛡 Гарантія: 1 місяць на пристрій")

    lines.append("━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(FOOTER)

    return _finalize(lines)


# --- Helpers ---

def _price_line(product: RoAppProduct, old_price: float | None) -> str:
    if old_price and abs(old_price - product.price) > 0.01 and product.price > 0:
        return f"💸 Ціна: <s>{_format_price(old_price)} грн</s> → {_format_price(product.price)} грн"
    elif product.price > 0:
        return f"💸 Ціна: {_format_price(product.price)} грн"
    return ""


def _add_condition(lines: list[str], product: RoAppProduct) -> None:
    screen_cond = _get_cf(product, "screen_condition")
    body_cond = _get_cf(product, "body_condition")
    if screen_cond or body_cond:
        lines.append("💯 Стан:")
        if screen_cond:
            lines.append(f" • Екран — {screen_cond}")
        if body_cond:
            lines.append(f" • Корпус — {body_cond}")
        lines.append("")


def _finalize(lines: list[str]) -> str:
    caption = "\n".join(lines)
    if len(caption) > MAX_CAPTION:
        caption = _truncate(caption)
    return caption


def _truncate(text: str) -> str:
    if len(text) <= MAX_CAPTION:
        return text
    footer_line = "\n━━━━━━━━━━━━━━━\n" + FOOTER
    available = MAX_CAPTION - len(footer_line) - 3
    return text[:available].rsplit("\n", 1)[0] + "..." + footer_line


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_price(price: float) -> str:
    if price == int(price):
        return f"{int(price):,}".replace(",", " ")
    return f"{price:,.2f}".replace(",", " ")


async def download_image(url: str) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception:
        pass
    return None


async def build_media_group(product: RoAppProduct, old_price: float | None = None) -> list[InputMediaPhoto] | None:
    if not product.images:
        return None

    caption = format_caption(product, old_price=old_price)
    media: list[InputMediaPhoto] = []

    for i, url in enumerate(product.images[:10]):
        data = await download_image(url)
        if data is None:
            continue
        filename = f"{product.sku or product.id}_{i}.jpg"
        file = BufferedInputFile(data, filename=filename)
        media.append(InputMediaPhoto(
            media=file,
            caption=caption if i == 0 else None,
            parse_mode="HTML" if i == 0 else None,
        ))

    return media if media else None
