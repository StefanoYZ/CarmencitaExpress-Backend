from fastapi import APIRouter, Query

from app.modules.optimization_poc.algorithms import FIRST_FIT_3D, run_algorithm
from app.modules.optimization_poc.repository import list_packages, list_trucks
from app.modules.optimization_poc.schema import Package, RunRequest, ScenarioResponse, SimulationResponse, Truck
from app.modules.optimization_poc.service import get_scenario, run_first_fit

router = APIRouter(prefix="/optimization/poc", tags=["Optimization PoC"])

ALGORITHM_RUNNERS = {
    FIRST_FIT_3D: run_first_fit,
}


@router.get("/packages", response_model=list[Package])
def get_packages(limit: int = Query(default=50, ge=1, le=50)) -> list[Package]:
    return list_packages(limit=limit, shuffled=True)


@router.get("/trucks", response_model=list[Truck])
def get_trucks() -> list[Truck]:
    return list_trucks()


@router.get("/scenario", response_model=ScenarioResponse)
def get_poc_scenario(limit: int = Query(default=50, ge=1, le=50)) -> ScenarioResponse:
    return get_scenario(limit=limit)


@router.post("/first-fit/run", response_model=SimulationResponse)
def run_first_fit_endpoint(payload: RunRequest) -> SimulationResponse:
    return run_algorithm(FIRST_FIT_3D, payload, ALGORITHM_RUNNERS)
