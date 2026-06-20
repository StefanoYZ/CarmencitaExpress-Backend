from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.modules.destinations.model import Destination
from app.modules.destinations.schema import (
    DestinationCreate,
    DestinationUpdate,
    normalize_destination_key,
)


def list_destinations(db: Session, include_inactive: bool = False) -> list[Destination]:
    query = db.query(Destination)
    if not include_inactive:
        query = query.filter(Destination.is_active.is_(True))
    return query.order_by(asc(Destination.name)).all()


def get_destination_by_id(db: Session, destination_id: int) -> Destination | None:
    return db.query(Destination).filter(Destination.id == destination_id).first()


def get_destination_by_name(db: Session, name: str) -> Destination | None:
    return (
        db.query(Destination)
        .filter(Destination.normalized_name == normalize_destination_key(name))
        .first()
    )


def create_destination(db: Session, payload: DestinationCreate) -> Destination:
    destination = Destination(
        name=payload.name,
        normalized_name=normalize_destination_key(payload.name),
        is_active=True,
    )
    db.add(destination)
    db.commit()
    db.refresh(destination)
    return destination


def update_destination(
    db: Session,
    destination: Destination,
    payload: DestinationUpdate,
) -> Destination:
    changed = False
    if payload.name is not None:
        destination.name = payload.name
        destination.normalized_name = normalize_destination_key(payload.name)
        changed = True
    if payload.is_active is not None:
        destination.is_active = payload.is_active
        changed = True

    if changed:
        db.add(destination)
        db.commit()
        db.refresh(destination)
    return destination
