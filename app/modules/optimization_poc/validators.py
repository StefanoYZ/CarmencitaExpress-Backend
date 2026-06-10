from app.modules.optimization_poc.schema import Placement, Truck

SUPPORT_RATIO = 0.6
EDGE_SUPPORT_RATIO = 0.12
FRAGILITY_SUPPORT_FACTOR = {
    "ALTA": 0.0,
    "MEDIA": 0.5,
    "BAJA": 2.0,
}


def is_inside_truck(x: float, y: float, z: float, width: float, height: float, depth: float, truck: Truck) -> bool:
    return x >= 0 and y >= 0 and z >= 0 and x + width <= truck.ancho_cm and y + height <= truck.alto_cm and z + depth <= truck.largo_cm


def has_overlap(candidate: Placement, placed: list[Placement]) -> bool:
    for current in placed:
        separated = candidate.x + candidate.width <= current.x or current.x + current.width <= candidate.x or candidate.y + candidate.height <= current.y or current.y + current.height <= candidate.y or candidate.z + candidate.depth <= current.z or current.z + current.depth <= candidate.z
        if not separated:
            return True
    return False


def is_weight_allowed(current_weight: float, next_weight: float, truck: Truck) -> bool:
    return current_weight + next_weight <= truck.capacidad_peso_kg


def has_minimum_support(candidate: Placement, placed: list[Placement], support_ratio: float = SUPPORT_RATIO) -> bool:
    if candidate.y == 0:
        return True
    base_area = candidate.width * candidate.depth
    if base_area <= 0:
        return False
    supported_area = 0.0
    support_min_x = candidate.x + candidate.width
    support_max_x = candidate.x
    support_min_z = candidate.z + candidate.depth
    support_max_z = candidate.z
    for current in placed:
        if abs((current.y + current.height) - candidate.y) > 0.001:
            continue
        overlap_x = max(0.0, min(candidate.x + candidate.width, current.x + current.width) - max(candidate.x, current.x))
        overlap_z = max(0.0, min(candidate.z + candidate.depth, current.z + current.depth) - max(candidate.z, current.z))
        overlap_area = overlap_x * overlap_z
        if overlap_area <= 0:
            continue
        supported_area += overlap_area
        support_min_x = min(support_min_x, max(candidate.x, current.x))
        support_max_x = max(support_max_x, min(candidate.x + candidate.width, current.x + current.width))
        support_min_z = min(support_min_z, max(candidate.z, current.z))
        support_max_z = max(support_max_z, min(candidate.z + candidate.depth, current.z + current.depth))

    if supported_area / base_area < support_ratio:
        return False

    edge_x = candidate.width * EDGE_SUPPORT_RATIO
    edge_z = candidate.depth * EDGE_SUPPORT_RATIO
    has_width_support = support_min_x <= candidate.x + edge_x and support_max_x >= candidate.x + candidate.width - edge_x
    has_depth_support = support_min_z <= candidate.z + edge_z and support_max_z >= candidate.z + candidate.depth - edge_z
    return has_width_support and has_depth_support


def respects_fragility(candidate: Placement, placed: list[Placement]) -> bool:
    if candidate.y == 0:
        return True

    supports: list[tuple[Placement, float]] = []
    for current in placed:
        sits_on_top = abs(candidate.y - (current.y + current.height)) <= 0.001
        if not sits_on_top:
            continue
        overlap_x = max(0.0, min(candidate.x + candidate.width, current.x + current.width) - max(candidate.x, current.x))
        overlap_z = max(0.0, min(candidate.z + candidate.depth, current.z + current.depth) - max(candidate.z, current.z))
        overlap_area = overlap_x * overlap_z
        if overlap_area > 0:
            supports.append((current, overlap_area))

    total_support_area = sum(overlap_area for _, overlap_area in supports)
    if total_support_area <= 0:
        return False

    for support, overlap_area in supports:
        carried_weight = candidate.peso_kg * (overlap_area / total_support_area)
        max_supported_weight = support.peso_kg * FRAGILITY_SUPPORT_FACTOR.get(support.fragility, 0.0)
        if carried_weight > max_supported_weight:
            return False
    return True
