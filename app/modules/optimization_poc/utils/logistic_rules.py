from unicodedata import normalize as unicode_normalize

from app.modules.optimization_poc.models import Package3D, Truck3D
from app.modules.optimization_poc.utils.constants import (
    DESTINATION_ALIASES,
    LEVER_CENTRAL_BAND_RATIO,
    LEVER_LONG_SUPPORT_RATIO,
    LOGISTIC_ROUTE,
    LONGITUDINAL_MIN_CONTACT_RATIO,
)

DEFAULT_ROUTE = "TRUJILLO_OROCULLAY"
MIN_SUPPORT_RATIO = 0.60
UNLOADING_ASSUMPTION = "Los destinos mas lejanos se cargan primero y se ubican al fondo del box."
STACKING_FACTORS = {
    "ALTA": 0.0,
    "MEDIA": 0.5,
    "BAJA": 1.5,
}
LOADING_FRONTIER_EPSILON_CM = 0.001


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
    ratio = priority / max(max_priority, 1)
    target_depth = truck.length * (1.0 - ratio)
    return min(target_depth, available_depth)


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


def validate_longitudinal_restraint(
    candidate_space: dict,
    candidate_width: float,
    candidate_height: float,
    candidate_length: float,
    placed_packages: list[dict],
    truck: Truck3D,
) -> bool:
    """Un paquete ELEVADO debe estar sujeto en el eje de marcha (z) contra una pared
    del box o contra otro paquete; si no, al frenar el camion se caeria."""
    if candidate_space["y"] <= 0.001:
        return True

    x = candidate_space["x"]
    y = candidate_space["y"]
    z = candidate_space["z"]
    if z <= 0.001 or abs(z + candidate_length - truck.largo_cm) <= 0.001:
        return True

    face_area = candidate_width * candidate_height
    if face_area <= 0:
        return True

    for package in placed_packages:
        overlap_x = min(x + candidate_width, package["x"] + package["width"]) - max(x, package["x"])
        overlap_y = min(y + candidate_height, package["y"] + package["height"]) - max(y, package["y"])
        if overlap_x <= 0.001 or overlap_y <= 0.001:
            continue
        if (overlap_x * overlap_y) / face_area < LONGITUDINAL_MIN_CONTACT_RATIO:
            continue
        if abs(package["z"] + package["length"] - z) <= 0.001 or abs(z + candidate_length - package["z"]) <= 0.001:
            return True
    return False


def validate_no_lever_constraint(
    candidate_space: dict,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list[dict],
) -> bool:
    """Evita el efecto palanca: sobre un soporte ALARGADO, el paquete apilado debe
    caer en la banda central del soporte, no en un extremo."""
    if candidate_space["y"] <= 0.001:
        return True

    center_x = candidate_space["x"] + candidate_width / 2
    center_z = candidate_space["z"] + candidate_length / 2

    for package in placed_packages:
        if abs(package["y"] + package["height"] - candidate_space["y"]) > 0.001:
            continue
        overlap_x = min(candidate_space["x"] + candidate_width, package["x"] + package["width"]) - max(candidate_space["x"], package["x"])
        overlap_z = min(candidate_space["z"] + candidate_length, package["z"] + package["length"]) - max(candidate_space["z"], package["z"])
        if overlap_x <= 0.001 or overlap_z <= 0.001:
            continue

        long_axis = max(package["width"], package["length"])
        short_axis = min(package["width"], package["length"])
        if short_axis <= 0 or long_axis < LEVER_LONG_SUPPORT_RATIO * short_axis:
            continue

        if package["width"] >= package["length"]:
            support_center = package["x"] + package["width"] / 2
            half_band = (package["width"] / 2) * LEVER_CENTRAL_BAND_RATIO
            if abs(center_x - support_center) > half_band:
                return False
        else:
            support_center = package["z"] + package["length"] / 2
            half_band = (package["length"] / 2) * LEVER_CENTRAL_BAND_RATIO
            if abs(center_z - support_center) > half_band:
                return False
    return True


def register_supported_weight(candidate_package: dict, placed_packages: list[dict]) -> None:
    all_packages = [*placed_packages, candidate_package]
    for package in all_packages:
        package["supported_weight"] = 0.0
        package["stacking_capacity"] = calculate_stacking_capacity(package)
        package["support_ratio"] = calculate_support_ratio(
            package,
            package["width"],
            package["length"],
            [item for item in all_packages if item is not package],
        )

    for package in sorted(all_packages, key=lambda item: item["y"], reverse=True):
        if package["y"] == 0:
            package["support_ratio"] = 1.0
            continue

        supports, total_support_area = support_distribution(
            package,
            package["width"],
            package["length"],
            [item for item in all_packages if item is not package],
        )
        base_area = package["width"] * package["length"]
        package["support_ratio"] = min(1.0, total_support_area / base_area) if base_area > 0 else 0.0
        if total_support_area <= 0:
            continue

        transmitted_weight = float(package["weight"]) + float(package.get("supported_weight", 0.0))
        for support, overlap_area in supports:
            support["supported_weight"] = float(support.get("supported_weight", 0.0)) + (
                transmitted_weight * (overlap_area / total_support_area)
            )


def sort_free_spaces(free_spaces: list[dict]) -> list[dict]:
    return sorted(
        free_spaces,
        key=lambda space: (
            space["z"],
            space["y"],
            space["x"],
            -(space["width"] * space["height"] * space["length"]),
        ),
    )


def filter_candidate_options_by_loading_frontier(
    candidate_options: list[dict],
    placed_packages: list[dict],
) -> list[dict]:
    if not candidate_options:
        return []

    min_accessible_z = (
        placed_packages[-1]["z"]
        if placed_packages
        else 0.0
    ) - LOADING_FRONTIER_EPSILON_CM

    accessible_options = [
        option
        for option in candidate_options
        if option["space"]["z"] >= min_accessible_z
    ]
    if not accessible_options:
        return []

    min_z = min(option["space"]["z"] for option in accessible_options)
    frontier_z = min_z + LOADING_FRONTIER_EPSILON_CM
    return [
        option
        for option in accessible_options
        if option["space"]["z"] <= frontier_z
    ]
