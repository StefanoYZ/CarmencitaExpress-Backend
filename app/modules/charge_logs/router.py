from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.charge_logs.schema import ChargeLogResponse
from app.modules.charge_logs.service import list_charge_logs


router = APIRouter(prefix="/logs-cobro", tags=["Logs de cobro"])


@router.get("", response_model=list[ChargeLogResponse])
def list_charge_logs_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.read")),
) -> list[ChargeLogResponse]:
    return list_charge_logs(db, limit)
