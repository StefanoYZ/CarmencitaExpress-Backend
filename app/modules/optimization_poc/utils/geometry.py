from itertools import permutations

from app.modules.optimization_poc.models.package import Package3D, destination_rank, is_upright_appliance
from app.modules.optimization_poc.models.truck import Truck3D, target_z_from_rank
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.validators import (
    has_lateral_support_for_vertical_thin,
    has_minimum_support,
    has_overlap,
    is_inside_truck,
    respects_fragility,
    stacking_capacity_for_fragility,
)

THINNESS_RATIO_THRESHOLD = 4.0
LOADING_FRONTIER_EPSILON_CM = 0.001


def build_candidate(
    package: Package3D,
    sequence: int,
    x: float,
    y: float,
    z: float,
    width: float,
    height: float,
    depth: float,
    orientation: str,
) -> Placement:
    return Placement(
        package_id=package.id,
        codigo=package.codigo,
        loading_sequence=sequence,
        delivery_order=package.orden_entrega,
        x=x,
        y=y,
        z=z,
        width=width,
        height=height,
        depth=depth,
        orientation=orientation,
        destination=package.destino,
        fragility=package.fragilidad,
        peso_kg=package.peso_kg,
        descripcion=package.descripcion,
        stacking_capacity=stacking_capacity_for_fragility(package.fragilidad, package.peso_kg),
    )


def orientations(package: Package3D, allow_rotation: bool) -> list[tuple[float, float, float, str]]:
    base = (package.ancho_cm, package.alto_cm, package.largo_cm)
    if not allow_rotation or is_upright_appliance(package):
        return [(base[0], base[1], base[2], "LWH")]

    if not package.permite_rotacion:
        if allows_controlled_thin_rotation(package):
            return controlled_thin_rotations(base)
        return [(base[0], base[1], base[2], "LWH")]

    labels = ["WHD", "WDH", "HWD", "HDW", "DWH", "DHW"]
    results: list[tuple[float, float, float, str]] = []
    seen = set()

    for index, dims in enumerate(permutations(base, 3)):
        if dims in seen:
            continue
        seen.add(dims)
        results.append((dims[0], dims[1], dims[2], labels[min(index, len(labels) - 1)]))
    return sorted(results, key=lambda item: orientation_sort_key(item[0], item[1], item[2]))


def orientation_sort_key(width: float, height: float, depth: float) -> tuple[float, float, float, float]:
    footprint = width * depth
    return (-footprint, height, -max(width, depth), -min(width, depth))


def allows_controlled_thin_rotation(package: Package3D) -> bool:
    dimensions = [package.ancho_cm, package.alto_cm, package.largo_cm]
    min_dimension = min(dimensions)
    max_dimension = max(dimensions)
    is_thin = (max_dimension / max(min_dimension, 1.0)) >= THINNESS_RATIO_THRESHOLD
    return package.fragilidad in {"ALTA", "MEDIA"} and is_thin


def controlled_thin_rotations(base: tuple[float, float, float]) -> list[tuple[float, float, float, str]]:
    max_dimension = max(base)
    min_dimension = min(base)
    candidates = []
    for rotated_width, rotated_height, rotated_depth in permutations(base, 3):
        if rotated_height == max_dimension:
            label = "VERTICAL"
        elif rotated_height == min_dimension:
            label = "HORIZONTAL"
        else:
            label = "SIDE"
        candidates.append((rotated_width, rotated_height, rotated_depth, label))

    deduped: dict[tuple[float, float, float], tuple[float, float, float, str]] = {}
    for rotated_width, rotated_height, rotated_depth, label in candidates:
        deduped.setdefault((rotated_width, rotated_height, rotated_depth), (rotated_width, rotated_height, rotated_depth, label))
    return sorted(deduped.values(), key=lambda item: orientation_sort_key(item[0], item[1], item[2]))


def support_ratio(candidate: Placement, placed: list[Placement]) -> float:
    if candidate.y == 0:
        return 1.0

    base_area = candidate.width * candidate.depth
    if base_area <= 0:
        return 0.0

    supported_area = 0.0
    for current in placed:
        if abs((current.y + current.height) - candidate.y) > 0.001:
            continue
        overlap_x = max(0.0, min(candidate.x + candidate.width, current.x + current.width) - max(candidate.x, current.x))
        overlap_z = max(0.0, min(candidate.z + candidate.depth, current.z + current.depth) - max(candidate.z, current.z))
        supported_area += overlap_x * overlap_z
    return min(1.0, supported_area / base_area)


def projected_bounding_volume(candidate: Placement, placed: list[Placement]) -> float:
    max_x = max([candidate.x + candidate.width, *[item.x + item.width for item in placed]])
    max_y = max([candidate.y + candidate.height, *[item.y + item.height for item in placed]])
    max_z = max([candidate.z + candidate.depth, *[item.z + item.depth for item in placed]])
    return max_x * max_y * max_z


def route_alignment_penalty(candidate: Placement, truck: Truck3D) -> float:
    target_z = target_z_from_rank(destination_rank(candidate), truck, candidate.depth)
    return abs(candidate.z - target_z) / max(truck.largo_cm, 1.0)


def loading_flow_key(candidate: Placement, truck: Truck3D, placed: list[Placement]) -> tuple[float, float, float, float, float, float]:
    support_penalty = 1.0 - support_ratio(candidate, placed)
    contact_penalty = 1.0 - contact_score(candidate, truck, placed)
    route_penalty = route_alignment_penalty(candidate, truck)
    return (
        round(candidate.z / max(truck.largo_cm, 1.0), 6),
        round(candidate.y / max(truck.alto_cm, 1.0), 6),
        round(candidate.x / max(truck.ancho_cm, 1.0), 6),
        round(route_penalty, 6),
        round(support_penalty, 6),
        round(contact_penalty, 6),
    )


def contact_score(candidate: Placement, truck: Truck3D, placed: list[Placement]) -> float:
    score = 0.0
    tolerance = 0.001

    if candidate.y <= tolerance:
        score += 1.0
    if candidate.x <= tolerance:
        score += 0.35
    if abs(candidate.x + candidate.width - truck.ancho_cm) <= tolerance:
        score += 0.35
    if candidate.z <= tolerance:
        score += 0.45
    if abs(candidate.z + candidate.depth - truck.largo_cm) <= tolerance:
        score += 0.45

    candidate_x1 = candidate.x
    candidate_x2 = candidate.x + candidate.width
    candidate_y1 = candidate.y
    candidate_y2 = candidate.y + candidate.height
    candidate_z1 = candidate.z
    candidate_z2 = candidate.z + candidate.depth

    for item in placed:
        item_x1 = item.x
        item_x2 = item.x + item.width
        item_y1 = item.y
        item_y2 = item.y + item.height
        item_z1 = item.z
        item_z2 = item.z + item.depth

        overlap_x = max(0.0, min(candidate_x2, item_x2) - max(candidate_x1, item_x1))
        overlap_y = max(0.0, min(candidate_y2, item_y2) - max(candidate_y1, item_y1))
        overlap_z = max(0.0, min(candidate_z2, item_z2) - max(candidate_z1, item_z1))

        if abs(candidate_y1 - item_y2) <= tolerance and overlap_x > 0 and overlap_z > 0:
            score += min(1.0, (overlap_x * overlap_z) / max(candidate.width * candidate.depth, 1.0))
        if abs(candidate_x1 - item_x2) <= tolerance and overlap_y > 0 and overlap_z > 0:
            score += 0.4 * min(1.0, (overlap_y * overlap_z) / max(candidate.height * candidate.depth, 1.0))
        if abs(candidate_x2 - item_x1) <= tolerance and overlap_y > 0 and overlap_z > 0:
            score += 0.4 * min(1.0, (overlap_y * overlap_z) / max(candidate.height * candidate.depth, 1.0))
        if abs(candidate_z1 - item_z2) <= tolerance and overlap_x > 0 and overlap_y > 0:
            score += 0.45 * min(1.0, (overlap_x * overlap_y) / max(candidate.width * candidate.height, 1.0))
        if abs(candidate_z2 - item_z1) <= tolerance and overlap_x > 0 and overlap_y > 0:
            score += 0.45 * min(1.0, (overlap_x * overlap_y) / max(candidate.width * candidate.height, 1.0))

    return min(4.0, score) / 4.0


def candidate_points(
    placed: list[Placement],
    truck: Truck3D,
    width: float,
    depth: float,
    package: Package3D,
) -> list[tuple[float, float, float]]:
    target_z = target_z_from_rank(destination_rank(package), truck, depth)
    points = {(0.0, 0.0, 0.0), (0.0, 0.0, target_z)}

    for item in placed:
        points.add((item.x + item.width, item.y, item.z))
        points.add((item.x, item.y, item.z + item.depth))
        points.add((item.x + item.width, item.y, item.z + item.depth))
        points.add((item.x, item.y + item.height, item.z))
        points.add((item.x, item.y + item.height, item.z + item.depth))
        points.add((item.x + item.width, item.y + item.height, item.z))

    valid_points = [
        point
        for point in points
        if point[0] >= 0
        and point[1] >= 0
        and point[2] >= 0
        and point[0] + width <= truck.ancho_cm
        and point[2] + depth <= truck.largo_cm
    ]
    return sorted(valid_points, key=lambda point: candidate_point_sort_key(point, truck, package, depth))


def dense_candidate_points(
    placed: list[Placement],
    truck: Truck3D,
    width: float,
    height: float,
    depth: float,
    package: Package3D,
) -> list[tuple[float, float, float]]:
    target_z = target_z_from_rank(destination_rank(package), truck, depth)
    points = {(0.0, 0.0, 0.0), (0.0, 0.0, target_z)}
    z_values = {0.0, target_z, max(truck.largo_cm - depth, 0.0)}

    for item in placed:
        right_x = item.x + item.width
        back_z = item.z + item.depth
        top_y = item.y + item.height
        z_values.update(
            {
                item.z,
                back_z,
                max(item.z - depth, 0.0),
                max(back_z - depth, 0.0),
            }
        )
        points.update(
            {
                (right_x, item.y, item.z),
                (item.x, item.y, back_z),
                (right_x, item.y, back_z),
                (item.x, top_y, item.z),
                (item.x, top_y, back_z),
                (right_x, top_y, item.z),
            }
        )

    bounded_z_values = sorted(
        z
        for z in z_values
        if z >= 0 and z + depth <= truck.largo_cm
    )
    for z in bounded_z_values:
        intersecting_items = [
            item
            for item in placed
            if item.y < height
            and item.z < z + depth
            and z < item.z + item.depth
        ]
        local_x_values = {0.0, max(truck.ancho_cm - width, 0.0)}
        for item in intersecting_items:
            local_x_values.add(item.x + item.width)
            local_x_values.add(max(item.x - width, 0.0))

        for x in local_x_values:
            if x < 0 or x + width > truck.ancho_cm:
                continue
            has_planar_overlap = any(
                x < item.x + item.width
                and item.x < x + width
                for item in intersecting_items
            )
            if not has_planar_overlap:
                points.add((x, 0.0, z))

    for item in placed:
        top_y = item.y + item.height
        local_x_values = {
            item.x,
            max(item.x + item.width - width, 0.0),
            item.x + item.width,
            max(item.x - width, 0.0),
        }
        local_z_values = {
            item.z,
            item.z + item.depth,
            max(item.z - depth, 0.0),
            max(item.z + item.depth - depth, 0.0),
            target_z,
        }
        for x in local_x_values:
            for z in local_z_values:
                points.add((x, top_y, z))

    valid_points = [
        point
        for point in points
        if point[0] >= 0
        and point[1] >= 0
        and point[2] >= 0
        and point[0] + width <= truck.ancho_cm
        and point[2] + depth <= truck.largo_cm
    ]
    return sorted(valid_points, key=lambda point: dense_candidate_point_sort_key(point, truck, package, width, depth))


def candidate_point_sort_key(
    point: tuple[float, float, float],
    truck: Truck3D,
    package: Package3D,
    depth: float,
) -> tuple[float, float, float, float]:
    route_penalty = route_point_penalty(point[2], depth, package, truck)
    return (point[2], point[1], point[0], route_penalty)


def dense_candidate_point_sort_key(
    point: tuple[float, float, float],
    truck: Truck3D,
    package: Package3D,
    width: float,
    depth: float,
) -> tuple[float, float, float, float, float]:
    route_penalty = route_point_penalty(point[2], depth, package, truck)
    side_gap = min(point[0], max(truck.ancho_cm - (point[0] + width), 0.0))
    return (point[2], point[1], point[0], route_penalty, side_gap)


def route_point_penalty(z: float, depth: float, package: Package3D, truck: Truck3D) -> float:
    target_z = target_z_from_rank(destination_rank(package), truck, depth)
    return abs(z - target_z)


def is_valid_placement(candidate: Placement, truck: Truck3D, placed: list[Placement]) -> bool:
    return (
        is_inside_truck(candidate.x, candidate.y, candidate.z, candidate.width, candidate.height, candidate.depth, truck)
        and not has_overlap(candidate, placed)
        and has_minimum_support(candidate, placed)
        and respects_fragility(candidate, placed)
        and has_lateral_support_for_vertical_thin(candidate, truck, placed)
    )


def valid_candidates(
    package: Package3D,
    truck: Truck3D,
    placed: list[Placement],
    sequence: int,
    allow_rotation: bool,
) -> list[Placement]:
    candidates: list[Placement] = []
    for width, height, depth, orientation in orientations(package, allow_rotation):
        for x, y, z in candidate_points(placed, truck, width, depth, package):
            candidate = build_candidate(package, sequence, x, y, z, width, height, depth, orientation)
            if is_valid_placement(candidate, truck, placed):
                candidates.append(candidate)
    return filter_candidates_by_loading_frontier(candidates, truck, placed)


def dense_valid_candidates(
    package: Package3D,
    truck: Truck3D,
    placed: list[Placement],
    sequence: int,
    allow_rotation: bool,
) -> list[Placement]:
    candidates: list[Placement] = []
    for width, height, depth, orientation in orientations(package, allow_rotation):
        for x, y, z in dense_candidate_points(placed, truck, width, height, depth, package):
            candidate = build_candidate(package, sequence, x, y, z, width, height, depth, orientation)
            if is_valid_placement(candidate, truck, placed):
                candidates.append(candidate)
    return filter_candidates_by_loading_frontier(candidates, truck, placed)


def is_loading_path_clear(
    candidate: Placement,
    truck: Truck3D,
    placed: list[Placement],
) -> bool:
    if candidate.z + candidate.depth >= truck.largo_cm - LOADING_FRONTIER_EPSILON_CM:
        return True

    candidate_x1 = candidate.x
    candidate_x2 = candidate.x + candidate.width
    candidate_y1 = candidate.y
    candidate_y2 = candidate.y + candidate.height
    path_start_z = candidate.z + candidate.depth

    for current in placed:
        if current.z + current.depth <= path_start_z + LOADING_FRONTIER_EPSILON_CM:
            continue
        overlap_x = min(candidate_x2, current.x + current.width) - max(candidate_x1, current.x)
        overlap_y = min(candidate_y2, current.y + current.height) - max(candidate_y1, current.y)
        if overlap_x > LOADING_FRONTIER_EPSILON_CM and overlap_y > LOADING_FRONTIER_EPSILON_CM:
            return False
    return True


def filter_candidates_by_loading_frontier(
    candidates: list[Placement],
    truck: Truck3D,
    placed: list[Placement],
) -> list[Placement]:
    if not candidates:
        return []

    accessible_candidates = [
        candidate
        for candidate in candidates
        if is_loading_path_clear(candidate, truck, placed)
    ]
    if not accessible_candidates:
        return []

    min_z = min(candidate.z for candidate in accessible_candidates)
    frontier_z = min_z + LOADING_FRONTIER_EPSILON_CM
    return [candidate for candidate in accessible_candidates if candidate.z <= frontier_z]


def create_initial_space(truck: Truck3D) -> dict[str, float]:
    return {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "width": truck.width,
        "height": truck.height,
        "length": truck.length,
    }


def fits_dimensions_in_space(width: float, height: float, length: float, space: dict[str, float]) -> bool:
    return width <= space["width"] and height <= space["height"] and length <= space["length"]


def fits_in_space(package: Package3D, space: dict[str, float]) -> bool:
    return fits_dimensions_in_space(package.width, package.height, package.length, space)


def generate_rotations(package: Package3D) -> list[tuple[float, float, float]]:
    original = [(package.width, package.height, package.length)]
    if is_upright_appliance(package):
        return original
    if not package.permite_rotacion:
        if allows_controlled_thin_rotation(package):
            return [(width, height, length) for width, height, length, _ in controlled_thin_rotations((package.width, package.height, package.length))]
        return original

    all_rotations = list(dict.fromkeys(permutations((package.width, package.height, package.length), 3)))
    return sorted(
        [(width, height, length) for width, height, length in all_rotations],
        key=lambda item: orientation_sort_key(item[0], item[1], item[2]),
    )


def split_space(
    space: dict[str, float],
    package_or_width,
    height: float | None = None,
    length: float | None = None,
) -> list[dict[str, float]]:
    if height is None and length is None:
        width = package_or_width.width
        height = package_or_width.height
        length = package_or_width.length
    else:
        width = float(package_or_width)

    new_spaces: list[dict[str, float]] = []
    remaining_width = space["width"] - width
    remaining_height = space["height"] - height
    remaining_length = space["length"] - length

    if remaining_width > 0:
        new_spaces.append(
            {
                "x": space["x"] + width,
                "y": space["y"],
                "z": space["z"],
                "width": remaining_width,
                "height": height,
                "length": length,
            }
        )

    if remaining_height > 0:
        new_spaces.append(
            {
                "x": space["x"],
                "y": space["y"] + height,
                "z": space["z"],
                "width": space["width"],
                "height": remaining_height,
                "length": length,
            }
        )

    if remaining_length > 0:
        new_spaces.append(
            {
                "x": space["x"],
                "y": space["y"],
                "z": space["z"] + length,
                "width": space["width"],
                "height": space["height"],
                "length": remaining_length,
            }
        )

    return new_spaces


def space_volume(space: dict[str, float]) -> float:
    return space["width"] * space["height"] * space["length"]
