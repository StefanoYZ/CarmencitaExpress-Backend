from unittest.mock import Mock

import pytest

from app.modules.payments import service


def _payment_payload(document_number: str) -> dict:
    return {
        "token": "TEST_TOKEN",
        "transaction_amount": 25,
        "payment_method_id": "master",
        "payer": {
            "email": "qa.payment@test.local",
            "identification": {"type": "DNI", "number": document_number},
        },
    }


@pytest.mark.parametrize("document_number", ["123456789", "1234567", "1234ABCD"])
def test_card_payment_rejects_non_peruvian_dni(document_number, monkeypatch):
    sdk = Mock()
    monkeypatch.setattr(service, "_get_sdk", lambda: sdk)

    with pytest.raises(ValueError, match="exactamente 8 digitos"):
        service.process_payment(_payment_payload(document_number))

    sdk.payment.assert_not_called()


def test_card_payment_sends_individual_payer_with_eight_digit_dni(monkeypatch):
    payment_resource = Mock()
    payment_resource.create.return_value = {
        "status": 201,
        "response": {"status": "approved", "id": 123},
    }
    sdk = Mock()
    sdk.payment.return_value = payment_resource
    monkeypatch.setattr(service, "_get_sdk", lambda: sdk)

    result = service.process_payment(_payment_payload("12345678"))

    sent_payer = payment_resource.create.call_args.args[0]["payer"]
    assert sent_payer == {
        "email": "qa.payment@test.local",
        "entity_type": "individual",
        "identification": {"type": "DNI", "number": "12345678"},
    }
    assert result["payment_status"] == "approved"
