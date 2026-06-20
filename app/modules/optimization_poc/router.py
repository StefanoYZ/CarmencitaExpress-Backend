from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission, require_role
from app.modules.optimization_poc.repository import list_registered_packages, list_trucks
from app.modules.optimization_poc.schema import (
    Package,
    RunRequest,
    ScenarioResponse,
    SimulationResponse,
    Truck,
)
from app.modules.optimization_poc.service import (
    get_scenario,
    run_best_fit_decreasing,
)


router = APIRouter(
    prefix="/optimization/poc",
    tags=["Optimization PoC"],
    dependencies=[Depends(require_role("ESTIBA"))],
)

@router.get("/packages", response_model=list[Package])
def get_packages(
    limit: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("optimization.read")),
) -> list[Package]:
    return list_registered_packages(db, limit=limit)


@router.get("/trucks", response_model=list[Truck])
def get_trucks(
    _current_user=Depends(require_permission("optimization.read")),
) -> list[Truck]:
    return list_trucks()


@router.get("/scenario", response_model=ScenarioResponse)
def get_poc_scenario(
    limit: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("optimization.read")),
) -> ScenarioResponse:
    return get_scenario(limit=limit, db=db)


@router.post("/first-fit/run", response_model=SimulationResponse)
def run_first_fit_endpoint(
    payload: RunRequest,
    _current_user=Depends(require_permission("optimization.run")),
) -> SimulationResponse:
    return _disabled_algorithm()


@router.post("/minimax-maximin/run", response_model=SimulationResponse)
def run_minimax_maximin_endpoint(
    payload: RunRequest,
    _current_user=Depends(require_permission("optimization.run")),
) -> SimulationResponse:
    return _disabled_algorithm()


@router.post("/best-fit/run", response_model=SimulationResponse)
def run_best_fit_endpoint(
    payload: RunRequest,
    _current_user=Depends(require_permission("optimization.run")),
) -> SimulationResponse:
    return _disabled_algorithm()


@router.post("/worst-fit/run", response_model=SimulationResponse)
def run_worst_fit_endpoint(
    payload: RunRequest,
    _current_user=Depends(require_permission("optimization.run")),
) -> SimulationResponse:
    return _disabled_algorithm()


@router.post("/best-fit-decreasing/run", response_model=SimulationResponse)
def run_best_fit_decreasing_endpoint(
    payload: RunRequest,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("optimization.run")),
) -> SimulationResponse:
    return run_best_fit_decreasing(payload, db=db)


@router.post("/backtracking/run", response_model=SimulationResponse)
def run_backtracking_endpoint(
    payload: RunRequest,
    _current_user=Depends(require_permission("optimization.run")),
) -> SimulationResponse:
    return _disabled_algorithm()


def _disabled_algorithm():
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Algoritmo desactivado. El modelo activo es Best Fit Decreasing 3D.",
    )
