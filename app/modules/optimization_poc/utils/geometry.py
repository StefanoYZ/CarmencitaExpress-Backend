from itertools import permutations

from app.modules.optimization_poc.models.package import Package3D, destination_rank
from app.modules.optimization_poc.models.truck import Truck3D, target_z_from_rank
from app.modules.optimization_poc.schema import Placement
from app.modules.optimization_poc.validators import has_minimum_support, has_overlap, is_inside_truck, respects_fragility


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
    )


def orientations(package: Package3D, allow_rotation: bool) -> list[tuple[float, float, float, str]]:
    base = (package.ancho_cm, package.alto_cm, package.largo_cm)
    if not allow_rotation or not package.permite_rotacion:
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
        points.add((item.x, item.y, item.z - depth))

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


def candidate_point_sort_key(
    point: tuple[float, float, float],
    truck: Truck3D,
    package: Package3D,
    depth: float,
) -> tuple[float, float, float, float]:
    route_penalty = route_point_penalty(point[2], depth, package, truck)
    return (point[1], route_penalty, point[2], point[0])


def route_point_penalty(z: float, depth: float, package: Package3D, truck: Truck3D) -> float:
    target_z = target_z_from_rank(destination_rank(package), truck, depth)
    return abs(z - target_z)


def is_valid_placement(candidate: Placement, truck: Truck3D, placed: list[Placement]) -> bool:
    return (
        is_inside_truck(candidate.x, candidate.y, candidate.z, candidate.width, candidate.height, candidate.depth, truck)
        and not has_overlap(candidate, placed)
        and has_minimum_support(candidate, placed)
        and respects_fragility(candidate, placed)
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
    return candidates


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
    if not package.permite_rotacion:
        return original

    fragile_tokens = ("VIDRIO", "LIQUIDO", "MEDICAMENT", "TELEVISOR")
    limited_tokens = (
        "ELECTRODOMESTICO",
        "ARTEFACTO",
        "REFRIGERADORA",
        "COCINA",
        "LAVADORA",
        "CONGELADORA",
    )

    content_type = (package.content_type or "").upper()
    if package.fragility == "ALTA" or any(token in content_type for token in fragile_tokens):
        return original

    base_rotations = [
        (package.width, package.height, package.length),
        (package.length, package.height, package.width),
    ]

    if package.fragility == "MEDIA" or any(token in content_type for token in limited_tokens):
        return list(dict.fromkeys(base_rotations))

    all_rotations = list(dict.fromkeys(permutations((package.width, package.height, package.length), 3)))
    return [(width, height, length) for width, height, length in all_rotations]


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
