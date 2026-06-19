from sqlalchemy.orm import Session

from app.modules.clients import repository
from app.modules.clients.model import Client
from app.modules.clients.schema import ClientCreate, ClientUpdate, ClientUpsert


def get_client_by_dni(db: Session, dni: str) -> Client | None:
    return repository.get_client_by_dni(db, dni)


def list_clients(db: Session) -> list[Client]:
    return repository.list_clients(db)


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
