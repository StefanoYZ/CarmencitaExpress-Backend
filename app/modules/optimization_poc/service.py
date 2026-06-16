from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException, status

from app.modules.optimization_poc.algorithms import (
    BACKTRACKING_LOGISTIC,
    BEST_FIT_3D,
    BEST_FIT_DECREASING_3D,
    FIRST_FIT_3D,
    MAXIMIN,
    MINIMAX,
    MINIMAX_MAXIMIN_3D,
    WORST_FIT,
    get_packing_algorithm,
)
from app.modules.optimization_poc.algorithms.backtracking_3d import backtracking_3d_algorithm
from app.modules.optimization_poc.algorithms.best_fit_decreasing_3d import best_fit_decreasing_3d_algorithm
from app.modules.optimization_poc.algorithms.worst_fit import worst_fit_algorithm
from app.modules.optimization_poc.models import Package3D, Truck3D
from app.modules.optimization_poc.repository import get_truck, list_packages, list_trucks
from app.modules.optimization_poc.schema import Package, Placement, RunRequest, ScenarioResponse, SimulationResponse
from app.modules.optimization_poc.utils.metrics import calculate_metrics
from app.modules.optimization_poc.validators import is_weight_allowed


def get_scenario(limit: int = 50) -> ScenarioResponse:
    return ScenarioResponse(
        packages=list_packages(limit=limit, shuffled=True),
        trucks=list_trucks(),
        coordinate_system={
            "x": "ancho del camion",
            "y": "altura del camion",
            "z": "largo o profundidad del camion",
            "origin": "(0,0,0) esquina inferior izquierda cercana a la puerta de carga",
            "door": "Z = 0",
        },
    )


def ordered_packages(limit: int = 50, strategy: str = FIRST_FIT_3D) -> list[Package]:
    packages = build_packages(list_packages(limit=limit, shuffled=False))
    return [package.to_schema() for package in get_packing_algorithm(strategy).order_packages(packages)]


def run_first_fit(request: RunRequest) -> SimulationResponse:
    return _run_simulation(request, algorithm=FIRST_FIT_3D, strategy_id=FIRST_FIT_3D, strategy=None)


def run_best_fit(request: RunRequest) -> SimulationResponse:
    return _run_simulation(request, algorithm=BEST_FIT_3D, strategy_id=BEST_FIT_3D, strategy=None)


def run_worst_fit(request: RunRequest) -> SimulationResponse:
    return _run_logistic_simulation(request, algorithm=WORST_FIT, runner=worst_fit_algorithm)


def run_best_fit_decreasing(request: RunRequest) -> SimulationResponse:
    return _run_logistic_simulation(
        request,
        algorithm=BEST_FIT_DECREASING_3D,
        runner=best_fit_decreasing_3d_algorithm,
    )


def run_backtracking_logistic(request: RunRequest) -> SimulationResponse:
    return _run_logistic_simulation(
        request,
        algorithm=BACKTRACKING_LOGISTIC,
        runner=backtracking_3d_algorithm,
    )


def run_minimax_maximin(request: RunRequest) -> SimulationResponse:
    strategy = (request.strategy or MINIMAX).upper()
    if strategy not in {MINIMAX, MAXIMIN}:
        strategy = MINIMAX
    return _run_simulation(request, algorithm=MINIMAX_MAXIMIN_3D, strategy_id=strategy, strategy=strategy)


def _run_simulation(
    request: RunRequest,
    *,
    algorithm: str,
    strategy_id: str,
    strategy: str | None,
) -> SimulationResponse:
    truck_schema = get_truck(request.truck_id)
    if not truck_schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camion no encontrado para la PoC.")

    truck = build_truck(truck_schema)
    packing_algorithm = get_packing_algorithm(strategy_id)
    packages = packing_algorithm.order_packages(build_packages(list_packages(limit=request.package_limit, shuffled=False)))
    placements: list[Placement] = []
    unplaced: list[Package3D] = []
    total_weight = 0.0
    started = perf_counter()

    for package in packages:
        if not is_weight_allowed(total_weight, package.peso_kg, truck):
            unplaced.append(package)
            continue

        placement = packing_algorithm.find_placement(
            package,
            truck,
            placements,
            len(placements) + 1,
            request.allow_rotation,
        )
        if placement:
            placements.append(placement)
            total_weight += package.peso_kg
        else:
            unplaced.append(package)

    execution_ms = max(1, round((perf_counter() - started) * 1000))
    metrics = calculate_metrics(
        truck=truck,
        ordered_packages=packages,
        placements=placements,
        unplaced_packages=unplaced,
        execution_ms=execution_ms,
    )
    return SimulationResponse(
        simulation_id=f"poc-{uuid4().hex[:8]}",
        algorithm=algorithm,
        strategy=strategy,
        truck=truck.to_schema(),
        input_count=len(packages),
        ordered_packages=[package.to_schema() for package in packages],
        placements=placements,
        unplaced_packages=[package.to_schema() for package in unplaced],
        metrics=metrics,
    )


def build_truck(truck) -> Truck3D:
    return truck if isinstance(truck, Truck3D) else Truck3D.from_schema(truck)


def build_packages(packages: list[Package]) -> list[Package3D]:
    return [package if isinstance(package, Package3D) else Package3D.from_schema(package) for package in packages]


def _run_logistic_simulation(
    request: RunRequest,
    *,
    algorithm: str,
    runner,
) -> SimulationResponse:
    truck_schema = get_truck(request.truck_id)
    if not truck_schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camion no encontrado para la PoC.")

    truck = build_truck(truck_schema)
    packages = build_packages(list_packages(limit=request.package_limit, shuffled=False))
    result = runner(
        truck,
        packages,
        route=request.route,
        origin_agency=request.origin_agency,
    )

    ordered_packages = result.get("ordered_packages") or packages
    package_by_id = {package.id: package for package in ordered_packages}
    placements: list[Placement] = []

    for sequence, item in enumerate(result.get("placed_packages", []), start=1):
        package = package_by_id[item["id"]]
        placements.append(
            Placement(
                package_id=package.id,
                codigo=package.codigo,
                loading_sequence=sequence,
                delivery_order=package.orden_entrega,
                x=item["x"],
                y=item["y"],
                z=item["z"],
                width=item["width"],
                height=item["height"],
                depth=item["length"],
                orientation="ROT" if item.get("rotated") else "LWH",
                destination=package.destino,
                fragility=package.fragilidad,
                peso_kg=package.peso_kg,
                descripcion=package.descripcion,
            )
        )

    placed_ids = {item["id"] for item in result.get("placed_packages", [])}
    unplaced_ids = [item["id"] for item in result.get("unplaced_packages", []) if item["id"] in package_by_id]
    unplaced_packages = [package_by_id[item_id] for item_id in unplaced_ids]

    if len(unplaced_packages) + len(placements) < len(ordered_packages):
        known_ids = placed_ids | set(unplaced_ids)
        unplaced_packages.extend(package for package in ordered_packages if package.id not in known_ids)

    metrics = calculate_metrics(
        truck=truck,
        ordered_packages=ordered_packages,
        placements=placements,
        unplaced_packages=unplaced_packages,
        execution_ms=max(1, round(float(result.get("execution_time_ms", 1)))),
    )

    return SimulationResponse(
        simulation_id=f"poc-{uuid4().hex[:8]}",
        algorithm=algorithm,
        strategy=None,
        truck=truck.to_schema(),
        input_count=len(ordered_packages),
        ordered_packages=[package.to_schema() for package in ordered_packages],
        placements=placements,
        unplaced_packages=[package.to_schema() for package in unplaced_packages],
        metrics=metrics,
    )
