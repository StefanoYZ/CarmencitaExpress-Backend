from datetime import date

from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.shipments.model import Shipment
from app.modules.shipments.schema import ShipmentCreate, ShipmentUpdate


INITIAL_STATUS = "REGISTRADA"
QUOTED_STATUS = "COTIZADA"
CANCELED_STATUS = "ANULADA"
SHIPMENT_CODE_WEEKDAY = {
    1: "L",
    2: "M",
    3: "X",
    4: "J",
    5: "V",
    6: "S",
    7: "D",
}


def generate_shipment_code(db: Session) -> str:
    weekday_letter = SHIPMENT_CODE_WEEKDAY[date.today().isoweekday()]
    next_sequence = (db.query(func.max(Shipment.id)).scalar() or 0) + 1

    while True:
        shipment_code = f"{weekday_letter}{str(next_sequence).zfill(9)}"
        exists = db.query(Shipment.id).filter(Shipment.shipment_code == shipment_code).first()
        if not exists:
            return shipment_code
        next_sequence += 1


def create_shipment(db: Session, shipment_data: ShipmentCreate) -> Shipment:
    shipment = Shipment(
        shipment_code=generate_shipment_code(db),
        status=INITIAL_STATUS,
        **shipment_data.model_dump(),
    )
    db.add(shipment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        shipment.shipment_code = generate_shipment_code(db)
        db.add(shipment)
        db.commit()
    db.refresh(shipment)
    return shipment


def list_shipments(db: Session) -> list[Shipment]:
    return db.query(Shipment).order_by(desc(Shipment.created_at)).all()


def get_shipment_by_id(db: Session, shipment_id: int) -> Shipment | None:
    return db.query(Shipment).filter(Shipment.id == shipment_id).first()


def get_shipment_by_code(db: Session, shipment_code: str) -> Shipment | None:
    return db.query(Shipment).filter(Shipment.shipment_code == shipment_code).first()


def mark_shipment_as_quoted(db: Session, shipment: Shipment) -> Shipment:
    if shipment.status == INITIAL_STATUS:
        shipment.status = QUOTED_STATUS
        db.add(shipment)
        db.commit()
        db.refresh(shipment)
    return shipment


def update_shipment(db: Session, shipment: Shipment, payload: ShipmentUpdate) -> Shipment:
    update_data = payload.model_dump()
    for field, value in update_data.items():
        setattr(shipment, field, value)
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def cancel_shipment(db: Session, shipment: Shipment) -> Shipment:
    shipment.status = CANCELED_STATUS
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment
