from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.quotes.schema import QuoteResponse
from app.modules.quotes.service import calculate_quote_for_shipment
from app.modules.shipments.service import get_shipment
from app.modules.sunat.client import LycetClient
from app.modules.sunat.exceptions import SunatEmissionBlockedError
from app.modules.sunat.schema import MockReceiptRecord, ReceiptResponse
from app.modules.shipments.model import Shipment


MOCK_RECEIPT_SERIES = "B001"
CANCELED_STATUS = "ANULADA"

# TODO: reemplazar este almacenamiento en memoria por repository + PostgreSQL.
_mock_receipts_store: dict[tuple[str, str], MockReceiptRecord] = {}
_next_mock_receipt_number = 1


def _next_receipt_number() -> str:
    global _next_mock_receipt_number

    number = f"{_next_mock_receipt_number:06d}"
    _next_mock_receipt_number += 1
    return number


def _sunat_document_type(document_type: str) -> str:
    normalized_type = document_type.strip().upper()
    if normalized_type == "DNI":
        return "1"
    if normalized_type == "RUC":
        return "6"
    return "0"


def build_receipt_payload(
    shipment: Shipment,
    quote: QuoteResponse,
    correlativo: str | None = None,
) -> dict[str, Any]:
    correlativo = correlativo or _next_receipt_number()
    description = (
        f"SERVICIO DE TRANSPORTE DE ENCOMIENDA - {shipment.origin} A {shipment.destination} "
        f"- CODIGO {shipment.shipment_code}"
    )

    return {
        "ublVersion": "2.1",
        "tipoOperacion": "0101",
        "tipoDoc": "03",
        "serie": MOCK_RECEIPT_SERIES,
        "correlativo": correlativo,
        "fechaEmision": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tipoMoneda": "PEN",
        "formaPago": {
            "moneda": "PEN",
            "tipo": "Contado",
            "monto": quote.total,
        },
        "client": {
            "tipoDoc": _sunat_document_type(shipment.sender_document_type),
            "numDoc": shipment.sender_document_number,
            "rznSocial": shipment.sender_name,
            "address": {
                "direccion": shipment.sender_address or "",
                "provincia": "",
                "departamento": "",
                "distrito": "",
                "ubigueo": "",
                "codigoPais": "PE",
            },
        },
        "company": {
            # TODO: configurar datos oficiales del emisor solo cuando se habilite emision real autorizada.
            "ruc": "20000000001",
            "razonSocial": "Empresa Demo - Modo Desarrollo",
            "nombreComercial": "Carmencita Express Cargo S.A.C. (modo desarrollo)",
            "address": {
                "direccion": "Direccion demo no fiscal",
                "provincia": "Trujillo",
                "departamento": "La Libertad",
                "distrito": "Trujillo",
                "ubigueo": "",
                "codigoPais": "PE",
            },
        },
        "mtoOperGravadas": quote.subtotal,
        "mtoIGV": quote.igv,
        "totalImpuestos": quote.igv,
        "valorVenta": quote.subtotal,
        "subTotal": quote.total,
        "mtoImpVenta": quote.total,
        "details": [
            {
                "unidad": "ZZ",
                "cantidad": 1,
                "codProducto": shipment.shipment_code,
                "codProdSunat": "78101802",
                "descripcion": description,
                "mtoValorUnitario": quote.subtotal,
                "descuento": 0,
                "igv": quote.igv,
                "tipAfeIgv": "10",
                "isc": 0,
                "totalImpuestos": quote.igv,
                "mtoPrecioUnitario": quote.total,
                "mtoValorVenta": quote.subtotal,
                "mtoValorGratuito": 0,
                "mtoBaseIgv": quote.subtotal,
                "porcentajeIgv": 18,
                "mtoBaseIsc": 0,
                "tipSisIsc": "",
                "porcentajeIsc": 0,
                "mtoBaseOth": 0,
                "porcentajeOth": 0,
                "otroTributo": 0,
                "icbper": 0,
                "factorIcbper": 0,
            }
        ],
        "legends": [
            {
                "code": "1000",
                # TODO: convertir correctamente el monto total a letras.
                "value": f"SON {quote.total:.2f} SOLES",
            }
        ],
        "metadata": {
            "codigo_encomienda": shipment.shipment_code,
            "destinatario": {
                "tipo_documento": shipment.recipient_document_type,
                "numero_documento": shipment.recipient_document_number,
                "nombre": shipment.recipient_name,
                "direccion": shipment.recipient_address,
                "telefono": shipment.recipient_phone,
            },
        },
    }


