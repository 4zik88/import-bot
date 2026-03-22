from __future__ import annotations

import logging
from typing import Any

import aiohttp

from bot.roapp.models import RoAppCategory, RoAppProduct, RoAppWarehouse

logger = logging.getLogger(__name__)

BASE_URL = "https://api.roapp.io"
PER_PAGE = 50
MAX_PAGES = 200


def _get_value(item: dict, keys: list[str]) -> Any:
    """Get the first non-empty value from a dict trying multiple keys."""
    for key in keys:
        val = item.get(key)
        if val is not None and val != "" and val != 0:
            return val
    return None


def _extract_sku(item: dict) -> str:
    val = _get_value(item, ["article", "code"])
    if val:
        return str(val)
    barcodes = item.get("barcodes")
    if isinstance(barcodes, list) and barcodes:
        b = barcodes[0]
        return str(b.get("code", b)) if isinstance(b, dict) else str(b)
    barcode = item.get("barcode")
    return str(barcode) if barcode else ""


def _extract_barcode(item: dict) -> str:
    barcodes = item.get("barcodes")
    if isinstance(barcodes, list) and barcodes:
        b = barcodes[0]
        return str(b.get("code", b)) if isinstance(b, dict) else str(b)
    barcode = item.get("barcode")
    return str(barcode) if barcode else ""


def _extract_price(item: dict) -> float:
    prices = item.get("prices")
    if isinstance(prices, dict):
        for v in prices.values():
            try:
                fv = float(v)
                if fv > 0:
                    return fv
            except (ValueError, TypeError):
                continue
    elif isinstance(prices, list):
        for p in prices:
            val = p.get("value", p) if isinstance(p, dict) else p
            try:
                fv = float(val)
                if fv > 0:
                    return fv
            except (ValueError, TypeError):
                continue
    price = item.get("price")
    if isinstance(price, dict):
        # Multiple price types — take the highest (retail price)
        best = 0.0
        for v in price.values():
            try:
                fv = float(v)
                if fv > best:
                    best = fv
            except (ValueError, TypeError):
                continue
        if best > 0:
            return best
    elif price is not None:
        try:
            return float(price)
        except (ValueError, TypeError):
            pass
    return 0.0


def _extract_images(item: dict) -> list[str]:
    urls: list[str] = []
    images = item.get("images")
    if isinstance(images, list):
        for img in images:
            if isinstance(img, str):
                if img:
                    urls.append(img)
            elif isinstance(img, dict):
                for key in ("image", "url", "src", "path", "link"):
                    val = img.get(key)
                    if val and isinstance(val, str):
                        urls.append(val)
                        break
    if not urls:
        for key in ("image", "photo"):
            val = item.get(key)
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, str) and v:
                        urls.append(v)
                if urls:
                    break
            elif val and isinstance(val, str):
                urls.append(val)
                break
    return urls


def _extract_name(item: dict) -> str:
    val = _get_value(item, ["title", "name", "product_name", "наименование", "название"])
    return str(val) if val else ""


def _extract_stock(item: dict) -> int:
    val = _get_value(item, ["residue", "stock", "quantity", "qty", "stock_quantity", "available", "остаток", "остатки"])
    if val is not None:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            pass
    return 0


def _extract_category(item: dict) -> tuple[str, str]:
    cat = item.get("category")
    if isinstance(cat, dict):
        return str(cat.get("id", "")), str(cat.get("title", ""))
    if isinstance(cat, str):
        return "", cat
    return "", ""


_EXCLUDED_FIELDS = {
    "code", "id", "product_id", "article", "art", "sku", "article_number", "product_code",
    "barcode", "barcode_number", "ean", "upc", "barcodes",
    "name", "title", "product_name", "наименование", "название",
    "stock", "quantity", "qty", "stock_quantity", "available", "остаток", "остатки", "residue",
    "price", "cost", "amount", "цена", "prices",
    "description", "desc", "content", "описание", "short_description", "short_desc", "excerpt",
    "category", "category_name", "cat", "product_category", "категория", "categories",
    "image", "image_url", "picture", "photo", "img", "изображение", "images",
    "weight", "mass", "вес", "length", "длина", "width", "ширина", "height", "высота",
    "is_serial", "is_enable_expiration_tracking", "is_expiration_tracking_enabled",
    "is_expiring_soon_alert_enabled", "is_critical_alert_enabled", "default_supplier_id",
    "uom", "warranty", "warranty_period", "custom_fields", "is_dimensions_weight_enabled",
}


def _extract_custom_attributes(item: dict, custom_fields_map: dict[str, str] | None = None) -> dict[str, str]:
    attrs: dict[str, str] = {}
    custom_fields = item.get("custom_fields")
    if isinstance(custom_fields, list):
        for cf in custom_fields:
            if isinstance(cf, dict):
                fid = str(cf.get("id", cf.get("field_id", "")))
                val = cf.get("value", "")
                if isinstance(val, bool) or val is False:
                    continue
                if val and fid:
                    attrs[fid] = str(val)
    elif isinstance(custom_fields, dict):
        for fid, val in custom_fields.items():
            if isinstance(val, bool) or val is False:
                continue
            if val and fid:
                attrs[fid] = str(val)
    return attrs


