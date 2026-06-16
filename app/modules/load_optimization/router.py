from fastapi import APIRouter

from app.modules.load_optimization.schemas import (
    OptimizationRequest
)

from app.modules.load_optimization.service import (
    LoadOptimizationService
)

router = APIRouter(
    prefix="/load-optimization",
    tags=["Load Optimization"]
)

# Memoria temporal para pruebas
saved_sample: OptimizationRequest | None = None


@router.post("/simulate")
def simulate(request: OptimizationRequest):
    return LoadOptimizationService.optimize(request)


@router.post("/compare")
def compare(request: OptimizationRequest):
    return LoadOptimizationService.compare(request)


@router.post("/save-sample")
def save_sample(request: OptimizationRequest):
    global saved_sample

    saved_sample = request

    return {
        "message": "Escenario guardado correctamente"
    }


@router.get("/sample")
def get_sample():
    if saved_sample is None:
        return {
            "message": "No hay escenario guardado",
            "data": None
        }

    return {
        "message": "Escenario encontrado",
        "data": saved_sample.model_dump()
    }