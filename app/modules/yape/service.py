import mercadopago

from app.core.config import MERCADOPAGO_ACCESS_TOKEN


def _get_sdk():
    if not MERCADOPAGO_ACCESS_TOKEN:
        raise ValueError("MERCADOPAGO_ACCESS_TOKEN no esta configurado.")
    return mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)


def procesar_pago_yape(data: dict):
    token = data.get("token")
    amount = data.get("amount")
    email = data.get("email", "test@test.com")

    if not token:
        return {"status": "error", "message": "Token de Yape requerido"}

    payment_data = {
        "transaction_amount": float(amount),
        "token": token,
        "description": "Pago con Yape - Carmencita Express",
        "installments": 1,
        "payment_method_id": "yape",
        "payer": {
            "email": email
        }
    }

    payment_response = _get_sdk().payment().create(payment_data)
    payment = payment_response.get("response", {})

    return {
        "status": payment.get("status"),
        "status_detail": payment.get("status_detail"),
        "id": payment.get("id"),
        "payment_method_id": payment.get("payment_method_id"),
        "data": payment
    }