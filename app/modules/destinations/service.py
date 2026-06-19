from sqlalchemy.orm import Session

from app.modules.destinations import repository
from app.modules.destinations.model import Destination
from app.modules.destinations.schema import DestinationCreate, DestinationUpdate

DEFAULT_DESTINATIONS = (
    "Trujillo",
    "Shorey",
    "Huaycatan",
    "Santiago de Chuco",
    "Chacomas",
    "Cachicadan",
    "Santa Cruz",
    "Cochapamba",
    "Ugallama",
    "Villacruz",
    "Las Manzanas",
    "Angasmarca",
    "Tambo Pampamarca Alta",
    "Psicochaca",
    "Santa Clara de Tulpo",
    "La Yeguada",
    "Mollebamba",
    "Cochamarca",
    "Orocullay",
)

DESTINATION_RENAMES = {
    "Huayatan": "Huaycatan",
    "Santa Cruz de Chuca": "Santa Cruz",
    "Algallama": "Ugallama",
}


def list_destinations(db: Session, include_inactive: bool = False) -> list[Destination]:
    return repository.list_destinations(db, include_inactive=include_inactive)


def create_destination(db: Session, payload: DestinationCreate) -> Destination:
    existing = repository.get_destination_by_name(db, payload.name)
    if existing:
        if not existing.is_active:
            return repository.update_destination(
                db,
                existing,
                DestinationUpdate(activo=True),
            )
        raise ValueError("El destino ya existe")
    return repository.create_destination(db, payload)


def update_destination(
    db: Session,
    destination_id: int,
    payload: DestinationUpdate,
) -> Destination | None:
    destination = repository.get_destination_by_id(db, destination_id)
    if not destination:
        return None
    if payload.name is not None:
        existing = repository.get_destination_by_name(db, payload.name)
        if existing and existing.id != destination.id:
            raise ValueError("El destino ya existe")
    return repository.update_destination(db, destination, payload)


def seed_default_destinations(db: Session) -> None:
    for previous_name, current_name in DESTINATION_RENAMES.items():
        previous = repository.get_destination_by_name(db, previous_name)
        current = repository.get_destination_by_name(db, current_name)
        if previous is not None and current is None:
            repository.update_destination(
                db,
                previous,
                DestinationUpdate(nombre=current_name),
            )

    for destination_name in DEFAULT_DESTINATIONS:
        if repository.get_destination_by_name(db, destination_name) is None:
            repository.create_destination(
                db,
                DestinationCreate(nombre=destination_name),
            )
