from typing import Any

from pydantic import BaseModel, Field


class QuoteRequest(BaseModel):
    shipment_id: int = Field(alias="encomienda_id")


class QuoteResponse(BaseModel):
    shipment_id: int = Field(alias="encomienda_id")
    shipment_code: str = Field(alias="codigo_encomienda")
    subtotal: float
    igv: float
    total: float
    currency: str = Field(default="PEN", alias="moneda")
    detail: dict[str, Any] = Field(alias="detalle")
