import time
from copy import deepcopy

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

from app.modules.load_optimization.algorithms.best_fit_decreasing_3d import (
    DEFAULT_ROUTE,
    MIN_SUPPORT_RATIO,
    UNLOADING_ASSUMPTION,
    get_route,
    normalize_text,
    validate_origin_and_destinations,
    build_destination_priority,
    get_destination_priority,
    get_destination_zone,
    space_overlaps_destination_zone,
    calculate_zone_distance_penalty,
    calculate_stacking_capacity,
    validate_stacking_constraint,
    calculate_support_ratio,
    validate_stability_constraint,
)


def get_backtracking_rejection_data(rejection_summary: dict) -> dict:
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
        "reason_code": "LOGISTIC_CONSTRAINT",
        "reason": "No hay espacio disponible o no cumple restricciones logísticas"
    }


def backtracking_3d_algorithm(
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

    best_solution = {
        "placed_packages": [],
        "unplaced_packages": [],
        "used_volume": 0,
        "total_weight": 0,
    }

    def is_better_solution(current_solution, current_best_solution):
        if len(current_solution["placed_packages"]) > len(
            current_best_solution["placed_packages"]
        ):
            return True

        if len(current_solution["placed_packages"]) == len(
            current_best_solution["placed_packages"]
        ):
            return current_solution["used_volume"] > current_best_solution[
                "used_volume"
            ]

        return False

    def backtrack(
        index,
        free_spaces,
        placed_packages,
        unplaced_packages,
        used_volume,
        total_weight
    ):
        nonlocal best_solution

        if index >= len(sorted_packages):
            current_solution = {
                "placed_packages": placed_packages,
                "unplaced_packages": unplaced_packages,
                "used_volume": used_volume,
                "total_weight": total_weight,
            }

            if is_better_solution(current_solution, best_solution):
                best_solution = deepcopy(current_solution)

            return

        package = sorted_packages[index]

        if total_weight + package.weight > truck.max_weight:
            backtrack(
                index + 1,
                free_spaces,
                placed_packages,
                unplaced_packages + [{
                    "id": package.id,
                    "reason_code": "WEIGHT_LIMIT",
                    "reason": "Excede el peso máximo del camión"
                }],
                used_volume,
                total_weight
            )
            return

        candidate_options = []

        rejection_summary = {
            "dimension_rejections": 0,
            "stacking_rejections": 0,
            "stability_rejections": 0
        }

        for rotation in generate_rotations(package):
            rotated_width, rotated_height, rotated_length = rotation
            rotated_volume = rotated_width * rotated_height * rotated_length

            for space in free_spaces:
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

                inside_destination_zone = space_overlaps_destination_zone(
                    space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority
                )

                zone_penalty = calculate_zone_distance_penalty(
                    space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority
                )

                remaining_volume = space_volume(space) - rotated_volume

                optimization_score = remaining_volume + zone_penalty

                support_ratio = calculate_support_ratio(
                    space,
                    rotated_width,
                    rotated_length,
                    placed_packages
                )

                candidate_options.append({
                    "space": space,
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
                })

        candidate_options = sorted(
            candidate_options,
            key=lambda option: (
                not option["inside_destination_zone"],
                option["optimization_score"]
            )
        )

        if not candidate_options:
            rejection_data = get_backtracking_rejection_data(
                rejection_summary
            )

            backtrack(
                index + 1,
                free_spaces,
                placed_packages,
                unplaced_packages + [{
                    "id": package.id,
                    "reason_code": rejection_data["reason_code"],
                    "reason": rejection_data["reason"],
                    "rejection_summary": rejection_summary
                }],
                used_volume,
                total_weight
            )

            return

        for option in candidate_options:
            selected_space = option["space"]

            new_free_spaces = deepcopy(free_spaces)
            new_free_spaces.remove(selected_space)
            new_free_spaces.extend(
                split_space(
                    selected_space,
                    option["width"],
                    option["height"],
                    option["length"]
                )
            )

            destination_zone = get_destination_zone(
                package.destination,
                truck,
                destination_priority
            )

            placed_package = {
                "id": package.id,
                "x": selected_space["x"],
                "y": selected_space["y"],
                "z": selected_space["z"],
                "width": option["width"],
                "height": option["height"],
                "length": option["length"],
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
                "inside_destination_zone": option["inside_destination_zone"],
                "stacking_capacity": calculate_stacking_capacity({
                    "fragility": package.fragility,
                    "weight": package.weight
                }),
                "stacking_constraint_satisfied": option[
                    "stacking_constraint_satisfied"
                ],
                "support_ratio": option["support_ratio"],
                "minimum_support_ratio_required": MIN_SUPPORT_RATIO,
                "stability_constraint_satisfied": option[
                    "stability_constraint_satisfied"
                ],
                "content_type": package.content_type,
                "rotated": (
                    option["width"] != package.width
                    or option["height"] != package.height
                    or option["length"] != package.length
                )
            }

            backtrack(
                index + 1,
                new_free_spaces,
                placed_packages + [placed_package],
                unplaced_packages,
                used_volume + option["volume"],
                total_weight + package.weight
            )

    backtrack(
        index=0,
        free_spaces=[create_initial_space(truck)],
        placed_packages=[],
        unplaced_packages=[],
        used_volume=0,
        total_weight=0
    )

    placed_packages = best_solution["placed_packages"]
    unplaced_packages = best_solution["unplaced_packages"]
    used_volume = best_solution["used_volume"]
    total_weight = best_solution["total_weight"]

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
        "algorithm": "backtracking_logistic",
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