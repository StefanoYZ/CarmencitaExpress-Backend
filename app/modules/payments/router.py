from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.payments.service import PaymentGatewayError, process_payment
from app.core.config import MERCADOPAGO_PUBLIC_KEY
from app.modules.charge_logs.service import (
    CARD_MODALITY,
    FAILED_RESULT,
    extract_user_from_authorization_header,
    extract_user_from_payload,
    infer_card_payment_result,
    register_charge_log,
    start_charge_measurement,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/public-key")
def get_public_key():
    if not MERCADOPAGO_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="MERCADOPAGO_PUBLIC_KEY no esta configurado.",
        )
    return {"publicKey": MERCADOPAGO_PUBLIC_KEY}


@router.post("/process-payment")
def create_payment(
    data: dict = Body(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    started_at, perf_start = start_charge_measurement()
    user = (
        extract_user_from_payload(data)
        or extract_user_from_authorization_header(authorization)
    )

    try:
        result = process_payment(data)
    except ValueError as error:
        register_charge_log(
            db,
            started_at=started_at,
            perf_start=perf_start,
            user=user,
            result=FAILED_RESULT,
            modality=CARD_MODALITY,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error
    except PaymentGatewayError as error:
        register_charge_log(
            db,
            started_at=started_at,
            perf_start=perf_start,
            user=user,
            result=FAILED_RESULT,
            modality=CARD_MODALITY,
        )
        raise HTTPException(status_code=502, detail=str(error)) from error

    api_status = result.get("api_status", 500)
    register_charge_log(
        db,
        started_at=started_at,
        perf_start=perf_start,
        user=user,
        result=infer_card_payment_result(result),
        modality=CARD_MODALITY,
    )
    if api_status not in [200, 201]:
        response = result.get("response") or {}
        cause = response.get("cause")
        detail = response.get("message") or response.get("error") or cause or response
        raise HTTPException(
            status_code=api_status if 400 <= api_status < 500 else 502,
            detail=detail,
        )

    return result
