from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.destinations.schema import (
    DestinationCreate,
    DestinationResponse,
    DestinationUpdate,
)
from app.modules.destinations.service import (
    create_destination,
    list_destinations,
    update_destination,
)

router = APIRouter(prefix="/destinos", tags=["Destinos"])


@router.get("", response_model=list[DestinationResponse])
def list_destinations_endpoint(
    include_inactive: bool = Query(default=False, alias="incluir_inactivos"),
    db: Session = Depends(get_db),
) -> list[DestinationResponse]:
    return list_destinations(db, include_inactive=include_inactive)


@router.post(
    "",
    response_model=DestinationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_destination_endpoint(
    payload: DestinationCreate,
    db: Session = Depends(get_db),
) -> DestinationResponse:
    try:
        return create_destination(db, payload)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.put("/{destination_id}", response_model=DestinationResponse)
def update_destination_endpoint(
    destination_id: int,
    payload: DestinationUpdate,
    db: Session = Depends(get_db),
) -> DestinationResponse:
    try:
        destination = update_destination(db, destination_id, payload)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    if destination is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destino no encontrado.",
        )
    return destination
