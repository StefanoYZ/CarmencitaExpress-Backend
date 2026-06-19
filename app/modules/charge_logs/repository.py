from datetime import datetime

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.modules.charge_logs.model import ChargeLog


def get_next_observation_number(db: Session) -> int:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("LOCK TABLE logs_de_cobro IN EXCLUSIVE MODE"))
    current_max = db.query(func.max(ChargeLog.observation_number)).scalar() or 0
    return int(current_max) + 1


def create_charge_log(
    db: Session,
    *,
    started_at: datetime,
    finished_at: datetime,
    user: str | None,
    response_time_ms: int,
    result: str,
    modality: str,
) -> ChargeLog:
    charge_log = ChargeLog(
        observation_number=get_next_observation_number(db),
        started_at=started_at,
        finished_at=finished_at,
        user=user,
        response_time_ms=response_time_ms,
        result=result,
        modality=modality,
    )
    db.add(charge_log)
    db.commit()
    db.refresh(charge_log)
    return charge_log


def list_charge_logs(db: Session, limit: int = 100) -> list[ChargeLog]:
    return (
        db.query(ChargeLog)
        .order_by(ChargeLog.created_at.desc(), ChargeLog.id.desc())
        .limit(limit)
        .all()
    )
