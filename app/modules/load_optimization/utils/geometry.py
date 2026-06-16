def create_initial_space(truck):
    return {
        "x": 0,
        "y": 0,
        "z": 0,
        "width": truck.width,
        "height": truck.height,
        "length": truck.length,
    }


def fits_dimensions_in_space(width, height, length, space) -> bool:
    return (
        width <= space["width"]
        and height <= space["height"]
        and length <= space["length"]
    )


def fits_in_space(package, space) -> bool:
    return fits_dimensions_in_space(
        package.width,
        package.height,
        package.length,
        space
    )


def generate_rotations(package):
    original = [
        (package.width, package.height, package.length)
    ]

    base_rotations = [
        (package.width, package.height, package.length),
        (package.length, package.height, package.width),
    ]

    all_rotations = [
        (package.width, package.height, package.length),
        (package.width, package.length, package.height),
        (package.height, package.width, package.length),
        (package.height, package.length, package.width),
        (package.length, package.width, package.height),
        (package.length, package.height, package.width),
    ]

    fragile_contents = ["VIDRIO", "LIQUIDO"]
    limited_contents = ["ELECTRODOMESTICO", "ARTEFACTO"]

    fragility = package.fragility.upper()
    content_type = package.content_type.upper()

    if fragility == "ALTA":
        return original

    if content_type in fragile_contents:
        return original

    if fragility == "MEDIA":
        return list(set(base_rotations))

    if content_type in limited_contents:
        return list(set(base_rotations))

    return list(set(all_rotations))


def split_space(space, package_or_width, height=None, length=None):
    """
    Divide el espacio libre después de colocar un paquete.

    Soporta dos formas:
    1. split_space(space, package)
    2. split_space(space, width, height, length)
    """

    if height is None and length is None:
        width = package_or_width.width
        height = package_or_width.height
        length = package_or_width.length
    else:
        width = package_or_width

    new_spaces = []

    remaining_width = space["width"] - width
    remaining_height = space["height"] - height
    remaining_length = space["length"] - length

    if remaining_width > 0:
        new_spaces.append({
            "x": space["x"] + width,
            "y": space["y"],
            "z": space["z"],
            "width": remaining_width,
            "height": height,
            "length": length,
        })

    if remaining_height > 0:
        new_spaces.append({
            "x": space["x"],
            "y": space["y"] + height,
            "z": space["z"],
            "width": space["width"],
            "height": remaining_height,
            "length": length,
        })

    if remaining_length > 0:
        new_spaces.append({
            "x": space["x"],
            "y": space["y"],
            "z": space["z"] + length,
            "width": space["width"],
            "height": space["height"],
            "length": remaining_length,
        })

    return new_spaces


def space_volume(space) -> float:
    return space["width"] * space["height"] * space["length"]