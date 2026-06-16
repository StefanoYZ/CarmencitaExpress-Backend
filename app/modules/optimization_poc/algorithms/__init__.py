from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, status

from app.modules.optimization_poc.models import Package3D, Truck3D
from app.modules.optimization_poc.schema import Placement, RunRequest, SimulationResponse
from app.modules.optimization_poc.utils.constants import (
    BACKTRACKING_LOGISTIC,
    BEST_FIT_3D,
    BEST_FIT_DECREASING_3D,
    FIRST_FIT_3D,
    MAXIMIN,
    MINIMAX,
    MINIMAX_MAXIMIN_3D,
    WORST_FIT,
)

AlgorithmRunner = Callable[[RunRequest], SimulationResponse]
PackageOrdering = Callable[[list[Package3D]], list[Package3D]]
PlacementFinder = Callable[[Package3D, Truck3D, list[Placement], int, bool], Placement | None]


@dataclass(frozen=True)
class PackingAlgorithm:
    id: str
    label: str
    order_packages: PackageOrdering
    find_placement: PlacementFinder


def normalize_algorithm_id(algorithm_id: str) -> str:
    return (algorithm_id or "").strip().upper().replace("-", "_")


def run_algorithm(
    algorithm_id: str,
    payload: RunRequest,
    runners: dict[str, AlgorithmRunner],
) -> SimulationResponse:
    normalized_id = normalize_algorithm_id(algorithm_id)
    runner = runners.get(normalized_id)
    if not runner:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Algoritmo no implementado en esta rama: {algorithm_id}",
        )
    return runner(payload)


from app.modules.optimization_poc.algorithms.best_fit_3d import find_placement as find_best_fit_placement
from app.modules.optimization_poc.algorithms.best_fit_3d import order_packages as order_best_fit_packages
from app.modules.optimization_poc.algorithms.first_fit_3d import find_placement as find_first_fit_placement
from app.modules.optimization_poc.algorithms.first_fit_3d import order_packages as order_first_fit_packages
from app.modules.optimization_poc.algorithms.maximin_3d import find_placement as find_maximin_placement
from app.modules.optimization_poc.algorithms.maximin_3d import order_packages as order_maximin_packages
from app.modules.optimization_poc.algorithms.minimax_3d import find_placement as find_minimax_placement
from app.modules.optimization_poc.algorithms.minimax_3d import order_packages as order_minimax_packages

PACKING_ALGORITHMS = {
    FIRST_FIT_3D: PackingAlgorithm(
        id=FIRST_FIT_3D,
        label="First Fit 3D",
        order_packages=order_first_fit_packages,
        find_placement=find_first_fit_placement,
    ),
    BEST_FIT_3D: PackingAlgorithm(
        id=BEST_FIT_3D,
        label="Best Fit 3D",
        order_packages=order_best_fit_packages,
        find_placement=find_best_fit_placement,
    ),
    MINIMAX: PackingAlgorithm(
        id=MINIMAX,
        label="Minimax",
        order_packages=order_minimax_packages,
        find_placement=find_minimax_placement,
    ),
    MAXIMIN: PackingAlgorithm(
        id=MAXIMIN,
        label="Maximin",
        order_packages=order_maximin_packages,
        find_placement=find_maximin_placement,
    ),
}


def get_packing_algorithm(strategy_id: str) -> PackingAlgorithm:
    normalized_id = normalize_algorithm_id(strategy_id)
    algorithm = PACKING_ALGORITHMS.get(normalized_id)
    if not algorithm:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Estrategia no implementada en la PoC: {strategy_id}",
        )
    return algorithm


__all__ = [
    "AlgorithmRunner",
    "BACKTRACKING_LOGISTIC",
    "BEST_FIT_3D",
    "BEST_FIT_DECREASING_3D",
    "FIRST_FIT_3D",
    "MAXIMIN",
    "MINIMAX",
    "MINIMAX_MAXIMIN_3D",
    "PACKING_ALGORITHMS",
    "PackingAlgorithm",
    "WORST_FIT",
    "get_packing_algorithm",
    "normalize_algorithm_id",
    "run_algorithm",
]
