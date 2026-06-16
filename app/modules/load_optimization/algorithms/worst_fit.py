import time

from app.modules.load_optimization.utils.geometry import (
    create_initial_space,
    fits_in_space,
    split_space,
    space_volume,
)

from app.modules.load_optimization.utils.metrics import (
    calculate_occupation_percentage,
    calculate_weight_percentage,
    calculate_success_rate,
)


def worst_fit_algorithm(truck, packages):
    start_time = time.perf_counter()

    free_spaces = [create_initial_space(truck)]

    placed_packages = []
    unplaced_packages = []

    used_volume = 0
    total_weight = 0

    for package in packages:
        if total_weight + package.weight > truck.max_weight:
            unplaced_packages.append({
                "id": package.id,
                "reason_code": "WEIGHT_LIMIT",
                "reason": "Excede el peso máximo del camión"
            })
            continue

        candidate_spaces = [
            space for space in free_spaces
            if fits_in_space(package, space)
        ]

        if not candidate_spaces:
            unplaced_packages.append({
                "id": package.id,
                "reason_code": "NO_SPACE",
                "reason": "No hay espacio disponible"
            })
            continue

        selected_space = max(
            candidate_spaces,
            key=space_volume
        )

        placed_packages.append({
            "id": package.id,
            "x": selected_space["x"],
            "y": selected_space["y"],
            "z": selected_space["z"],
            "width": package.width,
            "height": package.height,
            "length": package.length,
            "weight": package.weight,
            "fragility": package.fragility,
            "destination": package.destination,
            "content_type": package.content_type,
            "rotated": False
        })

        used_volume += package.volume
        total_weight += package.weight

        free_spaces.remove(selected_space)
        free_spaces.extend(
            split_space(selected_space, package)
        )

    execution_time_ms = round(
        (time.perf_counter() - start_time) * 1000,
        3
    )

    return {
        "algorithm": "worst_fit",
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