def normalize_product(item: dict, custom_fields_map: dict[str, str] | None = None) -> RoAppProduct:
    cat_id, cat_name = _extract_category(item)
    return RoAppProduct(
        id=str(item.get("id", "")),
        sku=_extract_sku(item),
        barcode=_extract_barcode(item),
        name=_extract_name(item),
        price=_extract_price(item),
        stock=_extract_stock(item),
        description=str(_get_value(item, ["description", "desc", "content", "описание"]) or ""),
        short_description=str(_get_value(item, ["short_description", "short_desc", "excerpt"]) or ""),
        images=_extract_images(item),
        category_id=cat_id,
        category_name=cat_name,
        weight=str(_get_value(item, ["weight", "mass", "вес"]) or ""),
        length=str(_get_value(item, ["length", "длина"]) or ""),
        width=str(_get_value(item, ["width", "ширина"]) or ""),
        height=str(_get_value(item, ["height", "высота"]) or ""),
        warranty=str(item.get("warranty", "")),
        custom_attributes=_extract_custom_attributes(item, custom_fields_map),
    )


class RoAppClient:
    def __init__(self, api_token: str, base_url: str = BASE_URL):
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Accept": "application/json",
                    "User-Agent": "TG-Channel-Import/1.0",
                },
                timeout=aiohttp.ClientTimeout(total=60),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, endpoint: str, params: dict | None = None) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        async with session.get(url, params=params) as resp:
            if resp.status == 401:
                raise ValueError("Неверный API-токен RoApp")
            if resp.status == 403:
                raise PermissionError("Доступ запрещен")
            resp.raise_for_status()
            return await resp.json()

    async def _get_all_pages(self, endpoint: str) -> list[dict]:
        all_items: list[dict] = []
        seen_ids: set[str] = set()
        page = 1
        while page <= MAX_PAGES:
            data = await self._get(endpoint, params={"page": page})
            total_count = None
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                total_count = data.get("count")
                items = data.get("results", data.get("data", data.get("items", [])))
                if not isinstance(items, list):
                    items = [data]
            else:
                break

            # Deduplicate by id to handle APIs that return all items on every page
            new_items = 0
            for item in items:
                item_id = str(item.get("id", ""))
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                all_items.append(item)
                new_items += 1

            # Stop if: no new items, fewer than page size, or we have all items
            if new_items == 0:
                break
            if len(items) < PER_PAGE:
                break
            if total_count and len(all_items) >= total_count:
                break
            page += 1
        return all_items

    async def test_connection(self) -> bool:
        try:
            await self._get("/products/", params={"page": 1})
            return True
        except Exception:
            return False

    async def get_products(self) -> list[RoAppProduct]:
        raw = await self._get_all_pages("/products/")
        custom_map = await self._get_custom_fields_map()
        return [normalize_product(item, custom_map) for item in raw]

    async def get_products_page(self, page: int = 1) -> tuple[list[RoAppProduct], int]:
        """Fetch a single page of products. Returns (products, total_count)."""
        data = await self._get("/products/", params={"page": page})
        total = 0
        if isinstance(data, dict):
            total = data.get("count", 0)
            items = data.get("results", data.get("data", data.get("items", [])))
        elif isinstance(data, list):
            items = data
            total = len(data)
        else:
            items = []
        custom_map = await self._get_custom_fields_map()
        products = [normalize_product(item, custom_map) for item in items]
        return products, total

    async def get_categories(self) -> list[RoAppCategory]:
        raw = await self._get_all_pages("/warehouse/categories/")
        result: list[RoAppCategory] = []
        for item in raw:
            try:
                result.append(RoAppCategory(
                    id=str(item.get("id", "")),
                    title=str(item.get("title", item.get("name", ""))),
                    parent_id=str(item["parent_id"]) if item.get("parent_id") else None,
                ))
            except Exception as e:
                logger.warning("Ошибка парсинга категории: %s — %s", item, e)
        return result

    async def get_warehouses(self) -> list[RoAppWarehouse]:
        data = await self._get("/warehouse/")
        items = data if isinstance(data, list) else data.get("results", data.get("data", []))
        return [
            RoAppWarehouse(id=str(w.get("id", "")), name=str(w.get("name", "")))
            for w in items
        ]

    async def get_warehouse_stock(self, warehouse_id: str) -> dict[str, int]:
        """Returns {article/code: stock_quantity}."""
        raw = await self._get_all_pages(f"/warehouse/goods/{warehouse_id}")
        stock: dict[str, int] = {}
        for item in raw:
            sku = _extract_sku(item)
            qty = _extract_stock(item)
            if sku:
                stock[sku] = qty
        return stock

    async def enrich_products_with_stock(self, products: list[RoAppProduct], warehouse_id: str) -> None:
        stock = await self.get_warehouse_stock(warehouse_id)
        for p in products:
            if p.sku in stock:
                p.stock = stock[p.sku]

    async def _get_custom_fields_map(self) -> dict[str, str]:
        try:
            raw = await self._get_all_pages("/products/custom-fields/")
            return {str(f.get("id", "")): str(f.get("title", f.get("name", ""))) for f in raw if f.get("id")}
        except Exception:
            return {}
