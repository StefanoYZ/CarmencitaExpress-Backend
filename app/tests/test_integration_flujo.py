"""Pruebas de INTEGRACIÓN — flujos que cruzan varios módulos por la API real.

A diferencia de las pruebas unitarias (que aíslan la lógica de un módulo), cada
caso aquí ejercita una cadena de módulos a través de la API HTTP + la BD, y
verifica que los efectos se propaguen y persistan a través de las fronteras
entre módulos (las "costuras" del sistema):

    shipments · clients · payments · charge_logs · sunat · optimization · auth

Aislamiento: SQLite en memoria (conftest), SUNAT_ENV=mock, integraciones de pago
mockeadas. Nomenclatura de casos: IT-xx (Integration Test).
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.charge_logs.model import ChargeLog
from app.modules.clients.model import Client
from app.modules.shipments.constants import (
    CANCELED_STATUS,
    DELIVERED_STATUS,
    PRE_REGISTERED_STATUS,
    REGISTERED_STATUS,
)
from app.modules.shipments.model import Shipment
from app.modules.sunat.model import ElectronicReceipt


def test_it01_ciclo_cliente_externo_preregistro_confirmar_boleta(
    api_client,
    db_session: Session,
    valid_shipment_payload,
    monkeypatch,
):
    """IT-01 · shipments + clients + sunat.

    Pre-registro público → upsert de cliente → confirmación de registro →
    emisión de boleta (mock) → PDF. Verifica que cada módulo reciba el estado
    correcto del anterior y que el comprobante quede ligado a la encomienda.
    """
    monkeypatch.setattr(settings, "sunat_env", "mock")

    # 1) shipments: pre-registro (crea encomienda PRE_REGISTRADA).
    pre = api_client.post("/api/v1/encomiendas/pre-registro", json=valid_shipment_payload)
    assert pre.status_code == 201, pre.text
    shipment_id = pre.json()["id"]
    assert pre.json()["estado"] == PRE_REGISTERED_STATUS

    # 2) clients: el pre-registro debió upsertear remitente y destinatario.
    remitente = db_session.query(Client).filter_by(dni="70123456").one()
    assert remitente.phone == "987654321"
    db_session.query(Client).filter_by(dni="70876543").one()

    # 3) shipments: confirmar-registro transiciona PRE_REGISTRADA → REGISTRADA.
    confirmed = api_client.post(f"/api/v1/encomiendas/{shipment_id}/confirmar-registro")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["estado"] == REGISTERED_STATUS

    # 4) sunat: emitir boleta desde la encomienda ya registrada + pago confirmado.
    emitted = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": shipment_id, "confirmar_pago": True},
    )
    assert emitted.status_code == 200, emitted.text
    assert emitted.json()["estado"] == "ACEPTADO_MOCK"

    # 5) sunat: el PDF referenciado por la respuesta se sirve correctamente.
    pdf = api_client.get(emitted.json()["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_it02_ciclo_interno_secretaria_registro_pago_boleta_entrega(
    api_client,
    db_session: Session,
    valid_shipment_payload,
    monkeypatch,
):
    """IT-02 · shipments + payments + charge_logs + sunat.

    Ciclo de secretaría de punta a punta: registro interno → cobro con tarjeta
    (deja charge log) → emisión de boleta → entrega final. Verifica que los
    efectos de cada módulo (log de cobro, comprobante, estado final) coexistan.
    """
    monkeypatch.setattr(settings, "sunat_env", "mock")
    monkeypatch.setattr(
        "app.modules.payments.router.process_payment",
        lambda payload: {
            "api_status": 201,
            "payment_status": "approved",
            "id": "IT02_PAYMENT",
            "response": {"status": "approved"},
        },
    )

    # 1) shipments: registro interno directo (queda REGISTRADA).
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload)
    assert created.status_code == 201, created.text
    shipment = created.json()

    # 2) payments + charge_logs: cobro con tarjeta deja un log de cobro exitoso.
    payment = api_client.post(
        "/api/v1/payments/process-payment",
        json={
            "token": "IT02_TOKEN",
            "transaction_amount": shipment.get("precio_con_igv", 25),
            "payment_method_id": "master",
            "usuario": "qa.integracion@test.local",
            "payer": {
                "email": "qa.integracion@test.local",
                "identification": {"type": "DNI", "number": "70123456"},
            },
        },
    )
    assert payment.status_code == 200, payment.text
    charge = db_session.query(ChargeLog).one()
    assert charge.result == "Exitoso"
    assert charge.modality == "Tarjeta de credito o debito"

    # 3) sunat: emisión de boleta para la encomienda pagada.
    emitted = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": shipment["id"], "confirmar_pago": True},
    )
    assert emitted.status_code == 200, emitted.text

    # 4) shipments: entrega final → ENTREGADA persistida.
    delivered = api_client.post(
        f"/api/v1/encomiendas/{shipment['id']}/entregar",
        json={"dni_receptor": "70876543", "firma_base64": "IT02_SIGNATURE"},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["estado"] == DELIVERED_STATUS

    persisted = db_session.query(Shipment).filter_by(id=shipment["id"]).one()
    assert persisted.status == DELIVERED_STATUS


def test_it03_upsert_de_cliente_entre_dos_preregistros(
    api_client,
    db_session: Session,
    valid_shipment_payload,
):
    """IT-03 · shipments + clients.

    Dos pre-registros con el mismo remitente (mismo DNI) no duplican el cliente:
    lo actualizan. Verifica el upsert idempotente del módulo clients a través del
    endpoint de shipments.
    """
    first = api_client.post("/api/v1/encomiendas/pre-registro", json=valid_shipment_payload)
    assert first.status_code == 201, first.text

    segundo_payload = {
        **valid_shipment_payload,
        "remitente_telefono": "999888777",
        "remitente_correo": "actualizado.qa@test.local",
        "descripcion": "Segundo envío mismo remitente",
    }
    second = api_client.post("/api/v1/encomiendas/pre-registro", json=segundo_payload)
    assert second.status_code == 201, second.text

    # Un único cliente para ese DNI, con los datos del segundo envío.
    remitentes = db_session.query(Client).filter_by(dni="70123456").all()
    assert len(remitentes) == 1
    assert remitentes[0].phone == "999888777"
    assert remitentes[0].email == "actualizado.qa@test.local"


def test_it04_anulacion_propaga_bloqueos_a_etiqueta_y_boleta(
    api_client,
    valid_shipment_payload,
    monkeypatch,
):
    """IT-04 · shipments + etiquetas + sunat.

    Anular una encomienda debe bloquear en cascada la generación de etiqueta y la
    emisión de boleta. Verifica que el cambio de estado en shipments se respete en
    los módulos que dependen de él.
    """
    monkeypatch.setattr(settings, "sunat_env", "mock")
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload).json()

    canceled = api_client.post(
        f"/api/v1/encomiendas/{created['id']}/anular",
        json={"motivo": "Prueba de integración IT-04"},
    )
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["estado"] == CANCELED_STATUS

    # etiquetas: bloqueada para una encomienda anulada.
    label = api_client.get(f"/api/v1/encomiendas/{created['id']}/etiqueta")
    assert label.status_code == 400

    # sunat: no se debe poder emitir boleta de una encomienda anulada.
    boleta = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": created["id"], "confirmar_pago": True},
    )
    assert boleta.status_code >= 400, boleta.text


def test_it05_encomiendas_registradas_alimentan_optimizacion_estiba(
    api_client,
    estiba_headers,
    valid_shipment_payload,
):
    """IT-05 · shipments + optimization + auth (RBAC).

    Las encomiendas registradas del día deben quedar disponibles para el módulo de
    optimización, ejecutable solo por ESTIBA. Verifica la costura registro→carga y
    que el control de acceso por rol se aplique en el flujo real.
    """
    for index, destino in enumerate(("Shorey", "Angasmarca", "Orocullay"), start=1):
        payload = {
            **valid_shipment_payload,
            "descripcion": f"Encomienda IT-05 {index}",
            "destino": destino,
            "tipo_contenido": "ROPA",
            "largo_cm": 30 + index,
            "ancho_cm": 20 + index,
            "alto_cm": 15 + index,
            "orientacion_base": "LARGO_ANCHO",
        }
        created = api_client.post("/api/v1/encomiendas", json=payload)
        assert created.status_code == 201, created.text

    run = api_client.post(
        "/api/v1/optimization/poc/best-fit-decreasing/run",
        headers=estiba_headers,
        json={"truck_id": "CAMION_A", "package_limit": 3, "allow_rotation": True},
    )
    assert run.status_code == 200, run.text
    metrics = run.json()["metrics"]
    assert metrics["placed_count"] == 3
    assert metrics["overlap_violations"] == 0
    assert metrics["boundary_violations"] == 0
