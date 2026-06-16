from fastapi import APIRouter, Query

from app.modules.optimization_poc.algorithms import (
    BACKTRACKING_LOGISTIC,
    BEST_FIT_3D,
    BEST_FIT_DECREASING_3D,
    FIRST_FIT_3D,
    MINIMAX_MAXIMIN_3D,
    WORST_FIT,
    run_algorithm,
)
from app.modules.optimization_poc.repository import list_packages, list_trucks
from app.modules.optimization_poc.schema import Package, RunRequest, ScenarioResponse, SimulationResponse, Truck
from app.modules.optimization_poc.service import (
    get_scenario,
    run_backtracking_logistic,
    run_best_fit,
    run_best_fit_decreasing,
    run_first_fit,
    run_minimax_maximin,
    run_worst_fit,
)

router = APIRouter(prefix="/optimization/poc", tags=["Optimization PoC"])

ALGORITHM_RUNNERS = {
    FIRST_FIT_3D: run_first_fit,
    MINIMAX_MAXIMIN_3D: run_minimax_maximin,
    BEST_FIT_3D: run_best_fit,
    WORST_FIT: run_worst_fit,
    BEST_FIT_DECREASING_3D: run_best_fit_decreasing,
    BACKTRACKING_LOGISTIC: run_backtracking_logistic,
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


@router.post("/minimax-maximin/run", response_model=SimulationResponse)
def run_minimax_maximin_endpoint(payload: RunRequest) -> SimulationResponse:
    return run_algorithm(MINIMAX_MAXIMIN_3D, payload, ALGORITHM_RUNNERS)


@router.post("/best-fit/run", response_model=SimulationResponse)
def run_best_fit_endpoint(payload: RunRequest) -> SimulationResponse:
    return run_algorithm(BEST_FIT_3D, payload, ALGORITHM_RUNNERS)


@router.post("/worst-fit/run", response_model=SimulationResponse)
def run_worst_fit_endpoint(payload: RunRequest) -> SimulationResponse:
    return run_algorithm(WORST_FIT, payload, ALGORITHM_RUNNERS)


@router.post("/best-fit-decreasing/run", response_model=SimulationResponse)
def run_best_fit_decreasing_endpoint(payload: RunRequest) -> SimulationResponse:
    return run_algorithm(BEST_FIT_DECREASING_3D, payload, ALGORITHM_RUNNERS)


@router.post("/backtracking/run", response_model=SimulationResponse)
def run_backtracking_endpoint(payload: RunRequest) -> SimulationResponse:
    return run_algorithm(BACKTRACKING_LOGISTIC, payload, ALGORITHM_RUNNERS)
