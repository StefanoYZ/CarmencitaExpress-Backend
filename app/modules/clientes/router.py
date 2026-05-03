from fastapi import APIRouter, HTTPException, status

from app.modules.clientes.schema import ClienteCreate, ClienteResponse
from app.modules.clientes.service import create_cliente, get_cliente, list_clientes


router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.post("", response_model=ClienteResponse, status_code=status.HTTP_201_CREATED)
def crear_cliente(payload: ClienteCreate) -> ClienteResponse:
    return create_cliente(payload)


@router.get("", response_model=list[ClienteResponse])
def obtener_clientes() -> list[ClienteResponse]:
    return list_clientes()


@router.get("/{cliente_id}", response_model=ClienteResponse)
def obtener_cliente(cliente_id: int) -> ClienteResponse:
    cliente = get_cliente(cliente_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    return cliente
