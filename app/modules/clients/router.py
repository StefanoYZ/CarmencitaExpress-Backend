from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.agencies.service import is_global_admin
from app.modules.clients.schema import ClientCreate, ClientResponse, ClientUpdate
from app.modules.clients.service import (
    create_or_update_client,
    get_client_by_dni,
    get_client_by_dni_for_agency,
    list_clients,
    list_clients_for_agency,
    update_client,
)
from app.modules.users.model import InternalUser


router = APIRouter(prefix="/clientes", tags=["Clientes"])


@router.get("", response_model=list[ClientResponse])
def list_clients_endpoint(
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> list[ClientResponse]:
    if is_global_admin(current_user):
        return list_clients(db)
    return list_clients_for_agency(db, current_user.agency_id)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client_endpoint(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.write")),
) -> ClientResponse:
    if not is_global_admin(current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado en base local.")
    return create_or_update_client(db, payload)


@router.get("/{dni}", response_model=ClientResponse)
def get_client_endpoint(
    dni: str = Path(pattern=r"^\d{8}$"),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> ClientResponse:
    client = (
        get_client_by_dni(db, dni)
        if is_global_admin(current_user)
        else get_client_by_dni_for_agency(db, dni, current_user.agency_id)
    )
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado en base local.")
    return client


@router.put("/{dni}", response_model=ClientResponse)
def update_client_endpoint(
    dni: str = Path(pattern=r"^\d{8}$"),
    payload: ClientUpdate = ...,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.update")),
) -> ClientResponse:
    if not is_global_admin(current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado en base local.")
    client = update_client(db, dni, payload)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado en base local.")
    return client
