
from copy import deepcopy
from time import perf_counter

from app.modules.optimization_poc.algorithms.best_fit_decreasing_3d import (
    find_placement as find_bfd_placement,
)
from app.modules.optimization_poc.algorithms.best_fit_decreasing_3d import (
    order_packages as order_bfd_packages,
)
from app.modules.optimization_poc.models import Package3D, Truck3D
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.utils.geometry import (
    create_initial_space,
    fits_dimensions_in_space,
    generate_rotations,
    space_volume,
    split_space,
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
    space_overlaps_destination_zone,
    validate_longitudinal_restraint,
    validate_no_lever_constraint,
    validate_origin_and_destinations,
    validate_stability_constraint,
    validate_stacking_constraint,
)
from app.modules.optimization_poc.utils.progressive_loading import select_progressive_placement
from app.modules.optimization_poc.validators import is_weight_allowed, recompute_supported_weights

BACKTRACKING_MAX_SECONDS = 3.0
BACKTRACKING_MAX_NODES = 25_000
BACKTRACKING_MAX_BRANCHES_PER_LEVEL = 8


def rounded(value: float) -> float:
    return round(float(value), 3)


def space_key(space: dict) -> tuple[float, float, float, float, float, float]:
    return (
        rounded(space["x"]),
        rounded(space["y"]),
        rounded(space["z"]),
        rounded(space["width"]),
        rounded(space["height"]),
        rounded(space["length"]),
    )


def option_key(option: dict) -> tuple[float, ...]:
    return (
        *space_key(option["space"]),
        rounded(option["width"]),
        rounded(option["height"]),
        rounded(option["length"]),
    )


def dedupe_candidate_options(candidate_options: list[dict]) -> list[dict]:
    unique_options: list[dict] = []
    seen: set[tuple[float, ...]] = set()

    for option in candidate_options:
        key = option_key(option)
        if key in seen:
            continue
        seen.add(key)
        unique_options.append(option)

    return unique_options


def build_state_key(
    index: int,
    free_spaces: list[dict],
    placed_packages: list[dict],
    total_weight: float,
) -> tuple:
    placed_key = tuple(
        sorted(
            (
                package["id"],
                rounded(package["x"]),
                rounded(package["y"]),
                rounded(package["z"]),
                rounded(package["width"]),
                rounded(package["height"]),
                rounded(package["length"]),
            )
            for package in placed_packages
        )
    )
    return (
        index,
        rounded(total_weight),
        tuple(sorted(space_key(space) for space in free_spaces)),
        placed_key,
    )


def build_progressive_seed(
    truck: Truck3D,
    packages: list[Package3D],
    destination_priority: dict[str, int],
) -> dict:
    ordered_seed_packages = order_bfd_packages(packages)
    pending_packages = list(enumerate(ordered_seed_packages))
    placements: list[Placement] = []
    placed_models: list[Package3D] = []
    total_weight = 0.0

    while pending_packages:
        selectable_packages = [
            item
            for item in pending_packages
            if is_weight_allowed(total_weight, item[1].weight, truck)
        ]
        if not selectable_packages:
            break

        selection = select_progressive_placement(
            pending_packages=selectable_packages,
            find_placement=find_bfd_placement,
            truck=truck,
            placements=placements,
            allow_rotation=True,
        )
        if not selection:
            break

        original_index, package, placement = selection
        placements.append(placement)
        placed_models.append(package)
        recompute_supported_weights(placements)
        total_weight += package.weight
        pending_packages = [
            item
            for item in pending_packages
            if item[0] != original_index
        ]

    package_by_id = {package.id: package for package in placed_models}
    placed_packages = [
        placement_to_logistic_dict(
            placement,
            package_by_id[placement.package_id],
            truck,
            destination_priority,
        )
        for placement in placements
    ]
    placed_ids = {package.id for package in placed_models}
    unplaced_packages = [
        {
            "id": package.id,
            "reason_code": "NO_FEASIBLE_SPACE",
            "reason": "No se encontro una posicion valida en la solucion inicial",
        }
        for package in packages
        if package.id not in placed_ids
    ]
    return {
        "placed_packages": placed_packages,
        "unplaced_packages": unplaced_packages,
        "used_volume": sum(
            package["width"] * package["height"] * package["length"]
            for package in placed_packages
        ),
        "total_weight": sum(package["weight"] for package in placed_packages),
    }


