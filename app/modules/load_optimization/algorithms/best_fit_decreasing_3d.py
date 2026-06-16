import time

from app.modules.load_optimization.utils.geometry import (
    create_initial_space,
    fits_dimensions_in_space,
    generate_rotations,
    split_space,
    space_volume,
)

from app.modules.load_optimization.utils.metrics import (
    calculate_occupation_percentage,
    calculate_weight_percentage,
    calculate_success_rate,
)


ROUTES = {
    "TRUJILLO_OROCULLAY": [
        "TRUJILLO", "SHOREY", "HUAYCATAN", "SANTIAGO DE CHUCO",
        "CHACOMAS", "CACHICADAN", "SANTA CRUZ", "COCHAPAMPA",
        "UGALLAMA", "VILLACRUZ", "LAS MANZANAS", "ANGASMARCA",
        "TAMBO PAMPAMARCA ALTA", "PSICOCHACA", "SANTA CLARA DE TULPO",
        "LA YEGUADA", "MOLLEBAMBA", "COCHAMARCA", "OROCULLAY",
    ]
}

DEFAULT_ROUTE = "TRUJILLO_OROCULLAY"
MIN_SUPPORT_RATIO = 0.60

UNLOADING_ASSUMPTION = (
    "z=0 fondo del camion; z=truck.length puerta del camion"
)


def normalize_text(value: str) -> str:
    return value.strip().upper()


def get_route(route_name: str) -> list:
    route_key = normalize_text(route_name)

    if route_key not in ROUTES:
        raise ValueError(f"Ruta no soportada: {route_name}")

    return [normalize_text(destination) for destination in ROUTES[route_key]]


def validate_origin_and_destinations(route: list, origin_agency: str, packages: list):
    origin_agency = normalize_text(origin_agency)

    if origin_agency not in route:
        raise ValueError(
            f"Agencia origen no pertenece a la ruta: {origin_agency}"
        )

    for package in packages:
        destination = normalize_text(package.destination)

        if destination not in route:
            raise ValueError(
                f"Destino no pertenece a la ruta: {package.destination}"
            )

        if destination == origin_agency:
            raise ValueError(
                f"El destino {package.destination} no puede ser igual a la agencia origen"
            )


def build_destination_priority(
    route_name: str = DEFAULT_ROUTE,
    origin_agency: str = "TRUJILLO"
) -> dict:
    route = get_route(route_name)
    origin_agency = normalize_text(origin_agency)

    if origin_agency not in route:
        raise ValueError(
            f"Agencia origen no pertenece a la ruta: {origin_agency}"
        )

    origin_index = route.index(origin_agency)

    priorities = {}

    for destination in route:
        if destination == origin_agency:
            continue

        distance = abs(route.index(destination) - origin_index)
        priorities[destination] = distance

    return priorities


def get_destination_priority(destination: str, destination_priority: dict) -> int:
    return destination_priority.get(normalize_text(destination), 99)


def get_destination_zone(destination: str, truck, destination_priority: dict) -> dict:
    destination = normalize_text(destination)

    zone_length = truck.length / 3
    priority = destination_priority.get(destination)

    if priority is None:
        return {
            "start_z": 0,
            "end_z": truck.length,
            "label": "ZONA_GENERAL"
        }

    max_priority = max(destination_priority.values())

    if max_priority <= 0:
        return {
            "start_z": 0,
            "end_z": truck.length,
            "label": "ZONA_GENERAL"
        }

    ratio = priority / max_priority

    if ratio >= 0.67:
        return {
            "start_z": 0,
            "end_z": zone_length,
            "label": "ZONA_LEJANA"
        }

    if ratio >= 0.34:
        return {
            "start_z": zone_length,
            "end_z": zone_length * 2,
            "label": "ZONA_MEDIA"
        }

    return {
        "start_z": zone_length * 2,
        "end_z": truck.length,
        "label": "ZONA_CERCANA"
    }


def space_overlaps_destination_zone(
    space,
    placed_length: float,
    destination: str,
    truck,
    destination_priority: dict
) -> bool:
    zone = get_destination_zone(destination, truck, destination_priority)
    package_center_z = space["z"] + (placed_length / 2)

    return zone["start_z"] <= package_center_z <= zone["end_z"]


