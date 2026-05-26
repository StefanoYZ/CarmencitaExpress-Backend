from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.modules.clients.model import Client
from app.modules.clients.schema import ClientCreate, ClientUpdate, ClientUpsert


def get_client_by_dni(db: Session, dni: str) -> Client | None:
    return db.query(Client).filter(Client.dni == dni).first()


def list_clients(db: Session) -> list[Client]:
    return db.query(Client).order_by(desc(Client.updated_at)).all()


def create_client(db: Session, data: ClientCreate | ClientUpsert) -> Client:
    client = Client(
        dni=data.dni,
        full_name=data.full_name,
        phone=data.phone,
        email=data.email,
        address=data.address,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def update_client(db: Session, dni: str, data: ClientUpdate | ClientUpsert) -> Client | None:
    client = get_client_by_dni(db, dni)
    if client is None:
        return None

    changed = _apply_non_empty_updates(client, data)
    if changed:
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


def upsert_client(db: Session, data: ClientUpsert) -> Client:
    client = get_client_by_dni(db, data.dni)
    if client is None:
        return create_client(db, data)

    changed = _apply_non_empty_updates(client, data)
    if changed:
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


def _apply_non_empty_updates(client: Client, data: ClientUpdate | ClientUpsert) -> bool:
    changed = False
    for field in ("full_name", "phone", "email", "address"):
        value = getattr(data, field, None)
        if value is None:
            continue
        if getattr(client, field) != value:
            setattr(client, field, value)
            changed = True
    return changed
