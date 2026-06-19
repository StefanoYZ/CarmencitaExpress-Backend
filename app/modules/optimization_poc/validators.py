from app.modules.optimization_poc.schema import Placement, Truck

SUPPORT_RATIO = 0.60
FRAGILITY_SUPPORT_FACTOR = {
    "ALTA": 0.0,
    "MEDIA": 0.5,
    "BAJA": 1.5,
}


def is_inside_truck(x: float, y: float, z: float, width: float, height: float, depth: float, truck: Truck) -> bool:
    return (
        x >= 0
        and y >= 0
        and z >= 0
        and x + width <= truck.ancho_cm
        and y + height <= truck.alto_cm
        and z + depth <= truck.largo_cm
    )


def has_overlap(candidate: Placement, placed: list[Placement]) -> bool:
    for current in placed:
        separated = (
            candidate.x + candidate.width <= current.x
            or current.x + current.width <= candidate.x
            or candidate.y + candidate.height <= current.y
            or current.y + current.height <= candidate.y
            or candidate.z + candidate.depth <= current.z
            or current.z + current.depth <= candidate.z
        )
        if not separated:
            return True
    return False


def is_weight_allowed(current_weight: float, next_weight: float, truck: Truck) -> bool:
    return current_weight + next_weight <= truck.capacidad_peso_kg


def stacking_capacity_for_fragility(fragility: str, weight: float) -> float:
    return float(weight) * FRAGILITY_SUPPORT_FACTOR.get((fragility or "").upper(), 0.0)


def support_distribution(candidate: Placement, placed: list[Placement]) -> tuple[list[tuple[Placement, float]], float]:
    supports: list[tuple[Placement, float]] = []
    total_support_area = 0.0

    if candidate.y == 0:
        return supports, candidate.width * candidate.depth

    for current in placed:
        if abs((current.y + current.height) - candidate.y) > 0.001:
            continue
        overlap_x = max(
            0.0,
            min(candidate.x + candidate.width, current.x + current.width) - max(candidate.x, current.x),
        )
        overlap_z = max(
            0.0,
            min(candidate.z + candidate.depth, current.z + current.depth) - max(candidate.z, current.z),
        )
        overlap_area = overlap_x * overlap_z
        if overlap_area <= 0:
            continue
        supports.append((current, overlap_area))
        total_support_area += overlap_area

    return supports, total_support_area


def placement_support_ratio(candidate: Placement, placed: list[Placement]) -> float:
    if candidate.y == 0:
        return 1.0

    base_area = candidate.width * candidate.depth
    if base_area <= 0:
        return 0.0

    _, supported_area = support_distribution(candidate, placed)
    return min(1.0, supported_area / base_area)


def has_minimum_support(candidate: Placement, placed: list[Placement], support_ratio: float = SUPPORT_RATIO) -> bool:
    candidate.support_ratio = placement_support_ratio(candidate, placed)
    return candidate.support_ratio >= support_ratio


def respects_fragility(candidate: Placement, placed: list[Placement]) -> bool:
    if candidate.y == 0:
        return True

    supports, total_support_area = support_distribution(candidate, placed)
    if total_support_area <= 0:
        return False

    for support, overlap_area in supports:
        carried_weight = candidate.peso_kg * (overlap_area / total_support_area)
        stacking_capacity = support.stacking_capacity or stacking_capacity_for_fragility(support.fragility, support.peso_kg)
        if support.supported_weight + carried_weight > stacking_capacity + 1e-6:
            return False
    return True


def has_lateral_support_for_vertical_thin(candidate: Placement, truck: Truck, placed: list[Placement]) -> bool:
    if candidate.orientation != "VERTICAL":
        return True
    if candidate.y != 0:
        return False

    tolerance = 0.001
    touches_side_wall = candidate.x <= tolerance or abs(candidate.x + candidate.width - truck.ancho_cm) <= tolerance
    if touches_side_wall:
        return True

    for item in placed:
        same_left_side = abs(candidate.x - (item.x + item.width)) <= tolerance
        same_right_side = abs((candidate.x + candidate.width) - item.x) <= tolerance
        if not same_left_side and not same_right_side:
            continue
        overlap_y = max(0.0, min(candidate.y + candidate.height, item.y + item.height) - max(candidate.y, item.y))
        overlap_z = max(0.0, min(candidate.z + candidate.depth, item.z + item.depth) - max(candidate.z, item.z))
        lateral_contact_ratio = (overlap_y * overlap_z) / max(candidate.height * candidate.depth, 1.0)
        if lateral_contact_ratio >= 0.35:
            return True
    return False


def recompute_supported_weights(placements: list[Placement]) -> None:
    for placement in placements:
        placement.supported_weight = 0.0
        placement.stacking_capacity = stacking_capacity_for_fragility(placement.fragility, placement.peso_kg)
        placement.support_ratio = placement_support_ratio(placement, [item for item in placements if item is not placement])

    for placement in sorted(placements, key=lambda item: item.y, reverse=True):
        if placement.y == 0:
            placement.support_ratio = 1.0
            continue

        supports, total_support_area = support_distribution(
            placement,
            [item for item in placements if item is not placement],
        )
        base_area = placement.width * placement.depth
        placement.support_ratio = min(1.0, total_support_area / base_area) if base_area > 0 else 0.0
        if total_support_area <= 0:
            continue

        transmitted_weight = placement.peso_kg + placement.supported_weight
        for support, overlap_area in supports:
            support.supported_weight += transmitted_weight * (overlap_area / total_support_area)
