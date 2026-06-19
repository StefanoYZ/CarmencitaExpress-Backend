import uuid

import truststore

truststore.inject_into_ssl()

import mercadopago
import requests

from app.core.config import MERCADOPAGO_ACCESS_TOKEN


class PaymentGatewayError(RuntimeError):
    pass


def _get_sdk():
    if not MERCADOPAGO_ACCESS_TOKEN:
        raise ValueError("MERCADOPAGO_ACCESS_TOKEN no esta configurado.")
    return mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)


def _required_text(data: dict, field: str) -> str:
    value = str(data.get(field) or "").strip()
    if not value:
        raise ValueError(f"El campo {field} es obligatorio para procesar la tarjeta.")
    return value


def _build_payer(data: dict) -> dict:
    source = data.get("payer") if isinstance(data.get("payer"), dict) else {}
    identification = (
        source.get("identification")
        if isinstance(source.get("identification"), dict)
        else {}
    )

    email = str(source.get("email") or data.get("cardholderEmail") or "").strip()
    identification_type = str(
        identification.get("type")
        or data.get("identificationType")
        or ""
    ).strip()
    identification_number = str(
        identification.get("number")
        or data.get("identificationNumber")
        or ""
    ).strip()
    first_name = str(
        source.get("first_name")
        or source.get("firstName")
        or data.get("cardholderName")
        or ""
    ).strip()

    if not email:
        raise ValueError("El correo del titular es obligatorio.")
    if not identification_type or not identification_number:
        raise ValueError("El tipo y numero de documento del titular son obligatorios.")

    payer = {
        "email": email,
        "identification": {
            "type": identification_type,
            "number": identification_number,
        },
    }
    if first_name:
        payer["first_name"] = first_name
    return payer


def process_payment(data: dict):
    if not isinstance(data, dict):
        raise ValueError("El payload del pago con tarjeta es invalido.")

    try:
        transaction_amount = float(data.get("transaction_amount"))
    except (TypeError, ValueError) as error:
        raise ValueError("El monto del pago con tarjeta es invalido.") from error
    if transaction_amount <= 0:
        raise ValueError("El monto del pago con tarjeta debe ser mayor a cero.")

    try:
        installments = int(data.get("installments", 1))
    except (TypeError, ValueError) as error:
        raise ValueError("La cantidad de cuotas es invalida.") from error
    if installments < 1:
        raise ValueError("La cantidad de cuotas debe ser mayor a cero.")

    payment_data = {
        "transaction_amount": transaction_amount,
        "token": _required_text(data, "token"),
        "description": data.get("description", "Pago encomienda"),
        "installments": installments,
        "payment_method_id": _required_text(data, "payment_method_id"),
        "payer": _build_payer(data),
    }
    issuer_id = data.get("issuer_id")
    if issuer_id not in (None, ""):
        payment_data["issuer_id"] = issuer_id

    request_options = mercadopago.config.RequestOptions()
    request_options.custom_headers = {
        "x-idempotency-key": str(uuid.uuid4())
    }

    try:
        response = _get_sdk().payment().create(payment_data, request_options)
    except requests.RequestException as error:
        raise PaymentGatewayError(
            "No se pudo establecer una conexion segura con Mercado Pago."
        ) from error

    api_status = int(response.get("status") or 500)
    payment = response.get("response") or {}

    return {
        "api_status": api_status,
        "payment_status": payment.get("status"),
        "status_detail": payment.get("status_detail"),
        "id": payment.get("id"),
        "payment_method_id": payment.get("payment_method_id"),
        "response": payment,
    }
