from itertools import permutations
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException, status

from app.modules.optimization_poc.metrics import calculate_metrics
from app.modules.optimization_poc.repository import get_truck, list_packages, list_trucks
from app.modules.optimization_poc.schema import Package, Placement, RunRequest, ScenarioResponse, SimulationResponse, Truck
from app.modules.optimization_poc.validators import has_minimum_support, has_overlap, is_inside_truck, is_weight_allowed, respects_fragility

FRAGILITY_ORDER = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}


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


def ordered_packages(limit: int = 50) -> list[Package]:
    packages = list_packages(limit=limit, shuffled=True)
    return sorted(packages, key=lambda item: (item.orden_entrega, item.prioridad, FRAGILITY_ORDER.get(item.fragilidad, 9), -(item.largo_cm * item.ancho_cm * item.alto_cm), item.codigo))



def run_minimax_maximin(request: RunRequest) -> SimulationResponse:
    return _run_packing(request=request, algorithm="MINIMAX_MAXIMIN_3D", strategy=request.strategy)


def _run_packing(request: RunRequest, algorithm: str, strategy: str | None) -> SimulationResponse:
    truck = get_truck(request.truck_id)
    if not truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camion no encontrado para la PoC.")
    packages = ordered_packages(limit=request.package_limit)
    placements: list[Placement] = []
    unplaced: list[Package] = []
    total_weight = 0.0
    started = perf_counter()
    for package in packages:
        if not is_weight_allowed(total_weight, package.peso_kg, truck):
            unplaced.append(package)
            continue
        placement = _find_placement(package=package, truck=truck, placed=placements, sequence=len(placements) + 1, allow_rotation=request.allow_rotation, algorithm=algorithm, strategy=strategy)
        if placement:
            placements.append(placement)
            total_weight += package.peso_kg
        else:
            unplaced.append(package)
    execution_ms = max(1, round((perf_counter() - started) * 1000))
    metrics = calculate_metrics(truck=truck, ordered_packages=packages, placements=placements, unplaced_packages=unplaced, execution_ms=execution_ms)
    return SimulationResponse(simulation_id=f"poc-{uuid4().hex[:8]}", algorithm=algorithm, strategy=strategy, truck=truck, input_count=len(packages), ordered_packages=packages, placements=placements, unplaced_packages=unplaced, metrics=metrics)


def _find_placement(*, package: Package, truck: Truck, placed: list[Placement], sequence: int, allow_rotation: bool, algorithm: str, strategy: str | None) -> Placement | None:
    valid: list[Placement] = []
    for x, y, z in _candidate_points(placed):
        for width, height, depth, orientation in _orientations(package, allow_rotation):
            candidate = Placement(package_id=package.id, codigo=package.codigo, loading_sequence=sequence, delivery_order=package.orden_entrega, x=x, y=y, z=z, width=width, height=height, depth=depth, orientation=orientation, destination=package.destino, fragility=package.fragilidad, peso_kg=package.peso_kg, descripcion=package.descripcion)
            if not _is_valid(candidate, truck, placed):
                continue
            valid.append(candidate)
    if not valid:
        return None
    if strategy == "MAXIMIN":
        return max(valid, key=lambda candidate: _maximin_score(candidate, truck, placed))
    return min(valid, key=lambda candidate: _minimax_penalty(candidate, truck, placed))


def _candidate_points(placed: list[Placement]) -> list[tuple[float, float, float]]:
    points = {(0.0, 0.0, 0.0)}
    for item in placed:
        points.add((item.x + item.width, item.y, item.z))
        points.add((item.x, item.y + item.height, item.z))
        points.add((item.x, item.y, item.z + item.depth))
    return sorted(points, key=lambda point: (point[2], point[1], point[0]))


def _orientations(package: Package, allow_rotation: bool) -> list[tuple[float, float, float, str]]:
    base = (package.ancho_cm, package.alto_cm, package.largo_cm)
    if not allow_rotation or not package.permite_rotacion:
        return [(base[0], base[1], base[2], "LWH")]
    orientations: list[tuple[float, float, float, str]] = []
    seen = set()
    labels = ["WHD", "WDH", "HWD", "HDW", "DWH", "DHW"]
    for index, dims in enumerate(permutations(base, 3)):
        if dims in seen:
            continue
        seen.add(dims)
        orientations.append((dims[0], dims[1], dims[2], labels[min(index, len(labels) - 1)]))
    return orientations


def _is_valid(candidate: Placement, truck: Truck, placed: list[Placement]) -> bool:
    return is_inside_truck(candidate.x, candidate.y, candidate.z, candidate.width, candidate.height, candidate.depth, truck) and not has_overlap(candidate, placed) and has_minimum_support(candidate, placed) and respects_fragility(candidate, placed)


def _minimax_penalty(candidate: Placement, truck: Truck, placed: list[Placement]) -> tuple[float, float, float, float]:
    space_waste = (candidate.x + candidate.width) / truck.ancho_cm
    height_penalty = (candidate.y + candidate.height) / truck.alto_cm
    door_penalty = candidate.z / truck.largo_cm
    support_penalty = 0.0 if has_minimum_support(candidate, placed) else 1.0
    worst = max(space_waste, height_penalty, door_penalty, support_penalty)
    return (worst, door_penalty, height_penalty, candidate.x)


def _maximin_score(candidate: Placement, truck: Truck, placed: list[Placement]) -> tuple[float, float, float]:
    support = 1.0 if has_minimum_support(candidate, placed) else 0.0
    compactness = 1.0 - ((candidate.x + candidate.width) / truck.ancho_cm * 0.35 + (candidate.z + candidate.depth) / truck.largo_cm * 0.65)
    accessibility = 1.0 - (candidate.z / truck.largo_cm)
    stability = 1.0 - (candidate.y / truck.alto_cm)
    return (min(support, compactness, accessibility, stability), accessibility, compactness)
