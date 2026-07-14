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
        # Cotas superiores (max): camion 491x210x220 cm, 5470 kg.
        ("peso_kg", 5470.01),
        ("peso_kg", 999999),
        ("largo_cm", 491.01),
        ("ancho_cm", 50000),
        ("alto_cm", 491.01),
    ],
)
def test_shipment_rejects_invalid_fields(valid_shipment_payload, field, value):
    payload = {**valid_shipment_payload, field: value}

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("peso_kg", 0.01),      # limite inferior valido (> 0)
        ("peso_kg", 5470),      # limite superior valido (= capacidad)
        ("largo_cm", 491),      # limite superior valido (= largo del camion)
    ],
)
def test_shipment_accepts_boundary_values(valid_shipment_payload, field, value):
    payload = {**valid_shipment_payload, field: value}

    shipment = ShipmentCreate(**payload)

    assert getattr(shipment, {"peso_kg": "weight_kg", "largo_cm": "length_cm"}[field]) == value


def test_shipment_normalizes_valid_data(valid_shipment_payload):
    shipment = ShipmentCreate(**valid_shipment_payload)

    assert shipment.sender_email == "remitente.qa@test.local"
    assert shipment.fragility == "MEDIA"
    assert shipment.content_type == "ROPA"
    assert shipment.sender_phone == "987654321"


def test_shipment_rejects_same_origin_and_destination(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "origen": "Trujillo",
        "destino": "trujillo",
    }

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_document_envelope_allows_zero_dimensions(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "DOCUMENTOS",
        "peso_kg": 1.0,
        "largo_cm": 0,
        "ancho_cm": 0,
        "alto_cm": 0,
    }

    shipment = ShipmentCreate(**payload)

    assert shipment.length_cm == 0
    assert shipment.width_cm == 0
    assert shipment.height_cm == 0


def test_document_envelope_rejects_weight_over_limit(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "DOCUMENTOS",
        "largo_cm": 0,
        "ancho_cm": 0,
        "alto_cm": 0,
        "peso_kg": 1.6,  # supera el maximo de 1.5 kg para sobres
    }

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_document_envelope_accepts_max_weight(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "DOCUMENTOS",
        "largo_cm": 0,
        "ancho_cm": 0,
        "alto_cm": 0,
        "peso_kg": 1.5,  # limite superior valido para un sobre
    }

    shipment = ShipmentCreate(**payload)

    assert shipment.weight_kg == 1.5


@pytest.mark.parametrize("field", ["largo_cm", "ancho_cm", "alto_cm"])
def test_package_rejects_zero_dimensions(valid_shipment_payload, field):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "ROPA",
        "descripcion": "Caja de ropa",
        "largo_cm": 40,
        "ancho_cm": 30,
        "alto_cm": 20,
        "orientacion_base": "LARGO_ANCHO",
        field: 0,
    }

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_package_requires_base_orientation(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "ROPA",
        "descripcion": "Caja de ropa",
        "orientacion_base": None,
    }

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_document_envelope_normalizes_base_orientation(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "DOCUMENTOS",
        "descripcion": "Sobre con contratos",
        "peso_kg": 1.0,
        "largo_cm": 0,
        "ancho_cm": 0,
        "alto_cm": 0,
        "orientacion_base": "LARGO_ALTO",
    }

    shipment = ShipmentCreate(**payload)

    assert shipment.base_orientation is None


def test_upright_appliance_rejects_unsafe_base_orientation(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "ELECTRODOMESTICOS",
        "descripcion": "Refrigeradora familiar",
        "peso_kg": 80,
        "largo_cm": 70,
        "ancho_cm": 60,
        "alto_cm": 170,
        "fragilidad": "MEDIA",
        "orientacion_base": "LARGO_ALTO",
    }

    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_upright_appliance_accepts_safe_base_orientation(valid_shipment_payload):
    payload = {
        **valid_shipment_payload,
        "tipo_contenido": "ELECTRODOMESTICOS",
        "descripcion": "Refrigeradora familiar",
        "peso_kg": 80,
        "largo_cm": 70,
        "ancho_cm": 60,
        "alto_cm": 170,
        "fragilidad": "MEDIA",
        "orientacion_base": "LARGO_ANCHO",
    }

    shipment = ShipmentCreate(**payload)

    assert shipment.base_orientation == "LARGO_ANCHO"


def test_distinct_people_cannot_share_phone(valid_shipment_payload):
    payload = {**valid_shipment_payload, "destinatario_telefono": valid_shipment_payload["remitente_telefono"]}
    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_distinct_people_cannot_share_email(valid_shipment_payload):
    payload = {**valid_shipment_payload, "destinatario_correo": valid_shipment_payload["remitente_correo"]}
    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


def test_same_person_may_share_phone_and_email(valid_shipment_payload):
    # Mismo DNI en remitente y destinatario: se permite compartir contacto.
    payload = {
        **valid_shipment_payload,
        "destinatario_numero_documento": valid_shipment_payload["remitente_numero_documento"],
        "destinatario_telefono": valid_shipment_payload["remitente_telefono"],
        "destinatario_correo": valid_shipment_payload["remitente_correo"],
    }
    shipment = ShipmentCreate(**payload)
    assert shipment.recipient_phone == shipment.sender_phone


def test_client_rejects_invalid_phone():
    with pytest.raises(ValidationError):
        ClientCreate(
            dni="70123456",
            nombre_completo="TEST QA",
            telefono="999999999",
        )
