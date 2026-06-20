import pytest

from app.modules.optimization_poc.models.package import Package3D, is_upright_appliance
from app.modules.optimization_poc.utils.geometry import generate_rotations, orientations


def build_package(description: str, content_type: str = "ELECTRONICOS") -> Package3D:
    return Package3D(
        id=1,
        codigo="TEST-UPRIGHT-001",
        descripcion=description,
        destino="Orocullay",
        orden_entrega=19,
        prioridad=1,
        fragilidad="MEDIA",
        peso_kg=80,
        largo_cm=75,
        ancho_cm=70,
        alto_cm=170,
        permite_rotacion=True,
        tipo_contenido=content_type,
        requires_packing=True,
    )


@pytest.mark.parametrize(
    "description",
    [
        "Refrigeradora embalada",
        "Cocina de seis hornillas",
        "Microondas",
        "Licuadora",
        "Olla arrocera",
        "Campana extractora",
        "Air fryer",
        "Lavadora",
        "Congeladora",
    ],
)
def test_appliances_keep_original_vertical_orientation(description):
    package = build_package(description)

    assert is_upright_appliance(package) is True
    assert generate_rotations(package) == [(70, 170, 75)]
    assert orientations(package, allow_rotation=True) == [(70, 170, 75, "LWH")]


def test_regular_package_can_still_rotate():
    package = build_package("Caja de ropa", content_type="ROPA")

    assert is_upright_appliance(package) is False
    assert len(generate_rotations(package)) > 1
    assert len(orientations(package, allow_rotation=True)) > 1
