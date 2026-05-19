from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.shipments.schema import ShipmentCreate, ShipmentDeleteResponse, ShipmentResponse, ShipmentUpdate
from app.modules.shipments.service import (
    cancel_shipment,
    create_shipment,
    get_shipment,
    get_shipment_by_code,
    list_shipments,
    update_shipment,
)


router = APIRouter(prefix="/encomiendas", tags=["shipments"])


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_shipment_endpoint(payload: ShipmentCreate, db: Session = Depends(get_db)) -> ShipmentResponse:
    return create_shipment(db, payload)


@router.get("", response_model=list[ShipmentResponse])
def list_shipments_endpoint(db: Session = Depends(get_db)) -> list[ShipmentResponse]:
    return list_shipments(db)


@router.get("/codigo/{codigo_encomienda}", response_model=ShipmentResponse)
def get_shipment_by_code_endpoint(codigo_encomienda: str, db: Session = Depends(get_db)) -> ShipmentResponse:
    shipment = get_shipment_by_code(db, codigo_encomienda)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.get("/{encomienda_id}", response_model=ShipmentResponse)
def get_shipment_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> ShipmentResponse:
    shipment = get_shipment(db, encomienda_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.put("/{encomienda_id}", response_model=ShipmentResponse)
def update_shipment_endpoint(
    encomienda_id: int,
    payload: ShipmentUpdate,
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    shipment = update_shipment(db, encomienda_id, payload)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.delete("/{encomienda_id}", response_model=ShipmentDeleteResponse)
def cancel_shipment_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> ShipmentDeleteResponse:
    shipment = cancel_shipment(db, encomienda_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return ShipmentDeleteResponse(
        success=True,
        message="Encomienda anulada correctamente",
        id=shipment.id,
        codigo_encomienda=shipment.shipment_code,
        estado=shipment.status,
    )
