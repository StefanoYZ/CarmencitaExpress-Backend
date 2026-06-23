from datetime import datetime, timezone

from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.modules.shipments.constants import (
    CANCELED_STATUS,
    DELIVERED_STATUS,
    EXTERNAL_REGISTRATION_ORIGIN,
    INTERNAL_REGISTRATION_ORIGIN,
    PRE_REGISTERED_STATUS,
    QUOTED_STATUS,
    REGISTERED_STATUS,
)
from app.modules.shipments.model import Shipment
from app.modules.shipments.schema import ShipmentCreate, ShipmentPreRegistrationCreate, ShipmentUpdate


SHIPMENT_CODE_WEEKDAY = {
    1: "L",
    2: "M",
    3: "X",
    4: "J",
    5: "V",
    6: "S",
    7: "D",
}
PROTECTED_UPDATE_FIELDS = {
    "id",
    "shipment_code",
    "created_at",
    "updated_at",
    "status",
    "registration_origin",
    "cancellation_reason",
    "canceled_at",
    "delivered_at",
    "delivery_receiver_document",
    "digital_signature_base64",
    "security_key",
    "sender_email",
    "recipient_email",
}
NON_PERSISTED_PAYLOAD_FIELDS = {"sender_email", "recipient_email"}


def expected_shipment_code_prefix() -> str:
    return SHIPMENT_CODE_WEEKDAY[business_today().isoweekday()]


def generate_shipment_code(db: Session) -> str:
    weekday_letter = expected_shipment_code_prefix()
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
        status=REGISTERED_STATUS,
        registration_origin=INTERNAL_REGISTRATION_ORIGIN,
        **shipment_data.model_dump(exclude={"status", *NON_PERSISTED_PAYLOAD_FIELDS}),
    )
    return _commit_new_shipment_with_code_retry(db, shipment)


def create_pre_registration(db: Session, shipment_data: ShipmentPreRegistrationCreate) -> Shipment:
    shipment = Shipment(
        shipment_code=generate_shipment_code(db),
        status=PRE_REGISTERED_STATUS,
        registration_origin=EXTERNAL_REGISTRATION_ORIGIN,
        **shipment_data.model_dump(exclude={"status", *NON_PERSISTED_PAYLOAD_FIELDS}),
    )
    return _commit_new_shipment_with_code_retry(db, shipment)


def _commit_new_shipment_with_code_retry(db: Session, shipment: Shipment) -> Shipment:
    if not shipment.shipment_code.startswith(expected_shipment_code_prefix()):
        shipment.shipment_code = generate_shipment_code(db)
    try:
        with db.begin_nested():
            db.add(shipment)
            db.flush([shipment])
    except IntegrityError:
        shipment.shipment_code = generate_shipment_code(db)
        with db.begin_nested():
            db.add(shipment)
            db.flush([shipment])
    db.commit()
    db.refresh(shipment)
    return shipment


def list_shipments(db: Session) -> list[Shipment]:
    return db.query(Shipment).order_by(desc(Shipment.created_at)).all()


def get_shipment_by_id(db: Session, shipment_id: int) -> Shipment | None:
    return db.query(Shipment).filter(Shipment.id == shipment_id).first()


def get_shipment_by_code(db: Session, shipment_code: str) -> Shipment | None:
    for candidate in _shipment_code_candidates(shipment_code):
        shipment = db.query(Shipment).filter(Shipment.shipment_code == candidate).first()
        if shipment is not None:
            return shipment
    return None


def _shipment_code_candidates(shipment_code: str) -> list[str]:
    normalized = str(shipment_code or "").strip().upper().replace(" ", "")
    if not normalized:
        return []

    candidates = [normalized]
    if len(normalized) == 10 and normalized[1:].isdigit():
        first = normalized[0]
        weekday_by_letter = {letter: number for number, letter in SHIPMENT_CODE_WEEKDAY.items()}

        if first in weekday_by_letter:
            candidates.append(f"{weekday_by_letter[first]}{normalized[1:]}")
        elif first.isdigit() and int(first) in SHIPMENT_CODE_WEEKDAY:
            candidates.append(f"{SHIPMENT_CODE_WEEKDAY[int(first)]}{normalized[1:]}")

    return list(dict.fromkeys(candidates))


def mark_shipment_as_quoted(db: Session, shipment: Shipment) -> Shipment:
    if shipment.status == REGISTERED_STATUS:
        shipment.status = QUOTED_STATUS
        db.add(shipment)
        db.commit()
        db.refresh(shipment)
    return shipment


def confirm_pre_registration(db: Session, shipment: Shipment) -> Shipment:
    shipment.status = REGISTERED_STATUS
    shipment.registration_origin = EXTERNAL_REGISTRATION_ORIGIN
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def update_shipment(db: Session, shipment: Shipment, payload: ShipmentUpdate) -> Shipment:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in PROTECTED_UPDATE_FIELDS:
            continue
        setattr(shipment, field, value)
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def cancel_shipment_with_reason(db: Session, shipment: Shipment, reason: str) -> Shipment:
    shipment.status = CANCELED_STATUS
    shipment.cancellation_reason = reason
    shipment.canceled_at = datetime.now(timezone.utc)
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


def cancel_shipment(db: Session, shipment: Shipment) -> Shipment:
    return cancel_shipment_with_reason(db, shipment, "Anulacion solicitada desde endpoint DELETE")


def get_label_data(db: Session, shipment_id: int) -> Shipment | None:
    return get_shipment_by_id(db, shipment_id)


def mark_as_delivered(
    db: Session,
    shipment: Shipment,
    receiver_document: str,
    signature_base64: str | None,
) -> Shipment:
    shipment.status = DELIVERED_STATUS
    shipment.delivered_at = datetime.now(timezone.utc)
    shipment.delivery_receiver_document = receiver_document
    shipment.digital_signature_base64 = signature_base64
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment
