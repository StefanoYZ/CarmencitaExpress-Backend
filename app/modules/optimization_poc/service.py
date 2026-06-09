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


def run_first_fit(request: RunRequest) -> SimulationResponse:
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
        placement = _find_first_fit(package=package, truck=truck, placed=placements, sequence=len(placements) + 1, allow_rotation=request.allow_rotation)
        if placement:
            placements.append(placement)
            total_weight += package.peso_kg
        else:
            unplaced.append(package)
    execution_ms = max(1, round((perf_counter() - started) * 1000))
    metrics = calculate_metrics(truck=truck, ordered_packages=packages, placements=placements, unplaced_packages=unplaced, execution_ms=execution_ms)
    return SimulationResponse(simulation_id=f"poc-{uuid4().hex[:8]}", algorithm="FIRST_FIT_3D", strategy=None, truck=truck, input_count=len(packages), ordered_packages=packages, placements=placements, unplaced_packages=unplaced, metrics=metrics)


def _find_first_fit(*, package: Package, truck: Truck, placed: list[Placement], sequence: int, allow_rotation: bool) -> Placement | None:
    for x, y, z in _candidate_points(placed):
        for width, height, depth, orientation in _orientations(package, allow_rotation):
            candidate = Placement(package_id=package.id, codigo=package.codigo, loading_sequence=sequence, delivery_order=package.orden_entrega, x=x, y=y, z=z, width=width, height=height, depth=depth, orientation=orientation, destination=package.destino, fragility=package.fragilidad, peso_kg=package.peso_kg, descripcion=package.descripcion)
            if _is_valid(candidate, truck, placed):
                return candidate
    return None


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
