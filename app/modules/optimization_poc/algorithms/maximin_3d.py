from app.modules.optimization_poc.models import Package3D, Truck3D, package_sort_key
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.utils.constants import MAXIMIN
from app.modules.optimization_poc.utils.geometry import (
    contact_score,
    dense_valid_candidates,
    loading_flow_key,
    projected_bounding_volume,
    route_alignment_penalty,
    support_ratio,
)


def order_packages(packages: list[Package3D]) -> list[Package3D]:
    return sorted(packages, key=lambda package: package_sort_key(package, MAXIMIN))


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
    support = support_ratio(candidate, placed)
    contact = contact_score(candidate, truck, placed)
    route_fit = 1.0 - route_alignment_penalty(candidate, truck)
    footprint_ratio = (candidate.width * candidate.depth) / max(truck.ancho_cm * truck.largo_cm, 1.0)
    truck_volume = max(truck.ancho_cm * truck.alto_cm * truck.largo_cm, 1.0)
    compactness = 1.0 - (projected_bounding_volume(candidate, placed) / truck_volume)
    height_score = 1.0 - ((candidate.y + candidate.height) / max(truck.alto_cm, 1.0))
    depth_score = (candidate.z + candidate.depth) / max(truck.largo_cm, 1.0)
    floor_bonus = 1.0 if candidate.y == 0 else 0.0
    return (
        *loading_flow_key(candidate, truck, placed),
        round(-support, 6),
        round(-contact, 6),
        round(-compactness, 6),
        round(-footprint_ratio, 6),
        round(-route_fit, 6),
        round(-height_score, 6),
        round(-floor_bonus, 6),
        round(depth_score, 6),
    )
