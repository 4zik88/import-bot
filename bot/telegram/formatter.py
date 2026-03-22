from __future__ import annotations

import aiohttp
from aiogram.types import BufferedInputFile, InputMediaPhoto

from bot.roapp.models import RoAppProduct

MAX_CAPTION = 1024

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


def _get_cf(product: RoAppProduct, internal_key: str) -> str:
    """Get custom field value by internal key name."""
    for fid, key in FIELD_MAP.items():
        if key == internal_key:
            val = product.custom_attributes.get(fid, "")
            if not val:
                # Try by readable name too
                for k, v in product.custom_attributes.items():
                    if k.lower().strip() == internal_key:
                        return str(v)
            if isinstance(val, bool):
                return ""
            return str(val) if val else ""
    # Fallback: search by common names
    for k, v in product.custom_attributes.items():
        if k.lower().strip() == internal_key and v:
            return str(v)
    return ""


def _is_esim_only(product: RoAppProduct) -> bool:
    """Detect if the phone is USA/eSIM version (no physical SIM)."""
    name = product.name.lower()
    return any(kw in name for kw in ["esim", "usa", "e-sim", "єсім", "есім", "фіз sim"])


def _is_sold(product: RoAppProduct) -> bool:
    return product.stock <= 0


def format_caption(product: RoAppProduct, old_price: float | None = None) -> str:
    lines: list[str] = []

    # Title
    lines.append(f"✅{_escape(product.name)}✅")
    lines.append("")

    # eSIM / USA version
    if _is_esim_only(product):
        lines.append("🇺🇸 Версія USA (тільки eSIM)")
        lines.append("🔓 Neverlock — працює з будь-якою eSIM")
        lines.append("")

    # Condition
    condition = _get_cf(product, "condition")
    screen_cond = _get_cf(product, "screen_condition")
    body_cond = _get_cf(product, "body_condition")

    if condition or screen_cond or body_cond:
        if condition:
            lines.append(f"💯 Стан: {condition}")
        if screen_cond:
            lines.append(f" • Екран — {screen_cond}")
        if body_cond:
            lines.append(f" • Корпус — {body_cond}")
        lines.append("")

    # Screen specs
    screen = _get_cf(product, "screen")
    if screen:
        lines.append(f"🖥 Екран: {screen}")
        lines.append("")

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

    # NFC and features
    nfc_val = product.custom_attributes.get("f6953535")
    features: list[str] = []
    if nfc_val and nfc_val is not False and str(nfc_val).lower() not in ("false", "0", ""):
        features.append("NFC")
    # Try to detect Face ID / True Tone from name
    name_lower = product.name.lower()
    if "iphone" in name_lower:
        # iPhone X and later have Face ID
        features = ["Face ID", "True Tone"] + features
    if features:
        lines.append(f"⚙️ {' • '.join(features)}")
        lines.append("")

    # Battery
    battery = _get_cf(product, "battery")
    if battery:
        lines.append(f"🔋 Батарея: {battery}")
        lines.append("")

    # Complect
    complect = _get_cf(product, "complect")
    if complect:
        lines.append(f"📦 Комплект: {complect}")
        lines.append("")

    # Price
    if old_price and abs(old_price - product.price) > 0.01 and product.price > 0:
        lines.append(f"💸 Ціна: <s>{_format_price(old_price)} грн</s> → {_format_price(product.price)} грн")
    elif product.price > 0:
        lines.append(f"💸 Ціна: {_format_price(product.price)} грн")
    lines.append("")

    # Warranty
    warranty = product.warranty
    if warranty and warranty not in ("0", ""):
        lines.append(f"🛡 Гарантія: {warranty} міс.")

    # Exchange
    lines.append("♻️ Обмін з вашою доплатою")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("📍 SOTIK — смартфони та ремонт")

    caption = "\n".join(lines)
    if len(caption) > MAX_CAPTION:
        caption = _truncate(caption)
    return caption


def _truncate(text: str) -> str:
    if len(text) <= MAX_CAPTION:
        return text
    # Keep footer, truncate middle
    footer = "\n━━━━━━━━━━━━━━━\n📍 SOTIK — смартфони та ремонт"
    available = MAX_CAPTION - len(footer) - 3
    return text[:available].rsplit("\n", 1)[0] + "..." + footer


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
