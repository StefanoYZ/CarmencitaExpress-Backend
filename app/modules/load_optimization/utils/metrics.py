def calculate_used_volume(placed_packages: list) -> float:
    used_volume = 0

    for package in placed_packages:
        used_volume += (
            package["width"]
            * package["height"]
            * package["length"]
        )

    return used_volume


def calculate_occupation_percentage(
    used_volume: float,
    truck_volume: float
) -> float:
    if truck_volume <= 0:
        return 0

    return round((used_volume / truck_volume) * 100, 2)


def calculate_remaining_volume(
    truck_volume: float,
    used_volume: float
) -> float:
    remaining_volume = truck_volume - used_volume

    if remaining_volume < 0:
        return 0

    return remaining_volume


def calculate_weight_percentage(
    total_weight: float,
    max_weight: float
) -> float:
    if max_weight <= 0:
        return 0

    return round((total_weight / max_weight) * 100, 2)


def calculate_placed_count(placed_packages: list) -> int:
    return len(placed_packages)


def calculate_unplaced_count(unplaced_packages: list) -> int:
    return len(unplaced_packages)


def calculate_success_rate(
    placed_packages: list,
    unplaced_packages: list
) -> float:
    total_packages = len(placed_packages) + len(unplaced_packages)

    if total_packages == 0:
        return 0

    return round((len(placed_packages) / total_packages) * 100, 2)


def build_optimization_metrics(
    placed_packages: list,
    unplaced_packages: list,
    truck_volume: float,
    used_volume: float,
    total_weight: float,
    max_weight: float,
    execution_time_ms: float
) -> dict:
    return {
        "occupation_percentage": calculate_occupation_percentage(
            used_volume,
            truck_volume
        ),
        "remaining_volume": calculate_remaining_volume(
            truck_volume,
            used_volume
        ),
        "weight_percentage": calculate_weight_percentage(
            total_weight,
            max_weight
        ),
        "placed_count": calculate_placed_count(
            placed_packages
        ),
        "unplaced_count": calculate_unplaced_count(
            unplaced_packages
        ),
        "success_rate": calculate_success_rate(
            placed_packages,
            unplaced_packages
        ),
        "execution_time_ms": execution_time_ms
    }