"""Pruebas unitarias de la cotización (tarifa).

Fórmula vigente (app/modules/quotes/service.py):
    subtotal = base_rate(ruta) + peso_kg*2 + volumen_m3*20 + recargo_fragilidad
    igv      = subtotal * 0.18
    total    = subtotal + igv
"""
import pytest

from app.modules.quotes.service import calculate_quote, calculate_quote_for_shipment
from app.modules.shipments.constants import CANCELED_STATUS
from app.modules.shipments.model import Shipment


def _shipment(**overrides) -> Shipment:
    base = dict(
        id=1,
        shipment_code="J000000001",
        origin="Trujillo",
        destination="Angasmarca",
        weight_kg=10.5,
        length_cm=40,
        width_cm=30,
        height_cm=20,
        fragility="MEDIA",
        content_type="DOCUMENTOS",
    )
    base.update(overrides)
    return Shipment(**base)


def test_cotizacion_datos_validos_calcula_tarifa_exacta():
    # base 10 (Trujillo-Angasmarca) + 21 (10.5*2) + 0.48 (vol) + 5 (MEDIA) = 36.48
    quote = calculate_quote_for_shipment(_shipment())
    assert quote.subtotal == 36.48
    assert quote.igv == 6.57
    assert quote.total == 43.05
    assert quote.currency == "PEN"
    assert quote.detail["base_rate"] == 10.00
    assert quote.detail["volume_m3"] == 0.024


def test_cotizacion_ruta_desconocida_usa_tarifa_por_defecto():
    quote = calculate_quote_for_shipment(_shipment(destination="Shorey"))
    assert quote.detail["base_rate"] == 12.00


def test_cotizacion_fragilidad_baja_sin_recargo():
    quote = calculate_quote_for_shipment(_shipment(fragility="BAJA"))
    assert quote.detail["fragility_surcharge"] == 0.00


def test_cotizacion_contenido_fragil_eleva_recargo_minimo():
    # Aunque la fragilidad sea BAJA, un contenido "fragil" fuerza recargo >= MEDIA (5).
    quote = calculate_quote_for_shipment(
        _shipment(fragility="BAJA", content_type="VIDRIO FRAGIL")
    )
    assert quote.detail["fragility_surcharge"] == 5.00


def test_cotizacion_volumen_se_incluye_en_subtotal():
    sin_vol = calculate_quote_for_shipment(
        _shipment(length_cm=0, width_cm=0, height_cm=0)
    )
    con_vol = calculate_quote_for_shipment(_shipment())
    assert con_vol.subtotal > sin_vol.subtotal


def test_cotizacion_encomienda_inexistente_devuelve_none(db_session):
    assert calculate_quote(db_session, 999999) is None


def test_cotizacion_encomienda_anulada_es_rechazada(db_session):
    from app.modules.shipments import repository as shipments_repo
    from app.modules.shipments.schema import ShipmentCreate

    payload = ShipmentCreate(
        remitente_tipo_documento="DNI",
        remitente_numero_documento="70123456",
        remitente_nombre="QA REMITENTE",
        destinatario_nombre="QA DESTINATARIO",
        origen="Trujillo",
        destino="Angasmarca",
        descripcion="paquete qa",
        peso_kg=5,
        largo_cm=20,
        ancho_cm=20,
        alto_cm=20,
        fragilidad="BAJA",
        orientacion_base="LARGO_ANCHO",
    )
    shipment = shipments_repo.create_shipment(db_session, payload)
    shipment.status = CANCELED_STATUS
    db_session.commit()

    with pytest.raises(ValueError):
        calculate_quote(db_session, shipment.id)
