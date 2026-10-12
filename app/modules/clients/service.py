from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.modules.clients import repository
from app.modules.clients.model import Client
from app.modules.clients.schema import ClientCreate, ClientUpdate, ClientUpsert
from app.modules.shipments.model import Shipment


def get_client_by_dni(db: Session, dni: str) -> Client | None:
    return repository.get_client_by_dni(db, dni)


def list_clients(db: Session) -> list[Client]:
    return repository.list_clients(db)


def get_client_by_dni_for_agency(db: Session, dni: str, agency_id: int) -> Client | None:
    client = get_client_by_dni(db, dni)
    if client is None:
        return None
    shipment_exists = db.query(Shipment.id).filter(
        Shipment.agency_id == agency_id,
        or_(
            Shipment.sender_document_number == dni,
            Shipment.recipient_document_number == dni,
        ),
    ).first()
    return client if shipment_exists else None


def list_clients_for_agency(db: Session, agency_id: int) -> list[Client]:
    return (
        db.query(Client)
        .join(
            Shipment,
            or_(
                Shipment.sender_document_number == Client.dni,
                Shipment.recipient_document_number == Client.dni,
            ),
        )
        .filter(Shipment.agency_id == agency_id)
        .order_by(Client.updated_at.desc())
        .distinct()
        .all()
    )


def create_or_update_client(db: Session, payload: ClientCreate) -> Client:
    return repository.upsert_client(db, ClientUpsert(**payload.model_dump()))


def update_client(db: Session, dni: str, payload: ClientUpdate) -> Client | None:
    return repository.update_client(db, dni, payload)


def upsert_client_from_person_data(
    db: Session,
    *,
    dni: str | None,
    nombre_completo: str | None,
    telefono: str | None = None,
    correo: str | None = None,
    direccion: str | None = None,
    commit: bool = True,
) -> Client | None:
    if not dni or not str(dni).strip().isdigit() or len(str(dni).strip()) != 8:
        return None

    if not nombre_completo or not str(nombre_completo).strip():
        return None

    payload = ClientUpsert(
        dni=str(dni).strip(),
        nombre_completo=str(nombre_completo).strip(),
        telefono=telefono,
        correo=correo,
        direccion=direccion,
    )
    return repository.upsert_client(db, payload, commit=commit)
