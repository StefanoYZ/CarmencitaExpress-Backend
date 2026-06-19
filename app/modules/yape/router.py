from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.charge_logs.service import (
    FAILED_RESULT,
    YAPE_MODALITY,
    extract_user_from_authorization_header,
    extract_user_from_payload,
    infer_yape_payment_result,
    register_charge_log,
    start_charge_measurement,
)
from .service import procesar_pago_yape

router = APIRouter(prefix="/yape", tags=["Yape"])

@router.post("/process-payment")
def process_yape_payment(
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
        result = procesar_pago_yape(data)
    except Exception as error:
        register_charge_log(
            db,
            started_at=started_at,
            perf_start=perf_start,
            user=user,
            result=FAILED_RESULT,
            modality=YAPE_MODALITY,
        )
        raise HTTPException(
            status_code=502,
            detail="No se pudo procesar el pago con Yape.",
        ) from error

    register_charge_log(
        db,
        started_at=started_at,
        perf_start=perf_start,
        user=user,
        result=infer_yape_payment_result(result),
        modality=YAPE_MODALITY,
    )
    return result