def calculate_zone_distance_penalty(
    space,
    placed_length: float,
    destination: str,
    truck,
    destination_priority: dict
) -> float:
    zone = get_destination_zone(destination, truck, destination_priority)
    zone_center = (zone["start_z"] + zone["end_z"]) / 2
    package_center = space["z"] + (placed_length / 2)

    distance = abs(package_center - zone_center)

    return distance * truck.width * truck.height


def sort_free_spaces_by_logistic_order(free_spaces: list) -> list:
    return sorted(
        free_spaces,
        key=lambda space: (space["z"], space["y"], space["x"])
    )


def calculate_stacking_capacity(package_data: dict) -> float:
    fragility = package_data["fragility"].upper()
    weight = package_data["weight"]

    if fragility == "ALTA":
        return 0

    if fragility == "MEDIA":
        return weight * 0.5

    return weight * 2


def ranges_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and end_a > start_b


def calculate_overlap_length(start_a, end_a, start_b, end_b) -> float:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def is_package_above(base_package: dict, upper_space: dict) -> bool:
    base_top_y = base_package["y"] + base_package["height"]
    return upper_space["y"] >= base_top_y


def validate_stacking_constraint(
    candidate_space: dict,
    candidate_weight: float,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list
) -> bool:
    candidate_x_start = candidate_space["x"]
    candidate_x_end = candidate_space["x"] + candidate_width
    candidate_z_start = candidate_space["z"]
    candidate_z_end = candidate_space["z"] + candidate_length

    for base_package in placed_packages:
        base_x_start = base_package["x"]
        base_x_end = base_package["x"] + base_package["width"]
        base_z_start = base_package["z"]
        base_z_end = base_package["z"] + base_package["length"]

        overlaps_x = ranges_overlap(
            candidate_x_start, candidate_x_end,
            base_x_start, base_x_end
        )

        overlaps_z = ranges_overlap(
            candidate_z_start, candidate_z_end,
            base_z_start, base_z_end
        )

        candidate_is_above = is_package_above(base_package, candidate_space)

        if overlaps_x and overlaps_z and candidate_is_above:
            stacking_capacity = calculate_stacking_capacity(base_package)

            if candidate_weight > stacking_capacity:
                return False

    return True


def calculate_support_ratio(
    candidate_space: dict,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list
) -> float:
    if candidate_space["y"] == 0:
        return 1.0

    candidate_x_start = candidate_space["x"]
    candidate_x_end = candidate_space["x"] + candidate_width
    candidate_z_start = candidate_space["z"]
    candidate_z_end = candidate_space["z"] + candidate_length

    base_area = candidate_width * candidate_length
    supported_area = 0

    for base_package in placed_packages:
        base_top_y = base_package["y"] + base_package["height"]

        if abs(base_top_y - candidate_space["y"]) > 0.001:
            continue

        overlap_x = calculate_overlap_length(
            candidate_x_start,
            candidate_x_end,
            base_package["x"],
            base_package["x"] + base_package["width"]
        )

        overlap_z = calculate_overlap_length(
            candidate_z_start,
            candidate_z_end,
            base_package["z"],
            base_package["z"] + base_package["length"]
        )

        supported_area += overlap_x * overlap_z

    if base_area <= 0:
        return 0

    return round(supported_area / base_area, 4)


def validate_stability_constraint(
    candidate_space: dict,
    candidate_width: float,
    candidate_length: float,
    placed_packages: list
) -> bool:
    support_ratio = calculate_support_ratio(
        candidate_space,
        candidate_width,
        candidate_length,
        placed_packages
    )

    return support_ratio >= MIN_SUPPORT_RATIO


def evaluate_candidate_spaces(
    free_spaces: list,
    rotated_width: float,
    rotated_height: float,
    rotated_length: float,
    package,
    placed_packages: list
) -> tuple[list, dict]:
    rejection_summary = {
        "dimension_rejections": 0,
        "stacking_rejections": 0,
        "stability_rejections": 0
    }

    valid_spaces = []

    for space in sort_free_spaces_by_logistic_order(free_spaces):
        if not fits_dimensions_in_space(
            rotated_width,
            rotated_height,
            rotated_length,
            space
        ):
            rejection_summary["dimension_rejections"] += 1
            continue

        if not validate_stacking_constraint(
            candidate_space=space,
            candidate_weight=package.weight,
            candidate_width=rotated_width,
            candidate_length=rotated_length,
            placed_packages=placed_packages
        ):
            rejection_summary["stacking_rejections"] += 1
            continue

        if not validate_stability_constraint(
            candidate_space=space,
            candidate_width=rotated_width,
            candidate_length=rotated_length,
            placed_packages=placed_packages
        ):
            rejection_summary["stability_rejections"] += 1
            continue

        valid_spaces.append(space)

    return valid_spaces, rejection_summary


