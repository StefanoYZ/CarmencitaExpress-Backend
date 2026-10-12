from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.security import hash_password
from app.modules.agencies.model import Agency
from app.modules.agencies.schema import (
    AgencyAdminAssignment,
    AgencyCreate,
    AgencyDashboardResponse,
    AgencyResponse,
    AgencyUpdate,
    AgencyUserCreate,
)
from app.modules.destinations.model import Destination
from app.modules.destinations.schema import normalize_destination_key
from app.modules.shipments.constants import CANCELED_STATUS, DELIVERED_STATUS
from app.modules.shipments.model import Shipment
from app.modules.users.model import InternalUser, Role
from app.modules.users.schema import UserResponse, UserStatusUpdate, UserUpdate
from app.modules.users.service import build_user_response


AGENCY_ADMIN_ROLE = "AGENCY_ADMIN"
GLOBAL_ADMIN_ROLE = "ADMIN_GENERAL"
OPERATIONAL_ROLES = {"SECRETARIA", "ESTIBA"}
BUSINESS_ROLES = OPERATIONAL_ROLES | {AGENCY_ADMIN_ROLE}


def is_global_admin(user: InternalUser) -> bool:
    return any(role.name in {GLOBAL_ADMIN_ROLE, "DEVELOPER"} and role.is_active for role in user.roles)


def is_agency_admin(user: InternalUser) -> bool:
    return any(role.name == AGENCY_ADMIN_ROLE and role.is_active for role in user.roles)


def is_business_user(user: InternalUser) -> bool:
    return any(role.name in BUSINESS_ROLES and role.is_active for role in user.roles)


def get_agency_for_origin(db: Session, origin: str) -> Agency | None:
    origin_key = normalize_destination_key(origin)
    if not origin_key:
        return None
    return (
        db.query(Agency)
        .join(Destination, Agency.destination_id == Destination.id)
        .filter(Destination.normalized_name == origin_key)
        .first()
    )


def backfill_shipment_agencies_by_origin(db: Session) -> int:
    """Align existing shipment ownership with the agency at the recorded origin."""
    agencies_by_origin = {
        destination.normalized_name: agency
        for agency, destination in db.query(Agency, Destination)
        .join(Destination, Agency.destination_id == Destination.id)
        .all()
    }
    updated = 0
    for shipment in db.query(Shipment).all():
        agency = agencies_by_origin.get(normalize_destination_key(shipment.origin))
        if agency is not None and shipment.agency_id != agency.id:
            shipment.agency_id = agency.id
            db.add(shipment)
            updated += 1
    if updated:
        db.commit()
    return updated


def get_scoped_agency(db: Session, agency_id: int, current_user: InternalUser) -> Agency | None:
    agency = _get_agency(db, agency_id)
    if agency is None:
        return None
    if is_global_admin(current_user):
        return agency
    if is_agency_admin(current_user) and current_user.agency_id == agency.id:
        return agency
    return None


def get_scoped_shipment(db: Session, shipment_id: int, current_user: InternalUser) -> Shipment | None:
    query = db.query(Shipment).filter(Shipment.id == shipment_id)
    if not is_global_admin(current_user):
        if not is_business_user(current_user) or current_user.agency_id is None:
            return None
        query = query.filter(Shipment.agency_id == current_user.agency_id)
    return query.first()


def list_scoped_shipments(db: Session, current_user: InternalUser) -> list[Shipment]:
    query = db.query(Shipment)
    if not is_global_admin(current_user):
        if not is_business_user(current_user) or current_user.agency_id is None:
            return []
        query = query.filter(Shipment.agency_id == current_user.agency_id)
    return query.order_by(desc(Shipment.created_at)).all()


def list_scoped_agencies(db: Session, current_user: InternalUser) -> list[AgencyResponse]:
    query = db.query(Agency).options(joinedload(Agency.destination))
    if is_global_admin(current_user):
        agencies = query.order_by(Agency.id).all()
    elif is_agency_admin(current_user) and current_user.agency_id is not None:
        agencies = query.filter(Agency.id == current_user.agency_id).all()
    else:
        agencies = []
    return [_build_agency_response(db, agency) for agency in agencies]


