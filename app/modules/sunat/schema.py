from typing import Any

from pydantic import BaseModel, Field


class ReceiptFromShipmentRequest(BaseModel):
    shipment_id: int = Field(alias="encomienda_id")
    confirm_payment: bool = Field(default=True, alias="confirmar_pago")


class ReceiptResponse(BaseModel):
    success: bool
    environment: str = Field(alias="ambiente")
    status: str = Field(alias="estado")
    series: str = Field(alias="serie")
    number: str = Field(alias="numero")
    issue_date: str = Field(alias="fecha_emision")
    shipment_code: str = Field(alias="codigo_encomienda")
    total: float
    subtotal: float
    igv: float
    currency: str = Field(alias="moneda")
    message: str = Field(alias="mensaje")
    hash: str | None = None
    pdf_url: str | None = None
    xml_url: str | None = None
    cdr: str | None = None
    cdr_code: str | None = None
    cdr_description: str | None = None
    cdr_notes: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] | None = None


class MockReceiptRecord(BaseModel):
    series: str = Field(alias="serie")
    number: str = Field(alias="numero")
    shipment_code: str = Field(alias="codigo_encomienda")
    shipment: dict[str, Any] = Field(alias="encomienda")
    quote: dict[str, Any] = Field(alias="cotizacion")
    issue_date: str = Field(alias="fecha_emision")
    hash: str
    raw_response: dict[str, Any]
