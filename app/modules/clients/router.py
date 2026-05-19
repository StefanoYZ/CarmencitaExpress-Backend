from fastapi import APIRouter, HTTPException, status

from app.modules.clients.schema import ClientCreate, ClientResponse
from app.modules.clients.service import create_client, get_client, list_clients


router = APIRouter(prefix="/clientes", tags=["clients"])


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client_endpoint(payload: ClientCreate) -> ClientResponse:
    return create_client(payload)


@router.get("", response_model=list[ClientResponse])
def list_clients_endpoint() -> list[ClientResponse]:
    return list_clients()


@router.get("/{cliente_id}", response_model=ClientResponse)
def get_client_endpoint(cliente_id: int) -> ClientResponse:
    client = get_client(cliente_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client
