from fastapi import APIRouter, Body, HTTPException
from app.modules.payments.service import process_payment
from app.core.config import MERCADOPAGO_PUBLIC_KEY

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/public-key")
def get_public_key():
    return {"publicKey": MERCADOPAGO_PUBLIC_KEY}


@router.post("/process-payment")
def create_payment(data: dict = Body(...)):
    result = process_payment(data)

    if result.get("status") not in [200, 201]:
        raise HTTPException(
            status_code=500,
            detail=result.get("response")
        )

    return result