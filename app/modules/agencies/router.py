from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.agencies.schema import (
    AgencyAdminAssignment,
    AgencyCreate,
    AgencyDashboardResponse,
    AgencyResponse,
    AgencyUpdate,
    AgencyUserCreate,
)
from app.modules.agencies.service import (
    agency_dashboard,
    assign_agency_admin,
    create_agency,
    create_agency_user,
    get_scoped_agency,
    is_global_admin,
    is_agency_admin,
    list_agency_users,
    list_scoped_agencies,
    set_agency_user_active,
    set_agency_active,
    update_agency_user,
    update_agency,
)
from app.modules.shipments.schema import ShipmentCreate, ShipmentResponse
from app.modules.shipments.model import Shipment
from app.modules.shipments.reports import generate_operational_report_pdf, generate_operational_report_excel
from app.modules.clients.schema import ClientResponse
from app.modules.clients.service import list_clients_for_agency
from app.modules.shipments.service import create_shipment
from app.modules.users.model import InternalUser
from app.modules.users.schema import UserResponse, UserStatusUpdate, UserUpdate


router = APIRouter(prefix="/agencias", tags=["Agencias"])


@router.get("", response_model=list[AgencyResponse])
def list_agencies_endpoint(
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.read")),
) -> list[AgencyResponse]:
    return list_scoped_agencies(db, current_user)


@router.post("", response_model=AgencyResponse, status_code=status.HTTP_201_CREATED)
def create_agency_endpoint(
    payload: AgencyCreate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.write")),
) -> AgencyResponse:
    _require_global_admin(current_user)
    try:
        return create_agency(db, payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{agency_id}", response_model=AgencyResponse)
def get_agency_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.read")),
) -> AgencyResponse:
    return _get_scoped_agency_or_404(db, agency_id, current_user)


@router.patch("/{agency_id}", response_model=AgencyResponse)
def update_agency_endpoint(
    agency_id: int,
    payload: AgencyUpdate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.update")),
) -> AgencyResponse:
    _require_global_admin(current_user)
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    try:
        return update_agency(db, agency, payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{agency_id}/activate", response_model=AgencyResponse)
def activate_agency_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.change_status")),
) -> AgencyResponse:
    _require_global_admin(current_user)
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    try:
        return set_agency_active(db, agency, True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{agency_id}/deactivate", response_model=AgencyResponse)
def deactivate_agency_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.change_status")),
) -> AgencyResponse:
    _require_global_admin(current_user)
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    return set_agency_active(db, agency, False)


@router.get("/{agency_id}/users", response_model=list[UserResponse])
def list_agency_users_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.read")),
) -> list[UserResponse]:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    return list_agency_users(db, agency)


@router.post("/{agency_id}/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_agency_user_endpoint(
    agency_id: int,
    payload: AgencyUserCreate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.update")),
) -> UserResponse:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    try:
        return create_agency_user(db, agency, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{agency_id}/users/{user_id}", response_model=UserResponse)
def update_agency_user_endpoint(
    agency_id: int,
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.update")),
) -> UserResponse:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    _ensure_operational_target(db, user_id, current_user)
    try:
        user = update_agency_user(db, agency, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user


@router.patch("/{agency_id}/users/{user_id}/status", response_model=UserResponse)
def update_agency_user_status_endpoint(
    agency_id: int,
    user_id: int,
    payload: UserStatusUpdate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.update")),
) -> UserResponse:
    if current_user.id == user_id and not payload.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes desactivar tu propia cuenta")
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    _ensure_operational_target(db, user_id, current_user)
    user = set_agency_user_active(db, agency, user_id, payload)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user


@router.post("/{agency_id}/agency-admin", response_model=AgencyResponse)
@router.put("/{agency_id}/agency-admin", response_model=AgencyResponse)
def assign_agency_admin_endpoint(
    agency_id: int,
    payload: AgencyAdminAssignment,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.assign_admin")),
) -> AgencyResponse:
    _require_global_admin(current_user)
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    try:
        return assign_agency_admin(db, agency, payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{agency_id}/dashboard", response_model=AgencyDashboardResponse)
def agency_dashboard_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("agencias.read")),
) -> AgencyDashboardResponse:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    return agency_dashboard(db, agency)


@router.get("/{agency_id}/clientes", response_model=list[ClientResponse])
def list_agency_clients_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> list[ClientResponse]:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    return list_clients_for_agency(db, agency.id)


@router.get("/{agency_id}/encomiendas", response_model=list[ShipmentResponse])
def list_agency_shipments_endpoint(
    agency_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> list[ShipmentResponse]:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    return db.query(Shipment).filter(Shipment.agency_id == agency.id).order_by(Shipment.created_at.desc()).all()


@router.get("/{agency_id}/encomiendas/codigo/{code}", response_model=ShipmentResponse)
def get_agency_shipment_by_code_endpoint(
    agency_id: int,
    code: str,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> ShipmentResponse:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    shipment = db.query(Shipment).filter(Shipment.agency_id == agency.id, Shipment.shipment_code == code).first()
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return shipment


@router.get("/{agency_id}/encomiendas/{shipment_id}", response_model=ShipmentResponse)
def get_agency_shipment_endpoint(
    agency_id: int,
    shipment_id: int,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> ShipmentResponse:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    shipment = db.query(Shipment).filter(Shipment.agency_id == agency.id, Shipment.id == shipment_id).first()
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return shipment


@router.get("/{agency_id}/reportes/operativo.{format}")
def export_agency_report_endpoint(
    agency_id: int,
    format: str,
    fecha: date | None = Query(default=None),
    estado: str | None = Query(default=None),
    texto: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.read")),
) -> Response:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    report = {"pdf": (generate_operational_report_pdf, "application/pdf"),
              "xlsx": (generate_operational_report_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}.get(format)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Formato no disponible")
    content = report[0](db, report_date=fecha, status=estado, search=texto, agency_id=agency.id)
    return Response(content=content, media_type=report[1], headers={
        "Content-Disposition": f'attachment; filename="reporte_agencia_{agency.id}.{format}"'
    })


@router.post("/{agency_id}/encomiendas", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_agency_shipment_endpoint(
    agency_id: int,
    payload: ShipmentCreate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("encomiendas.write")),
) -> ShipmentResponse:
    agency = _get_scoped_agency_or_404(db, agency_id, current_user)
    if not agency.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La agencia esta inactiva")
    return create_shipment(
        db, payload, agency_id=agency.id, actor_user_id=current_user.id
    )


def _get_scoped_agency_or_404(db: Session, agency_id: int, current_user: InternalUser):
    agency = get_scoped_agency(db, agency_id, current_user)
    if agency is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agencia no encontrada")
    return agency


def _require_global_admin(current_user: InternalUser) -> None:
    if not is_global_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere rol ADMIN_GENERAL")


def _ensure_operational_target(db: Session, user_id: int, current_user: InternalUser) -> None:
    if not is_agency_admin(current_user) or is_global_admin(current_user):
        return
    target = db.get(InternalUser, user_id)
    if target is not None and not any(role.name in {"SECRETARIA", "ESTIBA"} for role in target.roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puedes gestionar personal operativo")
