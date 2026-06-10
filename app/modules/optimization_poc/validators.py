from app.modules.optimization_poc.schema import Placement, Truck

SUPPORT_RATIO = 0.7


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
    for current in placed:
        if abs((current.y + current.height) - candidate.y) > 0.001:
            continue
        overlap_x = max(0.0, min(candidate.x + candidate.width, current.x + current.width) - max(candidate.x, current.x))
        overlap_z = max(0.0, min(candidate.z + candidate.depth, current.z + current.depth) - max(candidate.z, current.z))
        supported_area += overlap_x * overlap_z
    return supported_area / base_area >= support_ratio


def respects_fragility(candidate: Placement, placed: list[Placement]) -> bool:
    for current in placed:
        sits_on_top = abs(candidate.y - (current.y + current.height)) <= 0.001
        horizontal_overlap = not (candidate.x + candidate.width <= current.x or current.x + current.width <= candidate.x or candidate.z + candidate.depth <= current.z or current.z + current.depth <= candidate.z)
        if sits_on_top and horizontal_overlap and current.fragility == "ALTA" and candidate.peso_kg > current.peso_kg:
            return False
    return True