def create_agency(db: Session, payload: AgencyCreate) -> AgencyResponse:
    _get_active_destination(db, payload.destination_id)
    if db.query(Agency.id).filter(Agency.destination_id == payload.destination_id).first():
        raise ValueError("Ya existe una agencia para este destino")
    agency = Agency(
        code=_next_agency_code(db),
        destination_id=payload.destination_id,
        address=payload.address,
        phone=payload.phone,
        is_active=False,
    )
    try:
        db.add(agency)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Ya existe una agencia para este destino") from exc
    return _build_agency_response(db, _get_agency(db, agency.id))


def update_agency(db: Session, agency: Agency, payload: AgencyUpdate) -> AgencyResponse:
    changes = payload.model_dump(exclude_unset=True)
    destination_id = changes.get("destination_id")
    if destination_id is not None and destination_id != agency.destination_id:
        _get_active_destination(db, destination_id)
        existing = db.query(Agency.id).filter(Agency.destination_id == destination_id).first()
        if existing:
            raise ValueError("Ya existe una agencia para este destino")
    for field, value in changes.items():
        setattr(agency, field, value)
    try:
        db.add(agency)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Ya existe una agencia para este destino") from exc
    return _build_agency_response(db, _get_agency(db, agency.id))


def set_agency_active(db: Session, agency: Agency, is_active: bool) -> AgencyResponse:
    if is_active:
        _get_active_destination(db, agency.destination_id)
        if not db.query(InternalUser.id).filter(
            InternalUser.agency_id == agency.id,
            InternalUser.is_active.is_(True),
            InternalUser.roles.any(Role.name == AGENCY_ADMIN_ROLE),
        ).first():
            raise ValueError("Asigna un administrador de agencia activo antes de activarla")
    agency.is_active = is_active
    db.add(agency)
    db.commit()
    return _build_agency_response(db, _get_agency(db, agency.id))


def list_agency_users(db: Session, agency: Agency) -> list[UserResponse]:
    users = (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(InternalUser.agency_id == agency.id)
        .order_by(InternalUser.id)
        .all()
    )
    return [build_user_response(user) for user in users]


