from unicodedata import normalize as unicode_normalize

from app.modules.optimization_poc.models import Package3D, Truck3D
from app.modules.optimization_poc.utils.constants import DESTINATION_ALIASES, LOGISTIC_ROUTE

DEFAULT_ROUTE = "TRUJILLO_OROCULLAY"
MIN_SUPPORT_RATIO = 0.60
UNLOADING_ASSUMPTION = "Los destinos mas lejanos se cargan primero y se ubican al fondo del box."
STACKING_FACTORS = {
    "ALTA": 0.0,
    "MEDIA": 0.5,
    "BAJA": 2.0,
}


def normalize_text(value: str) -> str:
    normalized = unicode_normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    normalized = " ".join(normalized.upper().split())
    return DESTINATION_ALIASES.get(normalized, normalized)


def get_route(route: str = DEFAULT_ROUTE) -> list[str]:
    _ = route
    return [normalize_text(stop) for stop in LOGISTIC_ROUTE]


def validate_origin_and_destinations(
    selected_route: list[str],
    origin_agency: str,
    packages: list[Package3D],
) -> None:
    normalized_origin = normalize_text(origin_agency)
    if normalized_origin not in selected_route:
        raise ValueError(f"Origen no soportado para la PoC: {origin_agency}")

    invalid_destinations = sorted(
        {
            package.destino
            for package in packages
            if normalize_text(package.destino) not in selected_route
        }
    )
    if invalid_destinations:
        raise ValueError(
            "Destinos fuera de la ruta logistica: "
            + ", ".join(invalid_destinations)
        )


def build_destination_priority(route: str, origin_agency: str) -> dict[str, int]:
    selected_route = get_route(route)
    normalized_origin = normalize_text(origin_agency)
    origin_index = selected_route.index(normalized_origin)
    downstream_stops = selected_route[origin_index + 1 :]
    return {
        destination: index + 1
        for index, destination in enumerate(downstream_stops)
    }


def get_destination_priority(destination: str, destination_priority: dict[str, int]) -> int:
    return destination_priority.get(normalize_text(destination), 0)


def get_destination_zone(destination: str, truck: Truck3D, destination_priority: dict[str, int]) -> str:
    _ = truck
    priority = get_destination_priority(destination, destination_priority)
    max_priority = max(destination_priority.values(), default=1)
    ratio = priority / max(max_priority, 1)
    if ratio >= 0.66:
        return "LEJANA"
    if ratio >= 0.33:
        return "MEDIA"
    return "CERCANA"


def destination_target_z(
    destination: str,
    truck: Truck3D,
    length: float,
    destination_priority: dict[str, int],
) -> float:
    priority = get_destination_priority(destination, destination_priority)
    max_priority = max(destination_priority.values(), default=1)
    available_depth = max(truck.length - length, 0.0)
    return available_depth * (priority / max(max_priority, 1))


def space_overlaps_destination_zone(
    space: dict,
    candidate_length: float,
    destination: str,
    truck: Truck3D,
    destination_priority: dict[str, int],
) -> bool:
    target_z = destination_target_z(destination, truck, candidate_length, destination_priority)
    candidate_center = space["z"] + (candidate_length / 2)
    target_center = target_z + (candidate_length / 2)
    tolerance = max(candidate_length, truck.length * 0.18)
    return abs(candidate_center - target_center) <= tolerance


def calculate_zone_distance_penalty(
    space: dict,
    candidate_length: float,
    destination: str,
    truck: Truck3D,
    destination_priority: dict[str, int],
) -> float:
    target_z = destination_target_z(destination, truck, candidate_length, destination_priority)
    return abs(space["z"] - target_z) / max(truck.length, 1.0)


def calculate_stacking_capacity(package_like: dict) -> float:
    return float(package_like["weight"]) * STACKING_FACTORS.get(package_like["fragility"], 0.0)


def support_distribution(
    candidate_space: dict,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list[dict],
) -> tuple[list[tuple[dict, float]], float]:
    if candidate_space["y"] == 0:
        return [], candidate_width * candidate_length

    supports: list[tuple[dict, float]] = []
    total_support_area = 0.0

    for package in placed_packages:
        if abs((package["y"] + package["height"]) - candidate_space["y"]) > 0.001:
            continue

        overlap_x = max(
            0.0,
            min(candidate_space["x"] + candidate_width, package["x"] + package["width"])
            - max(candidate_space["x"], package["x"]),
        )
        overlap_z = max(
            0.0,
            min(candidate_space["z"] + candidate_length, package["z"] + package["length"])
            - max(candidate_space["z"], package["z"]),
        )
        overlap_area = overlap_x * overlap_z
        if overlap_area <= 0:
            continue

        supports.append((package, overlap_area))
        total_support_area += overlap_area

    return supports, total_support_area


def calculate_support_ratio(
    candidate_space: dict,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list[dict],
) -> float:
    if candidate_space["y"] == 0:
        return 1.0

    base_area = candidate_width * candidate_length
    if base_area <= 0:
        return 0.0

    _, total_support_area = support_distribution(
        candidate_space,
        candidate_width,
        candidate_length,
        placed_packages,
    )
    return min(1.0, total_support_area / base_area)


def validate_stability_constraint(
    candidate_space: dict,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list[dict],
) -> bool:
    if candidate_space["y"] == 0:
        return True

    support_ratio = calculate_support_ratio(
        candidate_space,
        candidate_width,
        candidate_length,
        placed_packages,
    )
    return support_ratio >= MIN_SUPPORT_RATIO


def validate_stacking_constraint(
    candidate_space: dict,
    candidate_weight: float,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list[dict],
) -> bool:
    if candidate_space["y"] == 0:
        return True

    supports, total_support_area = support_distribution(
        candidate_space,
        candidate_width,
        candidate_length,
        placed_packages,
    )
    if total_support_area <= 0:
        return False

    for support, overlap_area in supports:
        carried_weight = candidate_weight * (overlap_area / total_support_area)
        current_supported_weight = float(support.get("supported_weight", 0.0))
        stacking_capacity = float(
            support.get("stacking_capacity", calculate_stacking_capacity(support))
        )
        if current_supported_weight + carried_weight > stacking_capacity + 1e-6:
            return False

    return True


def register_supported_weight(candidate_package: dict, placed_packages: list[dict]) -> None:
    if candidate_package["y"] == 0:
        return

    supports, total_support_area = support_distribution(
        candidate_package,
        candidate_package["width"],
        candidate_package["length"],
        placed_packages,
    )
    if total_support_area <= 0:
        return

    for support, overlap_area in supports:
        carried_weight = candidate_package["weight"] * (overlap_area / total_support_area)
        support["supported_weight"] = float(support.get("supported_weight", 0.0)) + carried_weight


def sort_free_spaces(free_spaces: list[dict]) -> list[dict]:
    return sorted(
        free_spaces,
        key=lambda space: (
            -(space["width"] * space["height"] * space["length"]),
            space["y"],
            space["z"],
            space["x"],
        ),
    )
