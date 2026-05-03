from typing import Any

from pydantic import BaseModel


class BoletaDesdeEncomiendaRequest(BaseModel):
    encomienda_id: int
    confirmar_pago: bool = True


class BoletaResponse(BaseModel):
    success: bool
    ambiente: str
    estado: str
    serie: str
    numero: str
    fecha_emision: str
    codigo_encomienda: str
    total: float
    subtotal: float
    igv: float
    moneda: str
    mensaje: str
    hash: str | None = None
    pdf_url: str | None = None
    xml_url: str | None = None
    cdr: str | None = None
    raw_response: dict[str, Any] | None = None


class BoletaMockRecord(BaseModel):
    serie: str
    numero: str
    codigo_encomienda: str
    encomienda: dict[str, Any]
    cotizacion: dict[str, Any]
    fecha_emision: str
    hash: str
    raw_response: dict[str, Any]
