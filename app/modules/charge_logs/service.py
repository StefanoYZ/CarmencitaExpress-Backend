from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.modules.charge_logs import repository
from app.modules.charge_logs.model import ChargeLog


SUCCESS_RESULT = "Exitoso"
FAILED_RESULT = "Fallido"
CARD_MODALITY = "Tarjeta de credito o debito"
YAPE_MODALITY = "Billetera digital (Yape)"


def start_charge_measurement() -> tuple[datetime, float]:
    return datetime.now(timezone.utc), perf_counter()


def list_charge_logs(db: Session, limit: int = 100) -> list[ChargeLog]:
    return repository.list_charge_logs(db, limit)


def register_charge_log(
    db: Session,
    *,
    started_at: datetime,
    perf_start: float,
    user: str | None,
    result: str,
    modality: str,
) -> ChargeLog | None:
    finished_at = datetime.now(timezone.utc)
    response_time_ms = max(0, round((perf_counter() - perf_start) * 1000))

    try:
        return repository.create_charge_log(
            db,
            started_at=started_at,
            finished_at=finished_at,
            user=normalize_user(user),
            response_time_ms=response_time_ms,
            result=result,
            modality=modality,
        )
    except Exception:
        db.rollback()
        return None


def infer_card_payment_result(result: dict[str, Any] | None) -> str:
    if not result:
        return FAILED_RESULT
    api_status = result.get("api_status", result.get("status"))
    payment = result.get("response") or {}
    payment_status = str(
        result.get("payment_status") or payment.get("status") or ""
    ).lower()
    return (
        SUCCESS_RESULT
        if api_status in (200, 201) and payment_status not in {"rejected", "cancelled", "error"}
        else FAILED_RESULT
    )


def infer_yape_payment_result(result: dict[str, Any] | None) -> str:
    if not result:
        return FAILED_RESULT
    status = str(result.get("status") or "").lower()
    return SUCCESS_RESULT if status in {"approved", "accredited"} else FAILED_RESULT


def extract_user_from_payload(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    for key in ("usuario", "user", "username", "user_name", "email"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    payer = data.get("payer")
    if isinstance(payer, dict):
        value = payer.get("email")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_user_from_authorization_header(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    except Exception:
        return None
    for key in ("username", "email", "sub"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def normalize_user(user: str | None) -> str | None:
    value = " ".join(user.strip().split()) if isinstance(user, str) else ""
    return value.lower() if "@" in value else value or None