def issue_receipt_from_shipment(db: Session, shipment_id: int, confirm_payment: bool = True) -> ReceiptResponse:
    if settings.production_emission_blocked:
        raise SunatEmissionBlockedError("Real emission is blocked by configuration")

    if not confirm_payment:
        raise ValueError("Payment must be confirmed before issuing the receipt")

    shipment = get_shipment(db, shipment_id)
    if shipment is None:
        raise LookupError("Shipment not found")
    if shipment.status == CANCELED_STATUS:
        raise ValueError("No se puede emitir boleta para una encomienda anulada")

    quote = calculate_quote_for_shipment(shipment)
    number = _next_receipt_number()
    payload = build_receipt_payload(shipment, quote, number)

    if settings.sunat_env == "mock":
        return _issue_mock_receipt(shipment, quote, payload, number)

    if settings.sunat_env == "beta":
        result = LycetClient().emitir_boleta(payload)
        raw_response = result.get("raw_response", result)
        normalized = _normalize_lycet_response(raw_response)
        today = date.today().isoformat()
        return ReceiptResponse(
            success=result.get("success", False),
            ambiente="beta",
            estado=normalized["status"],
            serie=MOCK_RECEIPT_SERIES,
            numero=number,
            fecha_emision=today,
            codigo_encomienda=shipment.shipment_code,
            total=quote.total,
            subtotal=quote.subtotal,
            igv=quote.igv,
            moneda=quote.currency,
            mensaje=result.get("mensaje", "Receipt sent to Lycet beta."),
            hash=normalized["hash"],
            cdr=normalized["cdr"],
            cdr_code=normalized["cdr_code"],
            cdr_description=normalized["cdr_description"],
            cdr_notes=normalized["cdr_notes"],
            raw_response=raw_response,
        )

    raise SunatEmissionBlockedError("SUNAT_ENV=production is blocked for this stage")


def generate_beta_pdf_from_shipment(db: Session, shipment_id: int, confirm_payment: bool = True) -> tuple[str, bytes]:
    shipment, _quote, payload = _build_beta_payload_from_shipment(db, shipment_id, confirm_payment)
    pdf_bytes = LycetClient().generar_pdf(payload)
    filename = f"boleta_beta_{shipment.shipment_code}.pdf"
    return filename, pdf_bytes


def generate_beta_xml_from_shipment(db: Session, shipment_id: int, confirm_payment: bool = True) -> dict[str, Any]:
    shipment, _quote, payload = _build_beta_payload_from_shipment(db, shipment_id, confirm_payment)
    lycet_response = LycetClient().generar_xml(payload)

    if isinstance(lycet_response, str):
        return {
            "success": True,
            "ambiente": "beta",
            "codigo_encomienda": shipment.shipment_code,
            "xml": lycet_response,
        }

    return {
        "success": True,
        "ambiente": "beta",
        "codigo_encomienda": shipment.shipment_code,
        "raw_response": lycet_response,
    }


def _build_beta_payload_from_shipment(
    db: Session,
    shipment_id: int,
    confirm_payment: bool,
) -> tuple[Shipment, QuoteResponse, dict[str, Any]]:
    if settings.sunat_env != "beta":
        raise SunatEmissionBlockedError("This endpoint only works when SUNAT_ENV=beta")

    if not confirm_payment:
        raise ValueError("Payment must be confirmed before generating the beta document")

    shipment = get_shipment(db, shipment_id)
    if shipment is None:
        raise LookupError("Shipment not found")
    if shipment.status == CANCELED_STATUS:
        raise ValueError("No se puede emitir boleta para una encomienda anulada")

    quote = calculate_quote_for_shipment(shipment)
    payload = build_receipt_payload(shipment, quote)
    return shipment, quote, payload


