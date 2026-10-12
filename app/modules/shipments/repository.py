from datetime import datetime, timezone

from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.business_time import business_now, business_today
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
from app.modules.shipments.tracing import append_shipment_trace_event


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


def create_shipment(
    db: Session,
    shipment_data: ShipmentCreate,
    agency_id: int | None = None,
    privacy_channel: str = "INTERNAL",
    actor_user_id: int | None = None,
) -> Shipment:
    shipment = Shipment(
        shipment_code=generate_shipment_code(db),
        status=REGISTERED_STATUS,
        registration_origin=(EXTERNAL_REGISTRATION_ORIGIN if privacy_channel == "PUBLIC_WEB" else INTERNAL_REGISTRATION_ORIGIN),
        agency_id=agency_id,
        privacy_notice_version=(
            shipment_data.privacy_notice_version if shipment_data.privacy_notice_accepted else None
        ),
        privacy_accepted_at=business_now() if shipment_data.privacy_notice_accepted else None,
        privacy_channel=privacy_channel if shipment_data.privacy_notice_accepted else None,
        **shipment_data.model_dump(
            exclude={
                "status",
                "privacy_notice_accepted",
                "privacy_notice_version",
                *NON_PERSISTED_PAYLOAD_FIELDS,
            }
        ),
    )
    return _commit_new_shipment_with_code_retry(
        db, shipment, actor_user_id=actor_user_id,
        source="WEB" if privacy_channel == "PUBLIC_WEB" else "INTERNO",
    )


def create_pre_registration(
    db: Session,
    shipment_data: ShipmentPreRegistrationCreate,
    *,
    privacy_accepted_at: datetime,
    privacy_channel: str,
    agency_id: int | None = None,
) -> Shipment:
    shipment = Shipment(
        shipment_code=generate_shipment_code(db),
        status=PRE_REGISTERED_STATUS,
        registration_origin=EXTERNAL_REGISTRATION_ORIGIN,
        agency_id=agency_id,
        privacy_notice_version=shipment_data.privacy_notice_version,
        privacy_accepted_at=privacy_accepted_at,
        privacy_channel=privacy_channel,
        **shipment_data.model_dump(
            exclude={"status", "privacy_notice_accepted", "privacy_notice_version", *NON_PERSISTED_PAYLOAD_FIELDS}
        ),
    )
    return _commit_new_shipment_with_code_retry(db, shipment, source="WEB")


def _commit_new_shipment_with_code_retry(
    db: Session,
    shipment: Shipment,
    *,
    actor_user_id: int | None = None,
    source: str = "SISTEMA",
) -> Shipment:
    if not shipment.shipment_code.startswith(expected_shipment_code_prefix()):
        shipment.shipment_code = generate_shipment_code(db)
    try:
        with db.begin_nested():
            db.add(shipment)
            db.flush([shipment])
            append_shipment_trace_event(
                db, shipment,
                event_type="PRE_REGISTRADA" if shipment.status == PRE_REGISTERED_STATUS else "REGISTRADA",
                location=shipment.origin,
                description="Se creó el pre-registro del envío." if shipment.status == PRE_REGISTERED_STATUS else "Se registró la encomienda.",
                visible_to_customer=True,
                actor_user_id=actor_user_id,
                source=source,
            )
    except IntegrityError:
        shipment.shipment_code = generate_shipment_code(db)
        with db.begin_nested():
            db.add(shipment)
            db.flush([shipment])
            append_shipment_trace_event(
                db, shipment,
                event_type="PRE_REGISTRADA" if shipment.status == PRE_REGISTERED_STATUS else "REGISTRADA",
                location=shipment.origin,
                description="Se creó el pre-registro del envío." if shipment.status == PRE_REGISTERED_STATUS else "Se registró la encomienda.",
                visible_to_customer=True,
                actor_user_id=actor_user_id,
                source=source,
            )
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


