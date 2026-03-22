from __future__ import annotations

from pydantic import BaseModel, Field


class RoAppCategory(BaseModel):
    id: str
    title: str = ""
    parent_id: str | None = None

    @property
    def name(self) -> str:
        return self.title


class RoAppProduct(BaseModel):
    id: str = ""
    sku: str = ""
    barcode: str = ""
    name: str = ""
    price: float = 0.0
    stock: int = 0
    description: str = ""
    short_description: str = ""
    images: list[str] = Field(default_factory=list)
    category_id: str = ""
    category_name: str = ""
    weight: str = ""
    length: str = ""
    width: str = ""
    height: str = ""
    warranty: str = ""
    custom_attributes: dict[str, str] = Field(default_factory=dict)

    @property
    def has_images(self) -> bool:
        return len(self.images) > 0

    @property
    def main_image(self) -> str | None:
        return self.images[0] if self.images else None

    @property
    def gallery_images(self) -> list[str]:
        return self.images[1:] if len(self.images) > 1 else []


class RoAppWarehouse(BaseModel):
    id: str
    name: str = ""
