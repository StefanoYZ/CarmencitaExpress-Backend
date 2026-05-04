import uuid
import mercadopago

from app.core.config import MERCADOPAGO_ACCESS_TOKEN

sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)


def process_payment(data: dict):
    payment_data = {
        "transaction_amount": float(data.get("transaction_amount")),
        "token": data.get("token"),
        "description": data.get("description", "Pago encomienda"),
        "installments": int(data.get("installments", 1)),
        "payment_method_id": data.get("payment_method_id"),
        "issuer_id": data.get("issuer_id"),
        "payer": {
            "email": "test@test.com",
            "first_name": "APRO",
            "last_name": "",
            "identification": {
                "type": "DNI",
                "number": "12345678"
            }
        }
    }

    request_options = mercadopago.config.RequestOptions()
    request_options.custom_headers = {
        "X-Idempotency-Key": str(uuid.uuid4())
    }

    response = sdk.payment().create(payment_data, request_options)

    print("STATUS MP:", response.get("status"))
    print("RESPONSE MP:", response.get("response"))

    return {
        "status": response.get("status"),
        "response": response.get("response")
    }