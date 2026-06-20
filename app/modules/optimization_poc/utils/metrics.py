from app.modules.optimization_poc.models import Package3D, Truck3D, truck_volume
from app.modules.optimization_poc.schema import Metrics, Placement
from app.modules.optimization_poc.validators import has_overlap, is_inside_truck


def calculate_metrics(
    *,
    truck: Truck3D,
    ordered_packages: list[Package3D],
    placements: list[Placement],
    unplaced_packages: list[Package3D],
    execution_ms: int,
) -> Metrics:
    used_volume = sum(item.width * item.height * item.depth for item in placements)
    total_weight = sum(item.peso_kg for item in placements)
    boundary_violations = sum(
        0 if is_inside_truck(item.x, item.y, item.z, item.width, item.height, item.depth, truck) else 1
        for item in placements
    )
    overlap_violations = sum(1 for index, item in enumerate(placements) if has_overlap(item, placements[index + 1 :]))
    delivery_penalty = sum(item.delivery_order * item.z for item in placements) / max(len(placements), 1)
    rotation_count = sum(1 for item in placements if item.orientation != "LWH")
    average_distance = sum(item.z for item in placements) / max(len(placements), 1)
    total_truck_volume = truck_volume(truck)
    return Metrics(
        execution_ms=execution_ms,
        truck_volume_cm3=total_truck_volume,
        used_volume_cm3=used_volume,
        utilization_percent=round((used_volume / total_truck_volume) * 100, 2) if total_truck_volume else 0,
        placed_count=len(placements),
        unplaced_count=len(unplaced_packages),
        total_weight_kg=round(total_weight, 2),
        overlap_violations=overlap_violations,
        boundary_violations=boundary_violations,
        delivery_order_penalty=round(delivery_penalty, 2),
        rotation_count=rotation_count,
        average_delivery_distance_cm=round(average_distance, 2),
    )