def create_agency_user(db: Session, agency: Agency, payload: AgencyUserCreate) -> UserResponse:
    existing = db.query(InternalUser.id).filter(InternalUser.username == payload.username).first()
    if existing:
        raise ValueError("username already exists")
    role = db.query(Role).filter(Role.name == payload.role, Role.is_active.is_(True)).first()
    if role is None or role.name not in OPERATIONAL_ROLES:
        raise ValueError("El rol operativo no esta disponible")
    user = InternalUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        is_active=True,
        agency_id=agency.id,
    )
    user.roles.append(role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return build_user_response(_get_user(db, user.id))


def update_agency_user(
    db: Session,
    agency: Agency,
    user_id: int,
    payload: UserUpdate,
) -> UserResponse | None:
    user = _get_agency_user(db, agency, user_id)
    if user is None:
        return None
    if payload.username is not None and payload.username != user.username:
        if db.query(InternalUser.id).filter(InternalUser.username == payload.username).first():
            raise ValueError("username already exists")
        user.username = payload.username
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.add(user)
    db.commit()
    return build_user_response(_get_user(db, user.id))


def set_agency_user_active(
    db: Session,
    agency: Agency,
    user_id: int,
    payload: UserStatusUpdate,
) -> UserResponse | None:
    user = _get_agency_user(db, agency, user_id)
    if user is None:
        return None
    user.is_active = payload.is_active
    db.add(user)
    db.commit()
    return build_user_response(_get_user(db, user.id))


def assign_agency_admin(
    db: Session,
    agency: Agency,
    payload: AgencyAdminAssignment,
) -> AgencyResponse:
    agency_admin_role = db.query(Role).filter(Role.name == AGENCY_ADMIN_ROLE, Role.is_active.is_(True)).first()
    if agency_admin_role is None:
        raise ValueError("El rol AGENCY_ADMIN no esta disponible")
    try:
        if payload.user_id is not None:
            user = _get_user(db, payload.user_id)
            if user is None:
                raise LookupError("Usuario no encontrado")
            if user.agency_id not in {None, agency.id}:
                raise ValueError("El usuario ya pertenece a otra agencia")
            if any(role.name in {GLOBAL_ADMIN_ROLE, "DEVELOPER"} for role in user.roles):
                raise ValueError("El usuario no puede convertirse en administrador de agencia")
        else:
            if db.query(InternalUser.id).filter(InternalUser.username == payload.username).first():
                raise ValueError("username already exists")
            user = InternalUser(
                username=payload.username,
                password_hash=hash_password(payload.password or ""),
                full_name=payload.full_name or "",
                is_active=True,
                agency_id=agency.id,
            )
            db.add(user)

        previous_admins = (
            db.query(InternalUser)
            .options(selectinload(InternalUser.roles))
            .filter(
                InternalUser.agency_id == agency.id,
                InternalUser.roles.any(Role.name == AGENCY_ADMIN_ROLE),
            )
            .all()
        )
        for previous_admin in previous_admins:
            if previous_admin.id == user.id:
                continue
            previous_admin.roles = [role for role in previous_admin.roles if role.name != AGENCY_ADMIN_ROLE]
            previous_admin.is_active = False

        user.agency_id = agency.id
        user.roles = [agency_admin_role]
        db.add(user)
        db.commit()
    except (LookupError, ValueError):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("No se pudo asignar el administrador de agencia") from exc
    return _build_agency_response(db, _get_agency(db, agency.id))


def agency_dashboard(db: Session, agency: Agency) -> AgencyDashboardResponse:
    status_counts = dict(
        db.query(Shipment.status, func.count(Shipment.id))
        .filter(Shipment.agency_id == agency.id)
        .group_by(Shipment.status)
        .all()
    )
    total_shipments = db.query(func.count(Shipment.id)).filter(Shipment.agency_id == agency.id).scalar() or 0
    delivered_shipments = (
        db.query(func.count(Shipment.id))
        .filter(Shipment.agency_id == agency.id, Shipment.status == DELIVERED_STATUS)
        .scalar()
        or 0
    )
    canceled_shipments = (
        db.query(func.count(Shipment.id))
        .filter(Shipment.agency_id == agency.id, Shipment.status == CANCELED_STATUS)
        .scalar()
        or 0
    )
    recent_shipments = (
        db.query(Shipment)
        .filter(Shipment.agency_id == agency.id)
        .order_by(desc(Shipment.created_at))
        .limit(10)
        .all()
    )
    return AgencyDashboardResponse(
        agency=_build_agency_response(db, agency),
        total_shipments=total_shipments,
        active_shipments=total_shipments - delivered_shipments - canceled_shipments,
        delivered_shipments=delivered_shipments,
        canceled_shipments=canceled_shipments,
        status_counts=status_counts,
        recent_shipments=recent_shipments,
    )


def _get_agency(db: Session, agency_id: int) -> Agency | None:
    return db.query(Agency).options(joinedload(Agency.destination)).filter(Agency.id == agency_id).first()


def _get_user(db: Session, user_id: int) -> InternalUser | None:
    return (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(InternalUser.id == user_id)
        .first()
    )


def _get_agency_user(db: Session, agency: Agency, user_id: int) -> InternalUser | None:
    user = _get_user(db, user_id)
    return user if user is not None and user.agency_id == agency.id else None


def _get_active_destination(db: Session, destination_id: int) -> Destination:
    destination = db.query(Destination).filter(Destination.id == destination_id).first()
    if destination is None:
        raise LookupError("Destino no encontrado")
    if not destination.is_active:
        raise ValueError("El destino debe estar activo")
    return destination


def _next_agency_code(db: Session) -> str:
    next_sequence = (db.query(func.max(Agency.id)).scalar() or 0) + 1
    while True:
        code = f"AG-{next_sequence:06d}"
        if db.query(Agency.id).filter(Agency.code == code).first() is None:
            return code
        next_sequence += 1


def _build_agency_response(db: Session, agency: Agency) -> AgencyResponse:
    admin = (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(
            InternalUser.agency_id == agency.id,
            InternalUser.roles.any(Role.name == AGENCY_ADMIN_ROLE),
        )
        .first()
    )
    return AgencyResponse(
        id=agency.id,
        code=agency.code,
        destination_id=agency.destination_id,
        address=agency.address,
        phone=agency.phone,
        is_active=agency.is_active,
        destination=agency.destination,
        admin=build_user_response(admin) if admin else None,
        created_at=agency.created_at,
        updated_at=agency.updated_at,
    )