def placement_to_logistic_dict(
    placement: Placement,
    package: Package3D,
    truck: Truck3D,
    destination_priority: dict[str, int],
) -> dict:
    candidate_space = {
        "x": placement.x,
        "y": placement.y,
        "z": placement.z,
    }
    return {
        "id": package.id,
        "codigo": package.codigo,
        "description": package.descripcion,
        "delivery_order": package.orden_entrega,
        "priority": package.prioridad,
        "x": placement.x,
        "y": placement.y,
        "z": placement.z,
        "width": placement.width,
        "height": placement.height,
        "length": placement.depth,
        "weight": package.weight,
        "fragility": package.fragility,
        "destination": package.destination,
        "destination_priority": get_destination_priority(
            package.destination,
            destination_priority,
        ),
        "destination_zone": get_destination_zone(
            package.destination,
            truck,
            destination_priority,
        ),
        "inside_destination_zone": space_overlaps_destination_zone(
            candidate_space,
            placement.depth,
            package.destination,
            truck,
            destination_priority,
        ),
        "stacking_capacity": placement.stacking_capacity,
        "stacking_constraint_satisfied": True,
        "support_ratio": placement.support_ratio,
        "minimum_support_ratio_required": MIN_SUPPORT_RATIO,
        "stability_constraint_satisfied": placement.support_ratio >= MIN_SUPPORT_RATIO,
        "content_type": package.content_type,
        "supported_weight": placement.supported_weight,
        "rotated": placement.orientation != "LWH",
    }


def get_backtracking_rejection_data(rejection_summary: dict) -> dict:
    if rejection_summary["stability_rejections"] > 0:
        return {
            "reason_code": "STABILITY_CONSTRAINT",
            "reason": "No cumple restriccion de estabilidad minima",
        }

    if rejection_summary["stacking_rejections"] > 0:
        return {
            "reason_code": "STACKING_CONSTRAINT",
            "reason": "No cumple restriccion de estiba por peso y fragilidad",
        }

    if rejection_summary["dimension_rejections"] > 0:
        return {
            "reason_code": "NO_SPACE",
            "reason": "No hay espacio disponible",
        }

    return {
        "reason_code": "LOGISTIC_CONSTRAINT",
        "reason": (
            "No hay espacio disponible o no cumple "
            "restricciones logisticas"
        ),
    }


def clone_free_spaces(free_spaces: list[dict]) -> list[dict]:
    """
    Crea una copia independiente y ligera de la lista de espacios libres.

    Cada espacio actualmente contiene valores simples, por lo que dict.copy()
    es suficiente y evita el costo de deepcopy en cada rama.
    """
    return [space.copy() for space in free_spaces]


def clone_placed_packages(
    placed_packages: list[dict],
) -> list[dict]:
    """
    Crea una copia independiente de los paquetes colocados.

    Esto es obligatorio porque register_supported_weight modifica
    supported_weight en los paquetes que soportan al nuevo paquete.

    Cada rama del backtracking debe conservar sus propios valores.
    """
    return [
        placed_package.copy()
        for placed_package in placed_packages
    ]