def mark_shipment_as_quoted(
    db: Session, shipment: Shipment, *, actor_user_id: int | None = None
) -> Shipment:
    if shipment.status == REGISTERED_STATUS:
        shipment.status = QUOTED_STATUS
        db.add(shipment)
        _add_trace_event(
            db, shipment, "COTIZADA", shipment.origin, "Se generó la cotización del envío.",
            visible=True, actor_user_id=actor_user_id,
        )
        db.commit()
        db.refresh(shipment)
    return shipment


def confirm_pre_registration(
    db: Session, shipment: Shipment, *, actor_user_id: int | None = None,
    agency_id: int | None = None,
) -> Shipment:
    shipment.status = REGISTERED_STATUS
    shipment.registration_origin = EXTERNAL_REGISTRATION_ORIGIN
    if agency_id is not None:
        shipment.agency_id = agency_id
    db.add(shipment)
    _add_trace_event(
        db, shipment, "REGISTRADA", shipment.origin, "El pre-registro se confirmó como encomienda.",
        visible=True, actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(shipment)
    return shipment


def update_shipment(
    db: Session,
    shipment: Shipment,
    payload: ShipmentUpdate,
    *,
    actor_user_id: int | None = None,
    origin_agency_id: int | None = None,
) -> Shipment:
    update_data = payload.model_dump(exclude_unset=True)
    changed = False
    for field, value in update_data.items():
        if field in PROTECTED_UPDATE_FIELDS:
            continue
        if getattr(shipment, field) != value:
            changed = True
        setattr(shipment, field, value)
    if shipment.agency_id != origin_agency_id:
        shipment.agency_id = origin_agency_id
        changed = True
    db.add(shipment)
    if changed:
        _add_trace_event(
            db, shipment, "ACTUALIZADA", shipment.origin,
            "Se actualizaron datos de la encomienda.", visible=False,
            actor_user_id=actor_user_id,
        )
    db.commit()
    db.refresh(shipment)
    return shipment


def cancel_shipment_with_reason(
    db: Session, shipment: Shipment, reason: str, *, actor_user_id: int | None = None
) -> Shipment:
    shipment.status = CANCELED_STATUS
    shipment.cancellation_reason = reason
    shipment.canceled_at = datetime.now(timezone.utc)
    db.add(shipment)
    _add_trace_event(
        db, shipment, "ANULADA", shipment.origin, "La encomienda fue anulada.",
        visible=True, actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(shipment)
    return shipment


def cancel_shipment(
    db: Session, shipment: Shipment, *, actor_user_id: int | None = None
) -> Shipment:
    return cancel_shipment_with_reason(
        db, shipment, "Anulacion solicitada desde endpoint DELETE", actor_user_id=actor_user_id
    )


def get_label_data(db: Session, shipment_id: int) -> Shipment | None:
    return get_shipment_by_id(db, shipment_id)


def mark_as_delivered(
    db: Session,
    shipment: Shipment,
    receiver_document: str,
    signature_base64: str | None,
    *,
    actor_user_id: int | None = None,
) -> Shipment:
    shipment.status = DELIVERED_STATUS
    shipment.delivered_at = datetime.now(timezone.utc)
    shipment.delivery_receiver_document = receiver_document
    shipment.digital_signature_base64 = signature_base64
    db.add(shipment)
    _add_trace_event(
        db, shipment, "ENTREGADA", shipment.destination,
        "La encomienda fue registrada como entregada.", visible=True,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(shipment)
    return shipment


def _add_trace_event(
    db: Session,
    shipment: Shipment,
    event_type: str,
    location: str | None,
    description: str,
    *,
    visible: bool,
    source: str | None = None,
    actor_user_id: int | None = None,
) -> None:
    append_shipment_trace_event(
        db,
        shipment,
        event_type=event_type,
        location=location,
        description=description,
        actor_user_id=actor_user_id,
        source=source or ("INTERNO" if actor_user_id is not None else "SISTEMA"),
        visible_to_customer=visible,
    )
