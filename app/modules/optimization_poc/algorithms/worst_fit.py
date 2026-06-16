from time import perf_counter

from app.modules.optimization_poc.models import Package3D, Truck3D
from app.modules.optimization_poc.utils.geometry import (
    create_initial_space,
    fits_dimensions_in_space,
    generate_rotations,
    space_volume,
    split_space,
)
from app.modules.optimization_poc.utils.logistic_rules import (
    DEFAULT_ROUTE,
    UNLOADING_ASSUMPTION,
    build_destination_priority,
    calculate_stacking_capacity,
    calculate_support_ratio,
    calculate_zone_distance_penalty,
    get_destination_priority,
    get_destination_zone,
    get_route,
    normalize_text,
    register_supported_weight,
    sort_free_spaces,
    space_overlaps_destination_zone,
    validate_origin_and_destinations,
    validate_stability_constraint,
    validate_stacking_constraint,
)


def worst_fit_algorithm(
    truck: Truck3D,
    packages: list[Package3D],
    route: str = DEFAULT_ROUTE,
    origin_agency: str = "TRUJILLO",
) -> dict:
    started = perf_counter()

    selected_route = get_route(route)
    normalized_origin = normalize_text(origin_agency)
    validate_origin_and_destinations(selected_route, normalized_origin, packages)
    destination_priority = build_destination_priority(route, normalized_origin)

    ordered_packages = sorted(
        packages,
        key=lambda package: (
            -package.volume,
            -package.weight,
            -get_destination_priority(package.destination, destination_priority),
            package.codigo,
        ),
    )

    free_spaces = [create_initial_space(truck)]
    placed_packages: list[dict] = []
    unplaced_packages: list[dict] = []
    total_weight = 0.0

    for package in ordered_packages:
        if total_weight + package.weight > truck.max_weight:
            unplaced_packages.append(
                {
                    "id": package.id,
                    "reason_code": "WEIGHT_LIMIT",
                    "reason": "Excede el peso maximo del camion",
                }
            )
            continue

        candidate_options = []
        rejection_summary = {
            "dimension_rejections": 0,
            "stacking_rejections": 0,
            "stability_rejections": 0,
        }

        for rotated_width, rotated_height, rotated_length in generate_rotations(package):
            rotated_volume = rotated_width * rotated_height * rotated_length

            for space in free_spaces:
                if not fits_dimensions_in_space(rotated_width, rotated_height, rotated_length, space):
                    rejection_summary["dimension_rejections"] += 1
                    continue

                if not validate_stacking_constraint(
                    candidate_space=space,
                    candidate_weight=package.weight,
                    candidate_width=rotated_width,
                    candidate_length=rotated_length,
                    placed_packages=placed_packages,
                ):
                    rejection_summary["stacking_rejections"] += 1
                    continue

                if not validate_stability_constraint(
                    candidate_space=space,
                    candidate_width=rotated_width,
                    candidate_length=rotated_length,
                    placed_packages=placed_packages,
                ):
                    rejection_summary["stability_rejections"] += 1
                    continue

                remaining_volume = space_volume(space) - rotated_volume
                zone_penalty = calculate_zone_distance_penalty(
                    space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority,
                )

                candidate_options.append(
                    {
                        "space": space,
                        "width": rotated_width,
                        "height": rotated_height,
                        "length": rotated_length,
                        "volume": rotated_volume,
                        "remaining_volume": remaining_volume,
                        "zone_penalty": zone_penalty,
                        "inside_destination_zone": space_overlaps_destination_zone(
                            space,
                            rotated_length,
                            package.destination,
                            truck,
                            destination_priority,
                        ),
                        "support_ratio": calculate_support_ratio(
                            space,
                            rotated_width,
                            rotated_length,
                            placed_packages,
                        ),
                    }
                )

        if not candidate_options:
            unplaced_packages.append(
                {
                    "id": package.id,
                    "reason_code": "NO_FEASIBLE_SPACE",
                    "reason": "No se encontro un espacio valido segun las restricciones",
                    "rejection_summary": rejection_summary,
                }
            )
            continue

        selected_option = max(
            candidate_options,
            key=lambda option: (
                option["remaining_volume"],
                option["inside_destination_zone"],
                -option["zone_penalty"],
                option["support_ratio"],
                -option["space"]["y"],
            ),
        )

        selected_space = selected_option["space"]
        placed_package = {
            "id": package.id,
            "codigo": package.codigo,
            "description": package.descripcion,
            "delivery_order": package.orden_entrega,
            "priority": package.prioridad,
            "x": selected_space["x"],
            "y": selected_space["y"],
            "z": selected_space["z"],
            "width": selected_option["width"],
            "height": selected_option["height"],
            "length": selected_option["length"],
            "weight": package.weight,
            "fragility": package.fragility,
            "destination": package.destination,
            "destination_priority": get_destination_priority(package.destination, destination_priority),
            "destination_zone": get_destination_zone(package.destination, truck, destination_priority),
            "inside_destination_zone": selected_option["inside_destination_zone"],
            "stacking_capacity": calculate_stacking_capacity(
                {"fragility": package.fragility, "weight": package.weight}
            ),
            "support_ratio": selected_option["support_ratio"],
            "content_type": package.content_type,
            "supported_weight": 0.0,
            "rotated": (
                selected_option["width"] != package.width
                or selected_option["height"] != package.height
                or selected_option["length"] != package.length
            ),
        }

        register_supported_weight(placed_package, placed_packages)
        placed_packages.append(placed_package)
        total_weight += package.weight

        free_spaces = [space for space in free_spaces if space is not selected_space]
        free_spaces.extend(
            split_space(
                selected_space,
                selected_option["width"],
                selected_option["height"],
                selected_option["length"],
            )
        )
        free_spaces = sort_free_spaces(free_spaces)

    used_volume = sum(package["width"] * package["height"] * package["length"] for package in placed_packages)
    execution_time_ms = round((perf_counter() - started) * 1000, 3)

    return {
        "algorithm": "worst_fit",
        "route": route,
        "origin_agency": normalized_origin,
        "destination_priority": destination_priority,
        "unloading_assumption": UNLOADING_ASSUMPTION,
        "execution_time_ms": execution_time_ms,
        "used_volume": used_volume,
        "truck_volume": truck.volume,
        "total_weight": total_weight,
        "max_weight": truck.max_weight,
        "placed_count": len(placed_packages),
        "unplaced_count": len(unplaced_packages),
        "placed_packages": placed_packages,
        "unplaced_packages": unplaced_packages,
        "ordered_packages": ordered_packages,
    }
