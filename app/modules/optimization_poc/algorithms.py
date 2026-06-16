from typing import Callable

from fastapi import HTTPException, status

from app.modules.optimization_poc.schema import RunRequest, SimulationResponse

AlgorithmRunner = Callable[[RunRequest], SimulationResponse]

FIRST_FIT_3D = "FIRST_FIT_3D"
MINIMAX_MAXIMIN_3D = "MINIMAX_MAXIMIN_3D"


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
