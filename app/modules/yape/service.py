import os
import mercadopago
from dotenv import load_dotenv

load_dotenv()

MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")

sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)

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

    payment_response = sdk.payment().create(payment_data)
    payment = payment_response.get("response", {})

    return {
        "status": payment.get("status"),
        "status_detail": payment.get("status_detail"),
        "id": payment.get("id"),
        "payment_method_id": payment.get("payment_method_id"),
        "data": payment
    }