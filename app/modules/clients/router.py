from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.clients.schema import ClientCreate, ClientResponse, ClientUpdate
from app.modules.clients.service import create_or_update_client, get_client_by_dni, list_clients, update_client


router = APIRouter(prefix="/clientes", tags=["Clientes"])


@router.get("", response_model=list[ClientResponse])
def list_clients_endpoint(db: Session = Depends(get_db)) -> list[ClientResponse]:
    return list_clients(db)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client_endpoint(payload: ClientCreate, db: Session = Depends(get_db)) -> ClientResponse:
    return create_or_update_client(db, payload)


@router.get("/{dni}", response_model=ClientResponse)
def get_client_endpoint(
    dni: str = Path(pattern=r"^\d{8}$"),
    db: Session = Depends(get_db),
) -> ClientResponse:
    client = get_client_by_dni(db, dni)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado en base local.")
    return client


@router.put("/{dni}", response_model=ClientResponse)
def update_client_endpoint(
    dni: str = Path(pattern=r"^\d{8}$"),
    payload: ClientUpdate = ...,
    db: Session = Depends(get_db),
) -> ClientResponse:
    client = update_client(db, dni, payload)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado en base local.")
    return client
