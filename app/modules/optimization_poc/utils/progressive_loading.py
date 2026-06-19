from collections.abc import Callable

from app.modules.optimization_poc.models import Package3D, Truck3D, destination_rank
from app.modules.optimization_poc.schema import Placement

PROGRESSIVE_LOOKAHEAD = 12

PlacementFinder = Callable[
    [Package3D, Truck3D, list[Placement], int, bool],
    Placement | None,
]


def select_progressive_placement(
    *,
    pending_packages: list[tuple[int, Package3D]],
    find_placement: PlacementFinder,
    truck: Truck3D,
    placements: list[Placement],
    allow_rotation: bool,
) -> tuple[int, Package3D, Placement] | None:
    evaluated: list[tuple[int, Package3D, Placement]] = []
    evaluated_indexes: set[int] = set()

    def evaluate(item: tuple[int, Package3D]) -> Placement | None:
        original_index, package = item
        evaluated_indexes.add(original_index)
        placement = find_placement(
            package,
            truck,
            placements,
            len(placements) + 1,
            allow_rotation,
        )
        if placement:
            evaluated.append((original_index, package, placement))
        return placement

    for item in pending_packages[:PROGRESSIVE_LOOKAHEAD]:
        evaluate(item)

    if evaluated:
        deepest_z = min(item[2].z for item in evaluated)
        deepest_candidates = [
            item
            for item in evaluated
            if abs(item[2].z - deepest_z) <= 0.001
        ]
        if deepest_candidates:
            return min(deepest_candidates, key=progressive_selection_key)

    for item in pending_packages:
        if item[0] not in evaluated_indexes:
            evaluate(item)

    if not evaluated:
        return None
    return min(evaluated, key=progressive_selection_key)


def progressive_selection_key(
    item: tuple[int, Package3D, Placement],
) -> tuple[float, int, float, float, int]:
    original_index, package, placement = item
    return (
        round(placement.z, 3),
        -destination_rank(package),
        round(placement.y, 3),
        round(placement.x, 3),
        original_index,
    )
