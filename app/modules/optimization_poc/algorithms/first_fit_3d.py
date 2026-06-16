from app.modules.optimization_poc.models import Package3D, Truck3D, package_sort_key
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.utils.constants import FIRST_FIT_3D
from app.modules.optimization_poc.utils.geometry import build_candidate, candidate_points, is_valid_placement, orientations


def order_packages(packages: list[Package3D]) -> list[Package3D]:
    return sorted(packages, key=lambda package: package_sort_key(package, FIRST_FIT_3D))


def find_placement(
    package: Package3D,
    truck: Truck3D,
    placed: list[Placement],
    sequence: int,
    allow_rotation: bool,
) -> Placement | None:
    for width, height, depth, orientation in orientations(package, allow_rotation):
        for x, y, z in candidate_points(placed, truck, width, depth, package):
            candidate = build_candidate(package, sequence, x, y, z, width, height, depth, orientation)
            if is_valid_placement(candidate, truck, placed):
                return candidate
    return None
