from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.measurement_logs.service import ensure_boleta_log_after_payment, finish_service_phase
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
    if str(result.get("status") or "").lower() == "approved" and data.get("encomienda_id"):
        shipment_id = int(data["encomienda_id"])
        payment_id = int(result["id"]) if result.get("id") else None
        try:
            finish_service_phase(db, "registro", encomienda_id=shipment_id, pago_id=payment_id)
        except (LookupError, ValueError):
            pass
        ensure_boleta_log_after_payment(
            db,
            encomienda_id=shipment_id,
            pago_id=payment_id,
            usuario=user,
        )
    return result
