from app.modules.optimization_poc.models import Package3D, Truck3D, package_sort_key
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.utils.constants import FIRST_FIT_3D
from app.modules.optimization_poc.utils.geometry import (
    contact_score,
    dense_valid_candidates,
    loading_flow_key,
    projected_bounding_volume,
    route_alignment_penalty,
    support_ratio,
)


def order_packages(packages: list[Package3D]) -> list[Package3D]:
    return sorted(packages, key=lambda package: package_sort_key(package, FIRST_FIT_3D))


def find_placement(
    package: Package3D,
    truck: Truck3D,
    placed: list[Placement],
    sequence: int,
    allow_rotation: bool,
) -> Placement | None:
    candidates = dense_valid_candidates(package, truck, placed, sequence, allow_rotation)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: _score(candidate, truck, placed))


def _score(candidate: Placement, truck: Truck3D, placed: list[Placement]) -> tuple[float, ...]:
    truck_volume = max(truck.ancho_cm * truck.alto_cm * truck.largo_cm, 1.0)
    projected_ratio = projected_bounding_volume(candidate, placed) / truck_volume
    top_ratio = (candidate.y + candidate.height) / max(truck.alto_cm, 1.0)
    route_penalty = route_alignment_penalty(candidate, truck)
    support_penalty = 1.0 - support_ratio(candidate, placed)
    contact_penalty = 1.0 - contact_score(candidate, truck, placed)
    x_waste = (truck.ancho_cm - (candidate.x + candidate.width)) / max(truck.ancho_cm, 1.0)
    z_waste = (truck.largo_cm - (candidate.z + candidate.depth)) / max(truck.largo_cm, 1.0)
    orientation_penalty = 0.0 if candidate.orientation == "LWH" else 0.02
    return (
        *loading_flow_key(candidate, truck, placed),
        round(projected_ratio, 6),
        round(top_ratio, 6),
        round(support_penalty, 6),
        round(contact_penalty, 6),
        round(route_penalty, 6),
        round(z_waste, 6),
        round(x_waste, 6),
        round(orientation_penalty, 6),
    )
