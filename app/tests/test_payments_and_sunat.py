from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.charge_logs.model import ChargeLog
from app.modules.sunat.model import ElectronicReceipt
from app.modules.sunat import service as sunat_service


def test_card_payment_success_persists_charge_log(
    api_client,
    db_session: Session,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.payments.router.process_payment",
        lambda payload: {
            "api_status": 201,
            "payment_status": "approved",
            "id": "TEST_QA_PAYMENT",
            "response": {"status": "approved"},
        },
    )

    response = api_client.post(
        "/api/v1/payments/process-payment",
        json={
            "token": "TEST_TOKEN",
            "transaction_amount": 25,
            "payment_method_id": "master",
            "usuario": "qa.payment@test.local",
            "payer": {
                "email": "qa.payment@test.local",
                "identification": {"type": "DNI", "number": "12345678"},
            },
        },
    )

    assert response.status_code == 200
    log = db_session.query(ChargeLog).one()
    assert log.result == "Exitoso"
    assert log.modality == "Tarjeta de credito o debito"
    assert log.user == "qa.payment@test.local"
    assert log.finished_at >= log.started_at


def test_card_validation_failure_persists_failed_log(
    api_client,
    db_session: Session,
    monkeypatch,
):
    def fail(_payload):
        raise ValueError("Token requerido")

    monkeypatch.setattr("app.modules.payments.router.process_payment", fail)
    response = api_client.post(
        "/api/v1/payments/process-payment",
        json={"usuario": "qa.failed@test.local"},
    )

    assert response.status_code == 422
    assert db_session.query(ChargeLog).one().result == "Fallido"


def test_yape_success_persists_charge_log(api_client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.modules.yape.router.procesar_pago_yape",
        lambda payload: {
            "status": "approved",
            "id": "TEST_QA_YAPE",
            "payment_method_id": "yape",
        },
    )
    response = api_client.post(
        "/api/v1/yape/process-payment",
        json={
            "token": "TEST_YAPE_TOKEN",
            "amount": 25,
            "email": "qa.yape@test.local",
        },
    )

    assert response.status_code == 200
    log = db_session.query(ChargeLog).one()
    assert log.result == "Exitoso"
    assert log.modality == "Billetera digital (Yape)"


def test_sunat_mock_emission_and_pdf(
    api_client,
    valid_shipment_payload,
    monkeypatch,
):
    monkeypatch.setattr(settings, "sunat_env", "mock")
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload).json()

    emitted = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": created["id"], "confirmar_pago": True},
    )
    assert emitted.status_code == 200, emitted.text
    data = emitted.json()
    assert data["ambiente"] == "mock"
    assert data["estado"] == "ACEPTADO_MOCK"

    pdf = api_client.get(data["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_sunat_beta_client_contract(
    api_client,
    db_session,
    valid_shipment_payload,
    monkeypatch,
):
    monkeypatch.setattr(settings, "sunat_env", "beta")
    send_calls = []

    def emit_receipt(_self, payload):
        send_calls.append(payload)
        return {
            "success": True,
            "mensaje": "TEST QA beta",
            "raw_response": {
                "xml": "<Invoice>TEST_QA_XML</Invoice>",
                "hash": "TEST_HASH",
                "sunatResponse": {
                    "cdrZip": "TEST_CDR",
                    "cdrResponse": {
                        "code": "0",
                        "description": "Aceptado",
                        "notes": [],
                    },
                },
            },
        }

    monkeypatch.setattr(
        sunat_service.LycetClient,
        "emitir_boleta",
        emit_receipt,
    )
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload).json()
    emitted = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": created["id"], "confirmar_pago": True},
    )

    assert emitted.status_code == 200, emitted.text
    assert emitted.json()["ambiente"] == "beta"
    assert emitted.json()["cdr_code"] == "0"
    assert emitted.json()["cdr"] == "TEST_CDR"
    assert emitted.json()["xml"] == "<Invoice>TEST_QA_XML</Invoice>"

    emitted_again = api_client.post(
        "/api/v1/sunat/boletas/emitir-desde-encomienda",
        json={"encomienda_id": created["id"], "confirmar_pago": True},
    )
    assert emitted_again.status_code == 200
    assert len(send_calls) == 1

    receipt = db_session.query(ElectronicReceipt).one()
    assert receipt.signed_xml == "<Invoice>TEST_QA_XML</Invoice>"
    assert receipt.cdr_zip == "TEST_CDR"


def test_sunat_beta_pdf_and_xml_reuse_persisted_receipt(
    api_client,
    db_session,
    valid_shipment_payload,
    monkeypatch,
):
    monkeypatch.setattr(settings, "sunat_env", "beta")
    send_calls = []

    def emit_receipt(_self, payload):
        send_calls.append(payload)
        return {
            "success": True,
            "mensaje": "Aceptado",
            "raw_response": {
                "xml": "<Invoice>FIRMADO_QA</Invoice>",
                "hash": "HASH_QA",
                "sunatResponse": {
                    "cdrZip": "CDR_QA",
                    "cdrResponse": {
                        "code": "0",
                        "description": "La Boleta numero B001 ha sido aceptada",
                        "notes": [],
                    },
                },
            },
        }

    monkeypatch.setattr(sunat_service.LycetClient, "emitir_boleta", emit_receipt)
    created = api_client.post("/api/v1/encomiendas", json=valid_shipment_payload).json()

    pdf = api_client.post(
        "/api/v1/sunat/boletas/beta/pdf-desde-encomienda",
        json={"encomienda_id": created["id"], "confirmar_pago": True},
    )
    xml = api_client.post(
        "/api/v1/sunat/boletas/beta/xml-desde-encomienda",
        json={"encomienda_id": created["id"], "confirmar_pago": True},
    )

    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")
    assert xml.status_code == 200, xml.text
    assert xml.json()["xml"] == "<Invoice>FIRMADO_QA</Invoice>"
    assert xml.json()["cdr"] == "CDR_QA"
    assert xml.json()["cdr_code"] == "0"
    assert len(send_calls) == 1

    persisted = db_session.query(ElectronicReceipt).one()
    assert persisted.shipment_id == created["id"]
    assert persisted.signed_xml == "<Invoice>FIRMADO_QA</Invoice>"
    assert persisted.cdr_zip == "CDR_QA"
