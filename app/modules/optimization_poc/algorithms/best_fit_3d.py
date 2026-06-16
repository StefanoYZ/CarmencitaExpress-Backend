from app.modules.optimization_poc.models import Package3D, Truck3D, package_sort_key, truck_volume
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.utils.constants import BEST_FIT_3D
from app.modules.optimization_poc.utils.geometry import projected_bounding_volume, route_alignment_penalty, support_ratio, valid_candidates


def order_packages(packages: list[Package3D]) -> list[Package3D]:
    return sorted(packages, key=lambda package: package_sort_key(package, BEST_FIT_3D))


def find_placement(
    package: Package3D,
    truck: Truck3D,
    placed: list[Placement],
    sequence: int,
    allow_rotation: bool,
) -> Placement | None:
    candidates = valid_candidates(package, truck, placed, sequence, allow_rotation)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: _score(candidate, truck, placed))


def _score(candidate: Placement, truck: Truck3D, placed: list[Placement]) -> tuple[float, float, float, float, float]:
    projected_volume = projected_bounding_volume(candidate, placed)
    total_truck_volume = max(truck_volume(truck), 1.0)
    x_waste = (truck.ancho_cm - (candidate.x + candidate.width)) / max(truck.ancho_cm, 1.0)
    y_waste = (truck.alto_cm - (candidate.y + candidate.height)) / max(truck.alto_cm, 1.0)
    z_waste = (truck.largo_cm - (candidate.z + candidate.depth)) / max(truck.largo_cm, 1.0)
    support_penalty = 1.0 - support_ratio(candidate, placed)
    route_penalty = route_alignment_penalty(candidate, truck)
    return (
        round(projected_volume / total_truck_volume, 6),
        round(x_waste + y_waste + z_waste, 6),
        round(support_penalty, 6),
        round(route_penalty, 6),
        round(candidate.y / max(truck.alto_cm, 1.0), 6),
    )
