import json
from pathlib import Path
from random import Random

from sqlalchemy.orm import Session

from app.core.business_time import business_today, ensure_business_tz
from app.modules.optimization_poc.models.package import normalize_destination
# from app.modules.optimization_poc.models.package import Package3D, is_upright_appliance
from app.modules.optimization_poc.schema import Package, Truck
from app.modules.optimization_poc.utils.constants import ROUTE_RANK
from app.modules.shipments.constants import (
    PAYMENT_CONFIRMED_STATUS,
    QUOTED_STATUS,
    RECEIPT_ISSUED_STATUS,
    REGISTERED_STATUS,
)
from app.modules.shipments.model import Shipment

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SHUFFLE_SEED = 2026


def _load_json(name: str) -> list[dict]:
    with (FIXTURE_DIR / name).open(encoding="utf-8-sig") as file:
        return json.load(file)


def list_trucks() -> list[Truck]:
    return [Truck(**item) for item in _load_json("trucks.json")]


def list_packages(limit: int = 70, shuffled: bool = True) -> list[Package]:
    packages = [Package(**item) for item in _load_json("packages_70.json")[:limit]]
    if shuffled:
        packages = packages[:]
        Random(SHUFFLE_SEED).shuffle(packages)
    return packages


def list_packages_by_codes(codes: list[str]) -> list[Package]:
    normalized_codes = [code.strip().upper() for code in codes if code and code.strip()]
    packages = [Package(**item) for item in _load_json("packages_70.json")]
    package_by_code = {package.codigo.upper(): package for package in packages}
    return [package_by_code[code] for code in normalized_codes if code in package_by_code]


def get_truck(truck_id: str) -> Truck | None:
    return next((truck for truck in list_trucks() if truck.id == truck_id), None)


OPTIMIZABLE_SHIPMENT_STATUSES = {
    REGISTERED_STATUS,
    QUOTED_STATUS,
    PAYMENT_CONFIRMED_STATUS,
    RECEIPT_ISSUED_STATUS,
}


def list_registered_packages(db: Session, limit: int | None = None) -> list[Package]:
    # Filtra por estado en SQL (portable) y por "día de negocio" en Python con
    # ensure_business_tz, para no depender de cómo cada motor (SQLite/Postgres)
    # almacena la zona horaria de created_at.
    hoy = business_today()
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_(OPTIMIZABLE_SHIPMENT_STATUSES))
        .order_by(Shipment.created_at.asc(), Shipment.id.asc())
        .all()
    )
    del_dia = [
        shipment
        for shipment in shipments
        if ensure_business_tz(shipment.created_at).date() == hoy
    ]
    if limit is not None:
        del_dia = del_dia[:limit]
    return [_shipment_to_package(shipment) for shipment in del_dia]


def list_registered_packages_by_codes(db: Session, codes: list[str]) -> list[Package]:
    normalized_codes = [code.strip().upper() for code in codes if code and code.strip()]
    if not normalized_codes:
        return []
    day_start, day_end = business_day_utc_bounds()
    shipments = (
        db.query(Shipment)
        .filter(
            Shipment.status.in_(OPTIMIZABLE_SHIPMENT_STATUSES),
            Shipment.shipment_code.in_(normalized_codes),
            Shipment.created_at >= day_start,
            Shipment.created_at <= day_end,
        )
        .all()
    )
    shipment_by_code = {shipment.shipment_code.upper(): shipment for shipment in shipments}
    return [
        _shipment_to_package(shipment_by_code[code])
        for code in normalized_codes
        if code in shipment_by_code
    ]


def _shipment_to_package(shipment: Shipment) -> Package:
    content_type = str(shipment.content_type or "").strip().upper() or None
    requires_packing = content_type != "DOCUMENTOS"
    destination = normalize_destination(shipment.destination)
    package = Package(
        id=shipment.id,
        codigo=shipment.shipment_code,
        descripcion=shipment.description,
        destino=shipment.destination,
        orden_entrega=ROUTE_RANK.get(destination, 0),
        prioridad=1,
        fragilidad=shipment.fragility,
        peso_kg=shipment.weight_kg,
        largo_cm=shipment.length_cm,
        ancho_cm=shipment.width_cm,
        alto_cm=shipment.height_cm,
        permite_rotacion=requires_packing,
        tipo_contenido=content_type,
        orientacion_base=shipment.base_orientation or ("LARGO_ANCHO" if requires_packing else None),
        requires_packing=requires_packing,
    )
    # Regla anterior conservada como referencia: los electrodomesticos se
    # restringian automaticamente a posicion vertical.
    # if requires_packing and is_upright_appliance(Package3D.from_schema(package)):
    #     package.permite_rotacion = False
    return package
