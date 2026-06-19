import pytest
from pydantic import ValidationError

from app.modules.clients.schema import ClientCreate
from app.modules.shipments.schema import ShipmentCreate


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("remitente_numero_documento", "1234567"),
        ("remitente_numero_documento", "1234ABCD"),
        ("remitente_telefono", "812345678"),
        ("remitente_telefono", "999999999"),
        ("remitente_correo", "correo-invalido"),
        ("peso_kg", 0),
        ("largo_cm", -1),
        ("fragilidad", "EXTREMA"),
    ],
)
def test_shipment_rejects_invalid_fields(valid_shipment_payload, field, value):
    payload = {**valid_shipment_payload, field: value}

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_shipment_normalizes_valid_data(valid_shipment_payload):
    shipment = ShipmentCreate(**valid_shipment_payload)

    assert shipment.sender_email == "remitente.qa@test.local"
    assert shipment.fragility == "MEDIA"
    assert shipment.content_type == "DOCUMENTOS"
    assert shipment.sender_phone == "987654321"


def test_client_rejects_invalid_phone():
    with pytest.raises(ValidationError):
        ClientCreate(
            dni="70123456",
            nombre_completo="TEST QA",
            telefono="999999999",
        )
