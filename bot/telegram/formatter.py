from __future__ import annotations

import asyncio

import aiohttp
from aiogram.types import BufferedInputFile, InputMediaPhoto

from bot.roapp.models import RoAppProduct
from bot.telegram.templates import (
    KIND_FOOTER, KIND_LAPTOP, KIND_SMARTPHONE, KIND_TABLET,
    close_open_tags, get_template, render,
)

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

MAX_CAMERA_LEN = 120


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


def format_sold_caption(name: str) -> str:
    """Caption for posts whose product was sold but can't be deleted (>48h)."""
    lines = [
        "❌ <b>ПРОДАНО</b>",
        "",
        f"<s>{_escape(name)}</s>",
        "",
        get_template(KIND_FOOTER),
    ]
    return "\n".join(lines)


_KIND_BY_CATEGORY = {
    CAT_SMARTPHONES: KIND_SMARTPHONE,
    CAT_TABLETS: KIND_TABLET,
    CAT_LAPTOPS: KIND_LAPTOP,
}


def detect_kind(product: RoAppProduct) -> str:
    return _KIND_BY_CATEGORY.get(_detect_product_type(product), KIND_SMARTPHONE)


def format_caption(product: RoAppProduct, old_price: float | None = None) -> str:
    return render_caption(detect_kind(product), product, old_price)


def render_caption(
    kind: str, product: RoAppProduct, old_price: float | None = None,
    template: str | None = None, footer: str | None = None,
) -> str:
    """Render a post caption; ``template``/``footer`` override the saved ones (for previews)."""
    body = render(
        template if template is not None else get_template(kind),
        _template_values(product, old_price),
        _template_flags(product),
    )
    return _finalize(body, footer if footer is not None else get_template(KIND_FOOTER))


def _template_values(product: RoAppProduct, old_price: float | None) -> dict[str, str]:
    camera = _get_cf(product, "camera")
    values = {
        "name": product.name,
        "screen": _get_cf(product, "screen"),
        "processor": _get_cf(product, "processor"),
        "camera": _trim(camera, MAX_CAMERA_LEN) if camera else "",
        "battery": _get_cf(product, "battery"),
        "complect": _get_cf(product, "complect"),
        "screen_condition": _get_cf(product, "screen_condition"),
        "body_condition": _get_cf(product, "body_condition"),
        "os": _detect_os(product),
    }
    values = {k: _escape(v) for k, v in values.items()}
    values["price"] = _price_value(product, old_price)
    return values


def _template_flags(product: RoAppProduct) -> dict[str, bool]:
    apple = _is_apple(product)
    usa = _is_usa(product)
    lte = _has_lte(product)
    return {
        "Apple": apple,
        "Android": not apple,
        "США": apple and usa,
        "Європа": apple and not usa,
        "LTE": lte,
        "WiFi": not lte,
        "Стан": bool(_get_cf(product, "screen_condition") or _get_cf(product, "body_condition")),
        "Нова АКБ": _battery_replaced(product),
    }


# --- Helpers ---

def _price_value(product: RoAppProduct, old_price: float | None) -> str:
    if old_price and abs(old_price - product.price) > 0.01 and product.price > 0:
        return f"<s>{_format_price(old_price)} грн</s> → {_format_price(product.price)} грн"
    elif product.price > 0:
        return f"{_format_price(product.price)} грн"
    return ""


def _trim(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def _finalize(body: str, footer: str) -> str:
    caption = f"{body}\n{footer}" if body else footer
    if len(caption) <= MAX_CAPTION:
        return caption
    # Too long: cut the body at a line break and keep the footer intact.
    tail = "\n" + footer
    available = MAX_CAPTION - len(tail) - 3
    cut = body[:max(available, 0)].rsplit("\n", 1)[0]
    return close_open_tags(cut) + "..." + tail


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_price(price: float) -> str:
    if price == int(price):
        return f"{int(price):,}".replace(",", " ")
    return f"{price:,.2f}".replace(",", " ")


async def _download_with_session(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass
    return None


async def download_image(url: str) -> bytes | None:
    async with aiohttp.ClientSession() as session:
        return await _download_with_session(session, url)


async def build_media_group(product: RoAppProduct, old_price: float | None = None) -> list[InputMediaPhoto] | None:
    if not product.images:
        return None

    caption = format_caption(product, old_price=old_price)

    # Download all photos concurrently over one shared session — the order of
    # results (and thus of photos in the post) still matches product.images.
    urls = product.images[:10]
    async with aiohttp.ClientSession() as session:
        downloads = await asyncio.gather(
            *(_download_with_session(session, url) for url in urls)
        )

    media: list[InputMediaPhoto] = []
    for i, data in enumerate(downloads):
        if data is None:
            continue
        filename = f"{product.sku or product.id}_{i}.jpg"
        file = BufferedInputFile(data, filename=filename)
        # Caption goes on the first photo that actually downloaded.
        first = not media
        media.append(InputMediaPhoto(
            media=file,
            caption=caption if first else None,
            parse_mode="HTML" if first else None,
        ))

    return media if media else None
