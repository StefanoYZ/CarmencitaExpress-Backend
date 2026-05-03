from datetime import date, datetime
from typing import Any

from app.core.config import settings
from app.modules.cotizacion.schema import CotizacionResponse
from app.modules.cotizacion.service import calcular_cotizacion_para_encomienda
from app.modules.encomiendas.schema import EncomiendaResponse
from app.modules.encomiendas.service import get_encomienda
from app.modules.sunat.client import LycetClient
from app.modules.sunat.exceptions import SunatEmissionBlockedError
from app.modules.sunat.schema import BoletaMockRecord, BoletaResponse


SERIE_BOLETA_MOCK = "B001"

# TODO: reemplazar este almacenamiento en memoria por repository + PostgreSQL.
_boletas_mock_store: dict[tuple[str, str], BoletaMockRecord] = {}
_next_boleta_mock_number = 1


def _next_boleta_number() -> str:
    global _next_boleta_mock_number

    numero = f"{_next_boleta_mock_number:06d}"
    _next_boleta_mock_number += 1
    return numero


def _tipo_documento_sunat(tipo_documento: str) -> str:
    tipo = tipo_documento.strip().upper()
    if tipo == "DNI":
        return "1"
    if tipo == "RUC":
        return "6"
    return "0"


def build_boleta_payload(
    encomienda: EncomiendaResponse,
    cotizacion: CotizacionResponse,
    correlativo: str | None = None,
) -> dict[str, Any]:
    correlativo = correlativo or _next_boleta_number()
    descripcion = (
        f"SERVICIO DE TRANSPORTE DE ENCOMIENDA - {encomienda.origen} A {encomienda.destino} "
        f"- CODIGO {encomienda.codigo_encomienda}"
    )

    return {
        "ublVersion": "2.1",
        "tipoOperacion": "0101",
        "tipoDoc": "03",
        "serie": SERIE_BOLETA_MOCK,
        "correlativo": correlativo,
        "fechaEmision": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tipoMoneda": "PEN",
        "formaPago": {
            "moneda": "PEN",
            "tipo": "Contado",
            "monto": cotizacion.total,
        },
        "client": {
            "tipoDoc": _tipo_documento_sunat(encomienda.remitente_tipo_documento),
            "numDoc": encomienda.remitente_numero_documento,
            "rznSocial": encomienda.remitente_nombre,
            "address": {
                "direccion": encomienda.remitente_direccion or "",
                "provincia": "",
                "departamento": "",
                "distrito": "",
                "ubigueo": "",
                "codigoPais": "PE",
            },
        },
        "company": {
            # TODO: configurar datos oficiales solo cuando se habilite emision autorizada.
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
        "mtoOperGravadas": cotizacion.subtotal,
        "mtoIGV": cotizacion.igv,
        "totalImpuestos": cotizacion.igv,
        "valorVenta": cotizacion.subtotal,
        "subTotal": cotizacion.total,
        "mtoImpVenta": cotizacion.total,
        "details": [
            {
                "unidad": "ZZ",
                "cantidad": 1,
                "codProducto": encomienda.codigo_encomienda,
                "codProdSunat": "78101802",
                "descripcion": descripcion,
                "mtoValorUnitario": cotizacion.subtotal,
                "descuento": 0,
                "igv": cotizacion.igv,
                "tipAfeIgv": "10",
                "isc": 0,
                "totalImpuestos": cotizacion.igv,
                "mtoPrecioUnitario": cotizacion.total,
                "mtoValorVenta": cotizacion.subtotal,
                "mtoValorGratuito": 0,
                "mtoBaseIgv": cotizacion.subtotal,
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
                # TODO: convertir el total a letras correctamente.
                "value": f"SON {cotizacion.total:.2f} SOLES",
            }
        ],
        "metadata": {
            "codigo_encomienda": encomienda.codigo_encomienda,
            "destinatario": {
                "tipo_documento": encomienda.destinatario_tipo_documento,
                "numero_documento": encomienda.destinatario_numero_documento,
                "nombre": encomienda.destinatario_nombre,
                "direccion": encomienda.destinatario_direccion,
                "telefono": encomienda.destinatario_telefono,
            },
        },
    }


def emitir_boleta_desde_encomienda(encomienda_id: int, confirmar_pago: bool = True) -> BoletaResponse:
    if settings.production_emission_blocked:
        raise SunatEmissionBlockedError("Emision real bloqueada por configuracion")

    if not confirmar_pago:
        raise ValueError("Debe confirmar el pago para emitir la boleta")

    encomienda = get_encomienda(encomienda_id)
    if encomienda is None:
        raise LookupError("Encomienda no encontrada")

    cotizacion = calcular_cotizacion_para_encomienda(encomienda)
    numero = _next_boleta_number()
    payload = build_boleta_payload(encomienda, cotizacion, numero)

    if settings.sunat_env == "mock":
        return _emitir_boleta_mock(encomienda, cotizacion, payload, numero)

    if settings.sunat_env == "beta":
        result = LycetClient().emitir_boleta(payload)
        today = date.today().isoformat()
        return BoletaResponse(
            success=result.get("success", False),
            ambiente="beta",
            estado=result.get("estado", "ENVIADO_BETA"),
            serie=SERIE_BOLETA_MOCK,
            numero=numero,
            fecha_emision=today,
            codigo_encomienda=encomienda.codigo_encomienda,
            total=cotizacion.total,
            subtotal=cotizacion.subtotal,
            igv=cotizacion.igv,
            moneda=cotizacion.moneda,
            mensaje=result.get("mensaje", "Boleta enviada a Lycet beta."),
            raw_response=result.get("raw_response", result),
        )

    raise SunatEmissionBlockedError("SUNAT_ENV=production esta bloqueado para esta etapa")


def generar_pdf_beta_desde_encomienda(encomienda_id: int, confirmar_pago: bool = True) -> tuple[str, bytes]:
    encomienda, cotizacion, payload = _build_beta_payload_desde_encomienda(encomienda_id, confirmar_pago)
    pdf_bytes = LycetClient().generar_pdf(payload)
    filename = f"boleta_beta_{encomienda.codigo_encomienda}.pdf"
    return filename, pdf_bytes


def generar_xml_beta_desde_encomienda(encomienda_id: int, confirmar_pago: bool = True) -> dict[str, Any]:
    encomienda, _cotizacion, payload = _build_beta_payload_desde_encomienda(encomienda_id, confirmar_pago)
    lycet_response = LycetClient().generar_xml(payload)

    if isinstance(lycet_response, str):
        return {
            "success": True,
            "ambiente": "beta",
            "codigo_encomienda": encomienda.codigo_encomienda,
            "xml": lycet_response,
        }

    return {
        "success": True,
        "ambiente": "beta",
        "codigo_encomienda": encomienda.codigo_encomienda,
        "raw_response": lycet_response,
    }


def _build_beta_payload_desde_encomienda(
    encomienda_id: int,
    confirmar_pago: bool,
) -> tuple[EncomiendaResponse, CotizacionResponse, dict[str, Any]]:
    if settings.sunat_env != "beta":
        raise SunatEmissionBlockedError("Este endpoint solo funciona cuando SUNAT_ENV=beta")

    if not confirmar_pago:
        raise ValueError("Debe confirmar el pago para generar el comprobante beta")

    encomienda = get_encomienda(encomienda_id)
    if encomienda is None:
        raise LookupError("Encomienda no encontrada")

    cotizacion = calcular_cotizacion_para_encomienda(encomienda)
    payload = build_boleta_payload(encomienda, cotizacion)
    return encomienda, cotizacion, payload


def _emitir_boleta_mock(
    encomienda: EncomiendaResponse,
    cotizacion: CotizacionResponse,
    payload: dict[str, Any],
    numero: str,
) -> BoletaResponse:
    fecha_emision = date.today().isoformat()
    mock_hash = f"MOCK-HASH-{SERIE_BOLETA_MOCK}-{numero}"
    raw_response = {
        "modo": "mock",
        "advertencia": "Este comprobante es simulado y no fue enviado a SUNAT.",
        "payload": payload,
    }

    record = BoletaMockRecord(
        serie=SERIE_BOLETA_MOCK,
        numero=numero,
        codigo_encomienda=encomienda.codigo_encomienda,
        encomienda=encomienda.model_dump(),
        cotizacion=cotizacion.model_dump(),
        fecha_emision=fecha_emision,
        hash=mock_hash,
        raw_response=raw_response,
    )
    _boletas_mock_store[(SERIE_BOLETA_MOCK, numero)] = record

    return BoletaResponse(
        success=True,
        ambiente="mock",
        estado="ACEPTADO_MOCK",
        serie=SERIE_BOLETA_MOCK,
        numero=numero,
        fecha_emision=fecha_emision,
        codigo_encomienda=encomienda.codigo_encomienda,
        total=cotizacion.total,
        subtotal=cotizacion.subtotal,
        igv=cotizacion.igv,
        moneda=cotizacion.moneda,
        mensaje="Boleta simulada generada correctamente. Documento sin valor tributario.",
        hash=mock_hash,
        pdf_url=f"{settings.api_prefix}/sunat/boletas/mock/{SERIE_BOLETA_MOCK}/{numero}/pdf",
        xml_url=None,
        cdr=None,
        raw_response=raw_response,
    )


def get_boleta_mock(serie: str, numero: str) -> BoletaMockRecord | None:
    return _boletas_mock_store.get((serie, numero))
