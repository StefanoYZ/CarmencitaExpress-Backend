from fastapi import APIRouter, Body
from .service import procesar_pago_yape

router = APIRouter(prefix="/yape", tags=["Yape"])

@router.post("/process-payment")
def process_yape_payment(data: dict = Body(...)):
    return procesar_pago_yape(data)