from fastapi import APIRouter
from .service import consultar_dni_service

router = APIRouter(prefix="/reniec", tags=["Reniec"])

@router.get("/{dni}")
def consultar_dni(dni: str):
    return consultar_dni_service(dni)