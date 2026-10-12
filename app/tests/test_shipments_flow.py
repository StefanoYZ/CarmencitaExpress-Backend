from sqlalchemy.orm import Session
import pytest

from app.modules.clients.model import Client
from app.modules.claims.model import ShipmentTraceEvent
from app.modules.shipments.constants import (
    CANCELED_STATUS,
    DELIVERED_STATUS,
    PRE_REGISTERED_STATUS,
    REGISTERED_STATUS,
)
from app.modules.shipments.model import Shipment


@pytest.fixture(autouse=True)
def authenticated_client(api_client, admin_headers):
    api_client.headers.update(admin_headers)


def test_pre_registration_confirmation_and_clients(
    api_client,
    db_session: Session,
    valid_shipment_payload,
):
    created = api_client.post(
        "/api/v1/encomiendas/pre-registro",
        json=valid_shipment_payload,
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["estado"] == PRE_REGISTERED_STATUS

    assert db_session.query(Client).filter_by(dni="70123456").one().phone == "987654321"
    assert db_session.query(Client).filter_by(dni="70876543").one().email == "destinatario.qa@test.local"

    confirmed = api_client.post(
        f"/api/v1/encomiendas/{data['id']}/confirmar-registro",
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["estado"] == REGISTERED_STATUS


def test_registered_shipment_tracking_label_and_delivery(
    api_client,
    db_session: Session,
    valid_shipment_payload,
):
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload)
    assert created.status_code == 201, created.text
    shipment = created.json()

    updated_payload = {**valid_shipment_payload, "descripcion": "Paquete QA actualizado"}
    updated_payload.pop("aviso_privacidad_aceptado")
    updated_payload.pop("version_aviso_privacidad")
    updated = api_client.put(f"/api/v1/encomiendas/{shipment['id']}", json=updated_payload)
    assert updated.status_code == 200, updated.text
    quote = api_client.post("/api/v1/cotizaciones/calcular", json={"encomienda_id": shipment["id"]})
    assert quote.status_code == 200, quote.text

    by_code = api_client.get(
        f"/api/v1/encomiendas/codigo/{shipment['codigo_encomienda']}"
    )
    assert by_code.status_code == 200
    assert all("actor_name" not in event for event in by_code.json()["trazabilidad"])

    label = api_client.get(f"/api/v1/encomiendas/{shipment['id']}/etiqueta")
    assert label.status_code == 200
    assert label.json()["qr_payload"]["tracking"].endswith(
        shipment["codigo_encomienda"]
    )

    qr = api_client.get(f"/api/v1/encomiendas/{shipment['id']}/etiqueta/qr")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content.startswith(b"\x89PNG")

    pdf = api_client.get(f"/api/v1/encomiendas/{shipment['id']}/etiqueta/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    delivered = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/entregar",
        json={"dni_receptor": "70876543", "firma_base64": "QA_SIGNATURE"},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["estado"] == DELIVERED_STATUS

    persisted = db_session.query(Shipment).filter_by(id=shipment["id"]).one()
    assert persisted.status == DELIVERED_STATUS
    assert persisted.sender_name == "TEST QA REMITENTE"
    events = (
        db_session.query(ShipmentTraceEvent)
        .filter(ShipmentTraceEvent.shipment_id == shipment["id"])
        .all()
    )
    actor_by_type = {event.event_type: event.actor_name for event in events}
    assert actor_by_type["REGISTRADA"] == "TEST QA ADMIN_GENERAL"
    assert actor_by_type["ACTUALIZADA"] == "TEST QA ADMIN_GENERAL"
    assert actor_by_type["COTIZADA"] == "TEST QA ADMIN_GENERAL"
    assert actor_by_type["REGISTRO_INICIADA"] == "TEST QA ADMIN_GENERAL"
    assert actor_by_type["ENTREGADA"] == "TEST QA ADMIN_GENERAL"


def test_cancel_shipment_blocks_label(api_client, valid_shipment_payload):
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload).json()

    canceled = api_client.post(
        f"/api/v1/encomiendas/{created['id']}/anular",
        json={"motivo": "Prueba funcional QA"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["estado"] == CANCELED_STATUS

    label = api_client.get(f"/api/v1/encomiendas/{created['id']}/etiqueta")
    assert label.status_code == 400


def test_invalid_payload_returns_422(api_client, valid_shipment_payload):
    invalid = {
        **valid_shipment_payload,
        "remitente_numero_documento": "123",
        "peso_kg": 0,
    }
    response = api_client.post("/api/v1/encomiendas", json=invalid)
    assert response.status_code == 422
