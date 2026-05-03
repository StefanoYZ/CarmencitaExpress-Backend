from fastapi import APIRouter, HTTPException, status

from app.modules.encomiendas.schema import EncomiendaCreate, EncomiendaResponse
from app.modules.encomiendas.service import (
    create_encomienda,
    get_encomienda,
    get_encomienda_by_codigo,
    list_encomiendas,
)


router = APIRouter(prefix="/encomiendas", tags=["encomiendas"])


@router.post("", response_model=EncomiendaResponse, status_code=status.HTTP_201_CREATED)
def crear_encomienda(payload: EncomiendaCreate) -> EncomiendaResponse:
    return create_encomienda(payload)


@router.get("", response_model=list[EncomiendaResponse])
def obtener_encomiendas() -> list[EncomiendaResponse]:
    return list_encomiendas()


@router.get("/codigo/{codigo_encomienda}", response_model=EncomiendaResponse)
def obtener_encomienda_por_codigo(codigo_encomienda: str) -> EncomiendaResponse:
    encomienda = get_encomienda_by_codigo(codigo_encomienda)
    if encomienda is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return encomienda


@router.get("/{encomienda_id}", response_model=EncomiendaResponse)
def obtener_encomienda(encomienda_id: int) -> EncomiendaResponse:
    encomienda = get_encomienda(encomienda_id)
    if encomienda is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return encomienda
