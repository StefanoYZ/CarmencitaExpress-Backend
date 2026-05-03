from fastapi import APIRouter, HTTPException, status

from app.modules.cotizacion.schema import CotizacionRequest, CotizacionResponse
from app.modules.cotizacion.service import calcular_cotizacion


router = APIRouter(prefix="/cotizaciones", tags=["cotizaciones"])


@router.post("/calcular", response_model=CotizacionResponse)
def calcular(payload: CotizacionRequest) -> CotizacionResponse:
    cotizacion = calcular_cotizacion(payload.encomienda_id)
    if cotizacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return cotizacion