def get_unplaced_reason_data(rejection_summary: dict) -> dict:
    if rejection_summary["stability_rejections"] > 0:
        return {
            "reason_code": "STABILITY_CONSTRAINT",
            "reason": "No cumple restricción de estabilidad mínima"
        }

    if rejection_summary["stacking_rejections"] > 0:
        return {
            "reason_code": "STACKING_CONSTRAINT",
            "reason": "No cumple restricción de estiba por peso y fragilidad"
        }

    if rejection_summary["dimension_rejections"] > 0:
        return {
            "reason_code": "NO_SPACE",
            "reason": "No hay espacio disponible"
        }

    return {
        "reason_code": "NO_SPACE",
        "reason": "No hay espacio disponible"
    }


def best_fit_decreasing_3d_algorithm(
    truck,
    packages,
    route: str = DEFAULT_ROUTE,
    origin_agency: str = "TRUJILLO"
):
    start_time = time.perf_counter()

    selected_route = get_route(route)
    origin_agency = normalize_text(origin_agency)

    validate_origin_and_destinations(
        selected_route,
        origin_agency,
        packages
    )

    destination_priority = build_destination_priority(
        route,
        origin_agency
    )

    sorted_packages = sorted(
        packages,
        key=lambda package: (
            -get_destination_priority(
                package.destination,
                destination_priority
            ),
            -package.volume
        )
    )

    free_spaces = [create_initial_space(truck)]

    placed_packages = []
    unplaced_packages = []

    used_volume = 0
    total_weight = 0

    for package in sorted_packages:
        if total_weight + package.weight > truck.max_weight:
            unplaced_packages.append({
                "id": package.id,
                "reason_code": "WEIGHT_LIMIT",
                "reason": "Excede el peso máximo del camión"
            })
            continue

        best_option = None
        fallback_option = None

        package_rejection_summary = {
            "dimension_rejections": 0,
            "stacking_rejections": 0,
            "stability_rejections": 0
        }

        for rotation in generate_rotations(package):
            rotated_width, rotated_height, rotated_length = rotation
            rotated_volume = rotated_width * rotated_height * rotated_length

            candidate_spaces, rejection_summary = evaluate_candidate_spaces(
                free_spaces=free_spaces,
                rotated_width=rotated_width,
                rotated_height=rotated_height,
                rotated_length=rotated_length,
                package=package,
                placed_packages=placed_packages
            )

            for key in package_rejection_summary:
                package_rejection_summary[key] += rejection_summary[key]

            for candidate_space in candidate_spaces:
                remaining_volume = space_volume(candidate_space) - rotated_volume

                zone_penalty = calculate_zone_distance_penalty(
                    candidate_space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority
                )

                optimization_score = remaining_volume + zone_penalty

                inside_destination_zone = space_overlaps_destination_zone(
                    candidate_space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority
                )

                support_ratio = calculate_support_ratio(
                    candidate_space,
                    rotated_width,
                    rotated_length,
                    placed_packages
                )

                option = {
                    "space": candidate_space,
                    "width": rotated_width,
                    "height": rotated_height,
                    "length": rotated_length,
                    "volume": rotated_volume,
                    "remaining_volume": remaining_volume,
                    "zone_penalty": zone_penalty,
                    "optimization_score": optimization_score,
                    "inside_destination_zone": inside_destination_zone,
                    "support_ratio": support_ratio,
                    "stacking_constraint_satisfied": True,
                    "stability_constraint_satisfied": (
                        support_ratio >= MIN_SUPPORT_RATIO
                    )
                }

                if inside_destination_zone:
                    if (
                        best_option is None
                        or option["optimization_score"]
                        < best_option["optimization_score"]
                    ):
                        best_option = option

                if (
                    fallback_option is None
                    or option["optimization_score"]
                    < fallback_option["optimization_score"]
                ):
                    fallback_option = option

        selected_option = (
            best_option
            if best_option is not None
            else fallback_option
        )

        if selected_option is None:
            reason_data = get_unplaced_reason_data(package_rejection_summary)

            unplaced_packages.append({
                "id": package.id,
                "reason_code": reason_data["reason_code"],
                "reason": reason_data["reason"],
                "rejection_summary": package_rejection_summary
            })
            continue

        selected_space = selected_option["space"]
        placed_width = selected_option["width"]
        placed_height = selected_option["height"]
        placed_length = selected_option["length"]
        placed_volume = selected_option["volume"]

        destination_zone = get_destination_zone(
            package.destination,
            truck,
            destination_priority
        )

        stacking_capacity = calculate_stacking_capacity({
            "fragility": package.fragility,
            "weight": package.weight
        })

        placed_packages.append({
            "id": package.id,
            "x": selected_space["x"],
            "y": selected_space["y"],
            "z": selected_space["z"],
            "width": placed_width,
            "height": placed_height,
            "length": placed_length,
            "original_width": package.width,
            "original_height": package.height,
            "original_length": package.length,
            "weight": package.weight,
            "fragility": package.fragility,
            "destination": package.destination,
            "destination_priority": get_destination_priority(
                package.destination,
                destination_priority
            ),
            "destination_zone": destination_zone,
            "inside_destination_zone": selected_option["inside_destination_zone"],
            "stacking_capacity": stacking_capacity,
            "stacking_constraint_satisfied": selected_option[
                "stacking_constraint_satisfied"
            ],
            "support_ratio": selected_option["support_ratio"],
            "minimum_support_ratio_required": MIN_SUPPORT_RATIO,
            "stability_constraint_satisfied": selected_option[
                "stability_constraint_satisfied"
            ],
            "content_type": package.content_type,
            "rotated": (
                placed_width != package.width
                or placed_height != package.height
                or placed_length != package.length
            )
        })

        used_volume += placed_volume
        total_weight += package.weight

        free_spaces.remove(selected_space)
        free_spaces.extend(
            split_space(
                selected_space,
                placed_width,
                placed_height,
                placed_length
            )
        )

    execution_time_ms = round(
        (time.perf_counter() - start_time) * 1000,
        3
    )

    zone_compliance_count = sum(
        1 for package in placed_packages
        if package["inside_destination_zone"]
    )

    stacking_compliance_count = sum(
        1 for package in placed_packages
        if package["stacking_constraint_satisfied"]
    )

    stability_compliance_count = sum(
        1 for package in placed_packages
        if package["stability_constraint_satisfied"]
    )

    zone_compliance_percentage = round(
        (zone_compliance_count / len(placed_packages)) * 100,
        2
    ) if placed_packages else 0

    stacking_compliance_percentage = round(
        (stacking_compliance_count / len(placed_packages)) * 100,
        2
    ) if placed_packages else 0

    stability_compliance_percentage = round(
        (stability_compliance_count / len(placed_packages)) * 100,
        2
    ) if placed_packages else 0

    return {
        "algorithm": "bfd3d",
        "route": route,
        "origin_agency": origin_agency,
        "destination_order_applied": True,
        "destination_zone_constraint_applied": True,
        "destination_spatial_preference_applied": True,
        "stacking_constraint_applied": True,
        "stability_constraint_applied": True,
        "minimum_support_ratio_required": MIN_SUPPORT_RATIO,
        "stacking_rule": {
            "ALTA": "0 kg encima",
            "MEDIA": "50% del peso del paquete",
            "BAJA": "200% del peso del paquete"
        },
        "destination_priority": destination_priority,
        "unloading_assumption": UNLOADING_ASSUMPTION,
        "zone_compliance_percentage": zone_compliance_percentage,
        "zone_compliance_count": zone_compliance_count,
        "stacking_compliance_percentage": stacking_compliance_percentage,
        "stacking_compliance_count": stacking_compliance_count,
        "stability_compliance_percentage": stability_compliance_percentage,
        "stability_compliance_count": stability_compliance_count,
        "occupation_percentage": calculate_occupation_percentage(
            used_volume,
            truck.volume
        ),
        "weight_percentage": calculate_weight_percentage(
            total_weight,
            truck.max_weight
        ),
        "success_rate": calculate_success_rate(
            placed_packages,
            unplaced_packages
        ),
        "execution_time_ms": execution_time_ms,
        "used_volume": used_volume,
        "truck_volume": truck.volume,
        "total_weight": total_weight,
        "max_weight": truck.max_weight,
        "placed_count": len(placed_packages),
        "unplaced_count": len(unplaced_packages),
        "placed_packages": placed_packages,
        "unplaced_packages": unplaced_packages,
    }