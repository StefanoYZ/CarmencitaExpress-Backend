from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.agencies.service import get_scoped_shipment
from app.modules.quotes.schema import QuoteRequest, QuoteResponse
from app.modules.quotes.service import calculate_quote
from app.modules.users.model import InternalUser


router = APIRouter(prefix="/cotizaciones", tags=["quotes"])


@router.post("/calcular", response_model=QuoteResponse)
def calculate_quote_endpoint(
    payload: QuoteRequest,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("cotizaciones.calculate")),
) -> QuoteResponse:
    if get_scoped_shipment(db, payload.shipment_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        quote = calculate_quote(db, payload.shipment_id, actor_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return quote
