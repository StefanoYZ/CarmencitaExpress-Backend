from sqlalchemy.orm import Session

from app.modules.shipments import repository
from app.modules.shipments.model import Shipment
from app.modules.shipments.schema import ShipmentCreate, ShipmentUpdate


def create_shipment(db: Session, payload: ShipmentCreate) -> Shipment:
    return repository.create_shipment(db, payload)


def list_shipments(db: Session) -> list[Shipment]:
    return repository.list_shipments(db)


def get_shipment(db: Session, shipment_id: int) -> Shipment | None:
    return repository.get_shipment_by_id(db, shipment_id)


def get_shipment_by_code(db: Session, shipment_code: str) -> Shipment | None:
    return repository.get_shipment_by_code(db, shipment_code)


def mark_shipment_as_quoted(db: Session, shipment: Shipment) -> Shipment:
    return repository.mark_shipment_as_quoted(db, shipment)


def update_shipment(db: Session, shipment_id: int, payload: ShipmentUpdate) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    return repository.update_shipment(db, shipment, payload)


def cancel_shipment(db: Session, shipment_id: int) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    return repository.cancel_shipment(db, shipment)