def backtracking_3d_algorithm(
    truck: Truck3D,
    packages: list[Package3D],
    route: str = DEFAULT_ROUTE,
    origin_agency: str = "TRUJILLO",
) -> dict:
    started = perf_counter()

    selected_route = get_route(route)
    normalized_origin = normalize_text(origin_agency)

    validate_origin_and_destinations(
        selected_route,
        normalized_origin,
        packages,
    )

    destination_priority = build_destination_priority(
        route,
        normalized_origin,
    )

    ordered_packages = sorted(
        packages,
        key=lambda package: (
            -get_destination_priority(
                package.destination,
                destination_priority,
            ),
            -package.volume,
            -package.weight,
            package.codigo,
        ),
    )

    best_solution = build_progressive_seed(
        truck,
        ordered_packages,
        destination_priority,
    )
    search_stats = {
        "visited_nodes": 0,
        "pruned_by_bound": 0,
        "pruned_by_seen_state": 0,
        "candidate_options_trimmed": 0,
        "interrupted": False,
    }
    seen_states: dict[tuple, tuple[int, float]] = {}

    def should_stop_search() -> bool:
        if (perf_counter() - started) >= BACKTRACKING_MAX_SECONDS:
            search_stats["interrupted"] = True
            return True
        if search_stats["visited_nodes"] >= BACKTRACKING_MAX_NODES:
            search_stats["interrupted"] = True
            return True
        return False

    def is_better_solution(
        current_solution: dict,
        current_best_solution: dict,
    ) -> bool:
        current_placed_count = len(
            current_solution["placed_packages"]
        )
        best_placed_count = len(
            current_best_solution["placed_packages"]
        )

        if current_placed_count > best_placed_count:
            return True

        if current_placed_count == best_placed_count:
            return (
                current_solution["used_volume"]
                > current_best_solution["used_volume"]
            )

        return False

    def backtrack(
        index: int,
        free_spaces: list[dict],
        placed_packages: list[dict],
        unplaced_packages: list[dict],
        used_volume: float,
        total_weight: float,
    ) -> None:
        nonlocal best_solution

        if should_stop_search():
            return

        search_stats["visited_nodes"] += 1

        maximum_possible_count = len(placed_packages) + (len(ordered_packages) - index)
        if maximum_possible_count < len(best_solution["placed_packages"]):
            search_stats["pruned_by_bound"] += 1
            return

        state_key = build_state_key(
            index,
            free_spaces,
            placed_packages,
            total_weight,
        )
        state_quality = (len(placed_packages), rounded(used_volume))
        previous_quality = seen_states.get(state_key)
        if previous_quality is not None and previous_quality >= state_quality:
            search_stats["pruned_by_seen_state"] += 1
            return
        seen_states[state_key] = state_quality

        if index >= len(ordered_packages):
            current_solution = {
                "placed_packages": placed_packages,
                "unplaced_packages": unplaced_packages,
                "used_volume": used_volume,
                "total_weight": total_weight,
            }

            if is_better_solution(
                current_solution,
                best_solution,
            ):
                # Aquí se mantiene deepcopy porque best_solution debe
                # conservarse aunque las ramas siguientes modifiquen
                # sus estructuras temporales.
                best_solution = deepcopy(current_solution)

            return

        package = ordered_packages[index]

        if total_weight + package.weight > truck.max_weight:
            backtrack(
                index=index + 1,
                free_spaces=free_spaces,
                placed_packages=placed_packages,
                unplaced_packages=unplaced_packages
                + [
                    {
                        "id": package.id,
                        "reason_code": "WEIGHT_LIMIT",
                        "reason": (
                            "Excede el peso maximo del camion"
                        ),
                    }
                ],
                used_volume=used_volume,
                total_weight=total_weight,
            )
            return

        candidate_options: list[dict] = []

        rejection_summary = {
            "dimension_rejections": 0,
            "stacking_rejections": 0,
            "stability_rejections": 0,
        }

        for (
            rotated_width,
            rotated_height,
            rotated_length,
        ) in generate_rotations(package):
            rotated_volume = (
                rotated_width
                * rotated_height
                * rotated_length
            )

            for space_index, space in enumerate(free_spaces):
                if not fits_dimensions_in_space(
                    rotated_width,
                    rotated_height,
                    rotated_length,
                    space,
                ):
                    rejection_summary[
                        "dimension_rejections"
                    ] += 1
                    continue

                if not validate_stacking_constraint(
                    candidate_space=space,
                    candidate_weight=package.weight,
                    candidate_width=rotated_width,
                    candidate_length=rotated_length,
                    placed_packages=placed_packages,
                ):
                    rejection_summary[
                        "stacking_rejections"
                    ] += 1
                    continue

                if not validate_stability_constraint(
                    candidate_space=space,
                    candidate_width=rotated_width,
                    candidate_length=rotated_length,
                    placed_packages=placed_packages,
                ):
                    rejection_summary[
                        "stability_rejections"
                    ] += 1
                    continue

                # R1 (sujecion longitudinal) y R3 (anti-palanca). La R2 (electronico
                # plano parado) se aplica antes en generate_rotations.
                if not validate_longitudinal_restraint(
                    candidate_space=space,
                    candidate_width=rotated_width,
                    candidate_height=rotated_height,
                    candidate_length=rotated_length,
                    placed_packages=placed_packages,
                    truck=truck,
                ):
                    rejection_summary[
                        "stability_rejections"
                    ] += 1
                    continue

                if not validate_no_lever_constraint(
                    candidate_space=space,
                    candidate_width=rotated_width,
                    candidate_length=rotated_length,
                    placed_packages=placed_packages,
                ):
                    rejection_summary[
                        "stability_rejections"
                    ] += 1
                    continue

                inside_destination_zone = (
                    space_overlaps_destination_zone(
                        space,
                        rotated_length,
                        package.destination,
                        truck,
                        destination_priority,
                    )
                )

                zone_penalty = (
                    calculate_zone_distance_penalty(
                        space,
                        rotated_length,
                        package.destination,
                        truck,
                        destination_priority,
                    )
                )

                support_ratio = calculate_support_ratio(
                    space,
                    rotated_width,
                    rotated_length,
                    placed_packages,
                )

                remaining_volume = (
                    space_volume(space) - rotated_volume
                )

                candidate_options.append(
                    {
                        "space_index": space_index,
                        "space": space,
                        "width": rotated_width,
                        "height": rotated_height,
                        "length": rotated_length,
                        "volume": rotated_volume,
                        "remaining_volume": remaining_volume,
                        "zone_penalty": zone_penalty,
                        "optimization_score": (
                            remaining_volume + zone_penalty
                        ),
                        "inside_destination_zone": (
                            inside_destination_zone
                        ),
                        "support_ratio": support_ratio,
                        "stacking_constraint_satisfied": True,
                        "stability_constraint_satisfied": (
                            support_ratio
                            >= MIN_SUPPORT_RATIO
                        ),
                    }
                )

        candidate_options = filter_candidate_options_by_loading_frontier(
            candidate_options,
            placed_packages,
        )

        candidate_options = dedupe_candidate_options(
            candidate_options
        )

        candidate_options.sort(
            key=lambda option: (
                not option["inside_destination_zone"],
                option["zone_penalty"],
                option["space"]["z"],
                option["space"]["y"],
                option["space"]["x"],
                option["optimization_score"],
            )
        )

        if len(candidate_options) > BACKTRACKING_MAX_BRANCHES_PER_LEVEL:
            search_stats["candidate_options_trimmed"] += (
                len(candidate_options) - BACKTRACKING_MAX_BRANCHES_PER_LEVEL
            )
            candidate_options = candidate_options[
                :BACKTRACKING_MAX_BRANCHES_PER_LEVEL
            ]

        if not candidate_options:
            rejection_data = (
                get_backtracking_rejection_data(
                    rejection_summary
                )
            )

            backtrack(
                index=index + 1,
                free_spaces=free_spaces,
                placed_packages=placed_packages,
                unplaced_packages=unplaced_packages
                + [
                    {
                        "id": package.id,
                        "reason_code": rejection_data[
                            "reason_code"
                        ],
                        "reason": rejection_data["reason"],
                        "rejection_summary": (
                            rejection_summary.copy()
                        ),
                    }
                ],
                used_volume=used_volume,
                total_weight=total_weight,
            )
            return

        for option in candidate_options:
            if should_stop_search():
                break

            selected_space = option["space"]
            selected_space_index = option["space_index"]

            # Copia ligera de la lista de espacios.
            new_free_spaces = clone_free_spaces(
                free_spaces
            )

            # Se elimina exactamente el espacio usado.
            if (
                selected_space_index < 0
                or selected_space_index
                >= len(new_free_spaces)
            ):
                continue

            new_free_spaces.pop(selected_space_index)

            generated_spaces = split_space(
                selected_space,
                option["width"],
                option["height"],
                option["length"],
            )

            # Los espacios generados también se copian para
            # asegurar que la rama mantenga estado independiente.
            new_free_spaces.extend(
                generated_space.copy()
                for generated_space in generated_spaces
            )

            placed_package = {
                "id": package.id,
                "codigo": package.codigo,
                "description": package.descripcion,
                "delivery_order": package.orden_entrega,
                "priority": package.prioridad,
                "x": selected_space["x"],
                "y": selected_space["y"],
                "z": selected_space["z"],
                "width": option["width"],
                "height": option["height"],
                "length": option["length"],
                "weight": package.weight,
                "fragility": package.fragility,
                "destination": package.destination,
                "destination_priority": (
                    get_destination_priority(
                        package.destination,
                        destination_priority,
                    )
                ),
                "destination_zone": get_destination_zone(
                    package.destination,
                    truck,
                    destination_priority,
                ),
                "inside_destination_zone": option[
                    "inside_destination_zone"
                ],
                "stacking_capacity": (
                    calculate_stacking_capacity(
                        {
                            "fragility": (
                                package.fragility
                            ),
                            "weight": package.weight,
                        }
                    )
                ),
                "stacking_constraint_satisfied": option[
                    "stacking_constraint_satisfied"
                ],
                "support_ratio": option["support_ratio"],
                "minimum_support_ratio_required": (
                    MIN_SUPPORT_RATIO
                ),
                "stability_constraint_satisfied": option[
                    "stability_constraint_satisfied"
                ],
                "content_type": package.content_type,
                "supported_weight": 0.0,
                "rotated": (
                    option["width"] != package.width
                    or option["height"] != package.height
                    or option["length"] != package.length
                ),
            }

            # Cada rama recibe sus propios diccionarios.
            new_placed_packages = clone_placed_packages(
                placed_packages
            )

            # Esta función debe mantenerse: actualiza el peso
            # acumulado soportado por los paquetes inferiores.
            register_supported_weight(
                placed_package,
                new_placed_packages,
            )

            new_placed_packages.append(
                placed_package
            )

            backtrack(
                index=index + 1,
                free_spaces=new_free_spaces,
                placed_packages=new_placed_packages,
                unplaced_packages=unplaced_packages,
                used_volume=(
                    used_volume + option["volume"]
                ),
                total_weight=(
                    total_weight + package.weight
                ),
            )

        # También se explora la rama donde el paquete actual
        # no se coloca. Esto permite encontrar soluciones donde
        # rechazar un paquete deja espacio para más paquetes
        # posteriores.
        if not should_stop_search():
            backtrack(
                index=index + 1,
                free_spaces=free_spaces,
                placed_packages=placed_packages,
                unplaced_packages=unplaced_packages
                + [
                    {
                        "id": package.id,
                        "reason_code": "SKIPPED_BY_SEARCH",
                        "reason": (
                            "Paquete omitido durante la busqueda "
                            "para evaluar una solucion alternativa"
                        ),
                    }
                ],
                used_volume=used_volume,
                total_weight=total_weight,
            )

    if len(best_solution["placed_packages"]) < len(ordered_packages):
        backtrack(
            index=0,
            free_spaces=[create_initial_space(truck)],
            placed_packages=[],
            unplaced_packages=[],
            used_volume=0.0,
            total_weight=0.0,
        )

    placed_packages = best_solution[
        "placed_packages"
    ]
    unplaced_packages = best_solution[
        "unplaced_packages"
    ]
    used_volume = best_solution["used_volume"]
    total_weight = best_solution["total_weight"]

    execution_time_ms = round(
        (perf_counter() - started) * 1000,
        3,
    )

    zone_compliance_count = sum(
        1
        for placed_package in placed_packages
        if placed_package[
            "inside_destination_zone"
        ]
    )

    stacking_compliance_count = sum(
        1
        for placed_package in placed_packages
        if placed_package[
            "stacking_constraint_satisfied"
        ]
    )

    stability_compliance_count = sum(
        1
        for placed_package in placed_packages
        if placed_package[
            "stability_constraint_satisfied"
        ]
    )

    placed_count = len(placed_packages)

    zone_compliance_percentage = (
        round(
            (
                zone_compliance_count
                / placed_count
            )
            * 100,
            2,
        )
        if placed_count
        else 0
    )

    stacking_compliance_percentage = (
        round(
            (
                stacking_compliance_count
                / placed_count
            )
            * 100,
            2,
        )
        if placed_count
        else 0
    )

    stability_compliance_percentage = (
        round(
            (
                stability_compliance_count
                / placed_count
            )
            * 100,
            2,
        )
        if placed_count
        else 0
    )

    return {
        "algorithm": "backtracking_logistic",
        "route": route,
        "origin_agency": normalized_origin,
        "destination_order_applied": True,
        "destination_zone_constraint_applied": True,
        "destination_spatial_preference_applied": True,
        "stacking_constraint_applied": True,
        "stability_constraint_applied": True,
        "minimum_support_ratio_required": (
            MIN_SUPPORT_RATIO
        ),
        "destination_priority": (
            destination_priority
        ),
        "unloading_assumption": (
            UNLOADING_ASSUMPTION
        ),
        "zone_compliance_percentage": (
            zone_compliance_percentage
        ),
        "stacking_compliance_percentage": (
            stacking_compliance_percentage
        ),
        "stability_compliance_percentage": (
            stability_compliance_percentage
        ),
        "execution_time_ms": execution_time_ms,
        "used_volume": used_volume,
        "truck_volume": truck.volume,
        "total_weight": total_weight,
        "max_weight": truck.max_weight,
        "placed_count": placed_count,
        "unplaced_count": len(
            unplaced_packages
        ),
        "placed_packages": placed_packages,
        "unplaced_packages": (
            unplaced_packages
        ),
        "ordered_packages": (
            ordered_packages
        ),
        "search_stats": {
            **search_stats,
            "max_seconds": BACKTRACKING_MAX_SECONDS,
            "max_nodes": BACKTRACKING_MAX_NODES,
            "max_branches_per_level": BACKTRACKING_MAX_BRANCHES_PER_LEVEL,
            "seen_states": len(seen_states),
        },
    }
