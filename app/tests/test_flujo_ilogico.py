"""Pruebas de FLUJOS ILÓGICOS — ningún movimiento inválido debe escaparse.

Verifican que la máquina de estados de la encomienda rechace toda transición que
no tenga sentido de negocio (confirmar/anular/entregar/emitir boleta desde un
estado que no lo permite), devolviendo un error de cliente (4xx) y sin alterar el
estado. Complementan a test_integration_flujo.py (que prueba el camino feliz).

Aislamiento: SQLite en memoria (conftest), SUNAT_ENV=mock. Nomenclatura: FLU-xx.
"""
import pytest

from app.core.config import settings


def _registrar(api_client, valid_shipment_payload, **overrides):
    payload = {**valid_shipment_payload, **overrides}
    created = api_client.post("/api/v1/encomiendas", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _pre_registrar(api_client, valid_shipment_payload, **overrides):
    payload = {**valid_shipment_payload, **overrides}
    created = api_client.post("/api/v1/encomiendas/pre-registro", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _entregar(api_client, shipment_id):
    return api_client.post(
        f"/api/v1/encomiendas/{shipment_id}/entregar",
        json={"dni_receptor": "70876543", "firma_base64": "QA_FIRMA"},
    )


def test_flu01_no_confirmar_una_ya_registrada(api_client, valid_shipment_payload):
    """FLU-01: confirmar-registro sobre una REGISTRADA (no PRE_REGISTRADA) → 400."""
    shipment = _registrar(api_client, valid_shipment_payload)
    response = api_client.post(f"/api/v1/encomiendas/{shipment['id']}/confirmar-registro")
    assert response.status_code == 400, response.text


def test_flu02_no_confirmar_una_anulada(api_client, valid_shipment_payload):
    """FLU-02: confirmar-registro sobre una ANULADA → 400."""
    pre = _pre_registrar(api_client, valid_shipment_payload)
    anulada = api_client.post(
        f"/api/v1/encomiendas/{pre['id']}/anular", json={"motivo": "Prueba FLU-02"}
    )
    assert anulada.status_code == 200
    response = api_client.post(f"/api/v1/encomiendas/{pre['id']}/confirmar-registro")
    assert response.status_code == 400, response.text


def test_flu03_no_anular_una_entregada(api_client, valid_shipment_payload):
    """FLU-03: anular una ENTREGADA → 400."""
    shipment = _registrar(api_client, valid_shipment_payload)
    assert _entregar(api_client, shipment["id"]).status_code == 200
    response = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/anular", json={"motivo": "Prueba FLU-03"}
    )
    assert response.status_code == 400, response.text


def test_flu04_no_entregar_una_anulada(api_client, valid_shipment_payload):
    """FLU-04: entregar una ANULADA → 400."""
    shipment = _registrar(api_client, valid_shipment_payload)
    anulada = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/anular", json={"motivo": "Prueba FLU-04"}
    )
    assert anulada.status_code == 200
    response = _entregar(api_client, shipment["id"])
    assert response.status_code == 400, response.text


def test_flu05_no_entregar_dos_veces(api_client, valid_shipment_payload):
    """FLU-05: entregar una encomienda ya ENTREGADA → 400."""
    shipment = _registrar(api_client, valid_shipment_payload)
    assert _entregar(api_client, shipment["id"]).status_code == 200
    response = _entregar(api_client, shipment["id"])
    assert response.status_code == 400, response.text


def test_flu06_no_anular_dos_veces(api_client, valid_shipment_payload):
    """FLU-06: anular una encomienda ya ANULADA → 400."""
    shipment = _registrar(api_client, valid_shipment_payload)
    primera = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/anular", json={"motivo": "Prueba FLU-06"}
    )
    assert primera.status_code == 200
    segunda = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/anular", json={"motivo": "Otra vez"}
    )
    assert segunda.status_code == 400, segunda.text


def test_flu07_no_emitir_boleta_de_una_preregistrada(api_client, valid_shipment_payload, monkeypatch):
    """FLU-07: emitir boleta sobre una PRE_REGISTRADA → 400."""
    monkeypatch.setattr(settings, "sunat_env", "mock")
    pre = _pre_registrar(api_client, valid_shipment_payload)
    response = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": pre["id"], "confirmar_pago": True},
    )
    assert response.status_code == 400, response.text


def test_flu08_anular_sin_motivo_es_rechazado(api_client, valid_shipment_payload):
    """FLU-08: anular con motivo vacío → 4xx (motivo obligatorio)."""
    shipment = _registrar(api_client, valid_shipment_payload)
    response = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/anular", json={"motivo": "   "}
    )
    assert response.status_code >= 400, response.text


@pytest.mark.parametrize("accion", ["confirmar-registro", "anular", "entregar"])
def test_flu09_operar_sobre_encomienda_inexistente_da_404(api_client, accion):
    """FLU-09: cualquier operación sobre una encomienda inexistente → 404."""
    if accion == "confirmar-registro":
        response = api_client.post("/api/v1/encomiendas/999999/confirmar-registro")
    elif accion == "anular":
        response = api_client.post("/api/v1/encomiendas/999999/anular", json={"motivo": "x"})
    else:
        response = _entregar(api_client, 999999)
    assert response.status_code == 404, response.text


def test_flu10_no_generar_etiqueta_de_una_anulada(api_client, valid_shipment_payload):
    """FLU-10: pedir etiqueta de una ANULADA → 400 (coherente con IT-04)."""
    shipment = _registrar(api_client, valid_shipment_payload)
    api_client.post(f"/api/v1/encomiendas/{shipment['id']}/anular", json={"motivo": "FLU-10"})
    response = api_client.get(f"/api/v1/encomiendas/{shipment['id']}/etiqueta")
    assert response.status_code == 400, response.text
