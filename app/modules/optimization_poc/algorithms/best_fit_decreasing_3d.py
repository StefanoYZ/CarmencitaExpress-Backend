from time import perf_counter

from app.modules.optimization_poc.models import Package3D, Truck3D, destination_rank
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.utils.geometry import (
    contact_score,
    create_initial_space,
    dense_valid_candidates,
    fits_dimensions_in_space,
    generate_rotations,
    space_volume,
    split_space,
    support_ratio,
)
from app.modules.optimization_poc.utils.logistic_rules import (
    DEFAULT_ROUTE,
    MIN_SUPPORT_RATIO,
    UNLOADING_ASSUMPTION,
    build_destination_priority,
    calculate_stacking_capacity,
    calculate_support_ratio,
    calculate_zone_distance_penalty,
    filter_candidate_options_by_loading_frontier,
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


def order_packages(packages: list[Package3D]) -> list[Package3D]:
    return sorted(
        packages,
        key=lambda package: (
            -destination_rank(package),
            -package.volume,
            -package.weight,
            package.codigo,
        ),
    )


def find_placement(
    package: Package3D,
    truck: Truck3D,
    placed: list[Placement],
    sequence: int,
    allow_rotation: bool,
) -> Placement | None:
    candidates = dense_valid_candidates(
        package,
        truck,
        placed,
        sequence,
        allow_rotation,
    )
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: _placement_score(candidate, truck, placed))


def _placement_score(
    candidate: Placement,
    truck: Truck3D,
    placed: list[Placement],
) -> tuple[float, ...]:
    projected_depth = max(
        [candidate.z + candidate.depth, *[item.z + item.depth for item in placed]]
    )
    projected_width = max(
        [candidate.x + candidate.width, *[item.x + item.width for item in placed]]
    )
    projected_height = max(
        [candidate.y + candidate.height, *[item.y + item.height for item in placed]]
    )
    return (
        round(projected_depth / max(truck.largo_cm, 1.0), 6),
        round(
            _projected_void_ratio(
                candidate,
                placed,
                projected_width,
                projected_height,
                projected_depth,
            ),
            6,
        ),
        round(1.0 - contact_score(candidate, truck, placed), 6),
        round(1.0 - support_ratio(candidate, placed), 6),
        round(candidate.y, 3),
        round(candidate.x, 3),
    )


def _projected_void_ratio(
    candidate: Placement,
    placed: list[Placement],
    projected_width: float,
    projected_height: float,
    projected_depth: float,
) -> float:
    envelope_volume = projected_width * projected_height * projected_depth
    if envelope_volume <= 0:
        return 0.0

    occupied_volume = candidate.width * candidate.height * candidate.depth
    occupied_volume += sum(item.width * item.height * item.depth for item in placed)
    return max(envelope_volume - occupied_volume, 0.0) / envelope_volume


def best_fit_decreasing_3d_algorithm(
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
            -get_destination_priority(package.destination, destination_priority),
            -package.volume,
            -package.weight,
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

                inside_destination_zone = space_overlaps_destination_zone(
                    space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority,
                )
                zone_penalty = calculate_zone_distance_penalty(
                    space,
                    rotated_length,
                    package.destination,
                    truck,
                    destination_priority,
                )
                remaining_volume = space_volume(space) - rotated_volume
                support_ratio = calculate_support_ratio(
                    space,
                    rotated_width,
                    rotated_length,
                    placed_packages,
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
                        "optimization_score": remaining_volume + zone_penalty,
                        "inside_destination_zone": inside_destination_zone,
                        "support_ratio": support_ratio,
                        "stacking_constraint_satisfied": True,
                        "stability_constraint_satisfied": support_ratio >= MIN_SUPPORT_RATIO,
                    }
                )

        candidate_options = filter_candidate_options_by_loading_frontier(candidate_options, placed_packages)
        candidate_options = sorted(
            candidate_options,
            key=lambda option: (
                not option["inside_destination_zone"],
                option["zone_penalty"],
                option["space"]["z"],
                option["space"]["y"],
                option["space"]["x"],
                option["remaining_volume"],
            ),
        )

        if not candidate_options:
            unplaced_packages.append(
                {
                    "id": package.id,
                    "reason_code": "NO_FEASIBLE_SPACE",
                    "reason": "No se encontro un espacio valido segun las restricciones logisticas",
                    "rejection_summary": rejection_summary,
                }
            )
            continue

        selected_option = candidate_options[0]
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
            "stacking_constraint_satisfied": selected_option["stacking_constraint_satisfied"],
            "support_ratio": selected_option["support_ratio"],
            "minimum_support_ratio_required": MIN_SUPPORT_RATIO,
            "stability_constraint_satisfied": selected_option["stability_constraint_satisfied"],
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

    zone_compliance_count = sum(1 for package in placed_packages if package["inside_destination_zone"])
    stacking_compliance_count = sum(
        1 for package in placed_packages if package["stacking_constraint_satisfied"]
    )
    stability_compliance_count = sum(
        1 for package in placed_packages if package["stability_constraint_satisfied"]
    )

    return {
        "algorithm": "best_fit_decreasing_3d",
        "route": route,
        "origin_agency": normalized_origin,
        "destination_order_applied": True,
        "destination_spatial_preference_applied": True,
        "stacking_constraint_applied": True,
        "stability_constraint_applied": True,
        "minimum_support_ratio_required": MIN_SUPPORT_RATIO,
        "destination_priority": destination_priority,
        "unloading_assumption": UNLOADING_ASSUMPTION,
        "zone_compliance_percentage": round((zone_compliance_count / len(placed_packages)) * 100, 2)
        if placed_packages
        else 0,
        "stacking_compliance_percentage": round((stacking_compliance_count / len(placed_packages)) * 100, 2)
        if placed_packages
        else 0,
        "stability_compliance_percentage": round((stability_compliance_count / len(placed_packages)) * 100, 2)
        if placed_packages
        else 0,
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
