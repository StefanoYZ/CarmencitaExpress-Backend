from typing import Any

from pydantic import BaseModel


class CotizacionRequest(BaseModel):
    encomienda_id: int


class CotizacionResponse(BaseModel):
    encomienda_id: int
    codigo_encomienda: str
    subtotal: float
    igv: float
    total: float
    moneda: str = "PEN"
    detalle: dict[str, Any]
