from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

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
from app.modules.optimization_poc.repository import (
    get_truck,
    list_packages,
    list_packages_by_codes,
    list_registered_packages,
    list_registered_packages_by_codes,
    list_trucks,
)
from app.modules.optimization_poc.schema import Package, Placement, RunRequest, ScenarioResponse, SimulationResponse
from app.modules.optimization_poc.utils.metrics import calculate_metrics
from app.modules.optimization_poc.utils.progressive_loading import select_progressive_placement
from app.modules.optimization_poc.validators import is_weight_allowed, recompute_supported_weights


def get_scenario(limit: int | None = None, db: Session | None = None) -> ScenarioResponse:
    return ScenarioResponse(
        packages=_source_packages(limit=limit, db=db),
        trucks=list_trucks(),
        coordinate_system={
            "x": "ancho del camion",
            "y": "altura del camion",
            "z": "largo o profundidad del camion",
            "origin": "(0,0,0) esquina inferior izquierda del fondo de la bodega, junto a la cabina",
            "front": "Z = 0 es el fondo del camion junto a la cabina",
            "door": "Z = largo_cm es la puerta de carga",
        },
    )


def ordered_packages(
    limit: int | None = None,
    strategy: str = FIRST_FIT_3D,
    db: Session | None = None,
) -> list[Package]:
    packages = build_packages(
        [package for package in _source_packages(limit=limit, db=db) if package.requires_packing]
    )
    return [package.to_schema() for package in get_packing_algorithm(strategy).order_packages(packages)]


def run_first_fit(request: RunRequest, db: Session | None = None) -> SimulationResponse:
    return _run_simulation(request, algorithm=FIRST_FIT_3D, strategy_id=FIRST_FIT_3D, strategy=None, db=db)


def run_best_fit(request: RunRequest, db: Session | None = None) -> SimulationResponse:
    return _run_simulation(request, algorithm=BEST_FIT_3D, strategy_id=BEST_FIT_3D, strategy=None, db=db)


def run_worst_fit(request: RunRequest, db: Session | None = None) -> SimulationResponse:
    return _run_simulation(request, algorithm=WORST_FIT, strategy_id=WORST_FIT, strategy=None, db=db)


def run_best_fit_decreasing(request: RunRequest, db: Session | None = None) -> SimulationResponse:
    return _run_simulation(
        request,
        algorithm=BEST_FIT_DECREASING_3D,
        strategy_id=BEST_FIT_DECREASING_3D,
        strategy=None,
        db=db,
    )


def run_backtracking_logistic(request: RunRequest, db: Session | None = None) -> SimulationResponse:
    return _run_logistic_simulation(
        request,
        algorithm=BACKTRACKING_LOGISTIC,
        runner=backtracking_3d_algorithm,
        db=db,
    )


def run_minimax_maximin(request: RunRequest, db: Session | None = None) -> SimulationResponse:
    strategy = (request.strategy or MINIMAX).upper()
    if strategy not in {MINIMAX, MAXIMIN}:
        strategy = MINIMAX
    return _run_simulation(
        request,
        algorithm=MINIMAX_MAXIMIN_3D,
        strategy_id=strategy,
        strategy=strategy,
        db=db,
    )


def _run_simulation(
    request: RunRequest,
    *,
    algorithm: str,
    strategy_id: str,
    strategy: str | None,
    db: Session | None = None,
) -> SimulationResponse:
    truck_schema = get_truck(request.truck_id)
    if not truck_schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camion no encontrado para la PoC.")

    truck = build_truck(truck_schema)
    packing_algorithm = get_packing_algorithm(strategy_id)
    source_packages = packages_from_request(request, db=db)
    packages = packing_algorithm.order_packages(
        [package for package in source_packages if package.requires_packing]
    )
    pending_packages = list(enumerate(packages))
    loading_order: list[Package3D] = []
    placements: list[Placement] = []
    unplaced: list[Package3D] = []
    total_weight = 0.0
    started = perf_counter()

    while pending_packages:
        overweight = [
            item
            for item in pending_packages
            if not is_weight_allowed(total_weight, item[1].peso_kg, truck)
        ]
        if overweight:
            overweight_indexes = {index for index, _ in overweight}
            unplaced.extend(package for _, package in overweight)
            pending_packages = [
                item
                for item in pending_packages
                if item[0] not in overweight_indexes
            ]
            if not pending_packages:
                break

        selection = select_progressive_placement(
            pending_packages=pending_packages,
            find_placement=packing_algorithm.find_placement,
            truck=truck,
            placements=placements,
            allow_rotation=request.allow_rotation,
        )
        if not selection:
            unplaced.extend(package for _, package in pending_packages)
            break

        original_index, package, placement = selection
        placements.append(placement)
        loading_order.append(package)
        recompute_supported_weights(placements)
        total_weight += package.peso_kg
        pending_packages = [
            item
            for item in pending_packages
            if item[0] != original_index
        ]

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
        input_count=len(source_packages),
        ordered_packages=[package.to_schema() for package in source_packages],
        placements=placements,
        unplaced_packages=[package.to_schema() for package in unplaced],
        metrics=metrics,
    )
def build_truck(truck) -> Truck3D:
    return truck if isinstance(truck, Truck3D) else Truck3D.from_schema(truck)


def build_packages(packages: list[Package]) -> list[Package3D]:
    return [package if isinstance(package, Package3D) else Package3D.from_schema(package) for package in packages]


def packages_from_request(request: RunRequest, db: Session | None = None) -> list[Package3D]:
    if request.package_codes:
        packages = (
            list_registered_packages_by_codes(db, request.package_codes)
            if db is not None
            else list_packages_by_codes(request.package_codes)
        )
        return build_packages(packages)
    return build_packages(_source_packages(limit=request.package_limit, db=db))


def _source_packages(limit: int | None, db: Session | None) -> list[Package]:
    if db is not None:
        return list_registered_packages(db, limit=limit)
    return list_packages(limit=limit or 70, shuffled=False)


def _run_logistic_simulation(
    request: RunRequest,
    *,
    algorithm: str,
    runner,
    db: Session | None = None,
) -> SimulationResponse:
    truck_schema = get_truck(request.truck_id)
    if not truck_schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camion no encontrado para la PoC.")

    truck = build_truck(truck_schema)
    source_packages = packages_from_request(request, db=db)
    packages = [package for package in source_packages if package.requires_packing]
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
                supported_weight=float(item.get("supported_weight", 0.0)),
                stacking_capacity=float(item.get("stacking_capacity", 0.0)),
                support_ratio=float(item.get("support_ratio", 1.0)),
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
        input_count=len(source_packages),
        ordered_packages=[package.to_schema() for package in source_packages],
        placements=placements,
        unplaced_packages=[package.to_schema() for package in unplaced_packages],
        metrics=metrics,
    )