def _issue_mock_receipt(
    shipment: Shipment,
    quote: QuoteResponse,
    payload: dict[str, Any],
    number: str,
) -> ReceiptResponse:
    issue_date = date.today().isoformat()
    mock_hash = f"MOCK-HASH-{MOCK_RECEIPT_SERIES}-{number}"
    raw_response = {
        "modo": "mock",
        "advertencia": "Este comprobante es simulado y no fue enviado a SUNAT.",
        "payload": payload,
    }

    record = MockReceiptRecord(
        serie=MOCK_RECEIPT_SERIES,
        numero=number,
        codigo_encomienda=shipment.shipment_code,
        encomienda=_shipment_to_dict(shipment),
        cotizacion=quote.model_dump(),
        fecha_emision=issue_date,
        hash=mock_hash,
        raw_response=raw_response,
    )
    _mock_receipts_store[(MOCK_RECEIPT_SERIES, number)] = record

    return ReceiptResponse(
        success=True,
        ambiente="mock",
        estado="ACEPTADO_MOCK",
        serie=MOCK_RECEIPT_SERIES,
        numero=number,
        fecha_emision=issue_date,
        codigo_encomienda=shipment.shipment_code,
        total=quote.total,
        subtotal=quote.subtotal,
        igv=quote.igv,
        moneda=quote.currency,
        mensaje="Boleta simulada generada correctamente. Documento sin valor tributario.",
        hash=mock_hash,
        pdf_url=f"{settings.api_prefix}/sunat/boletas/mock/{MOCK_RECEIPT_SERIES}/{number}/pdf",
        xml_url=None,
        cdr=None,
        cdr_code=None,
        cdr_description=None,
        cdr_notes=[],
        raw_response=raw_response,
    )


def get_mock_receipt(series: str, number: str) -> MockReceiptRecord | None:
    return _mock_receipts_store.get((series, number))


def _shipment_to_dict(shipment: Shipment) -> dict[str, Any]:
    return {
        "id": shipment.id,
        "shipment_code": shipment.shipment_code,
        "sender_document_type": shipment.sender_document_type,
        "sender_document_number": shipment.sender_document_number,
        "sender_name": shipment.sender_name,
        "sender_address": shipment.sender_address,
        "sender_phone": shipment.sender_phone,
        "recipient_document_type": shipment.recipient_document_type,
        "recipient_document_number": shipment.recipient_document_number,
        "recipient_name": shipment.recipient_name,
        "recipient_address": shipment.recipient_address,
        "recipient_phone": shipment.recipient_phone,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "description": shipment.description,
        "weight_kg": shipment.weight_kg,
        "length_cm": shipment.length_cm,
        "width_cm": shipment.width_cm,
        "height_cm": shipment.height_cm,
        "fragility": shipment.fragility,
        "status": shipment.status,
        "created_at": shipment.created_at,
        "updated_at": shipment.updated_at,
    }


def _normalize_lycet_response(raw_response: dict[str, Any]) -> dict[str, Any]:
    sunat_response = raw_response.get("sunatResponse") or {}
    cdr_response = sunat_response.get("cdrResponse") or {}
    cdr_code = cdr_response.get("code")
    cdr_notes = cdr_response.get("notes") or []
    if isinstance(cdr_notes, str):
        cdr_notes = [cdr_notes]

    return {
        "status": "ACEPTADO" if cdr_code == "0" else raw_response.get("estado", "ENVIADO_BETA"),
        "hash": raw_response.get("hash"),
        "cdr": sunat_response.get("cdrZip"),
        "cdr_code": cdr_code,
        "cdr_description": cdr_response.get("description"),
        "cdr_notes": cdr_notes,
    }
