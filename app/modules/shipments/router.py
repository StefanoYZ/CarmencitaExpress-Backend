from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.agencies.service import (
    get_agency_for_origin,
    get_scoped_shipment,
    is_business_user,
    is_global_admin,
    list_scoped_shipments,
)
from app.modules.shipments.reports import (
    generate_operational_report_excel,
    generate_operational_report_pdf,
)
from app.modules.shipments.schema import (
    ConfirmPreRegistrationRequest,
    DeliveryRequest,
    DeliveryResponse,
    ShipmentCancelRequest,
    ShipmentCreate,
    ShipmentDeleteResponse,
    ShipmentLabelResponse,
    ShipmentPreRegistrationCreate,
    ShipmentPreRegistrationResponse,
    PrivacyNoticeResponse,
    ShipmentResponse,
    ShipmentUpdate,
    PUBLIC_PRIVACY_NOTICE_VERSION,
)
from app.modules.shipments.service import (
    cancel_shipment,
    cancel_shipment_with_reason,
    confirm_pre_registration,
    create_pre_registration,
    create_shipment,
    delete_expired_pre_registration,
    generate_label_pdf,
    generate_label_qr_png,
    get_label_data,
    get_shipment,
    get_shipment_by_code,
    list_shipments,
    mark_as_delivered,
    update_shipment,
)
from app.modules.claims.model import ShipmentTraceEvent


router = APIRouter(prefix="/encomiendas", tags=["shipments"])


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_shipment_endpoint(
    payload: ShipmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.write")),
) -> ShipmentResponse:
    origin_agency = get_agency_for_origin(db, payload.origin)
    if origin_agency is not None and not origin_agency.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La agencia de origen está inactiva")
    if is_business_user(current_user) and not is_global_admin(current_user):
        if origin_agency is None or origin_agency.id != current_user.agency_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El origen debe corresponder a la agencia asignada a tu usuario.",
            )
    elif origin_agency is None and current_user.agency_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El origen seleccionado no está vinculado a una agencia.",
        )
    return create_shipment(
        db,
        payload,
        agency_id=origin_agency.id if origin_agency is not None else current_user.agency_id,
        actor_user_id=current_user.id,
    )


@router.get("/aviso-privacidad", response_model=PrivacyNoticeResponse)
def get_public_privacy_notice() -> PrivacyNoticeResponse:
    return PrivacyNoticeResponse(
        version=PUBLIC_PRIVACY_NOTICE_VERSION,
        text="CARMENCITA EXPRESS CARGO S.A.C. (RUC 20609708850) tratará los datos del remitente y destinatario necesarios para registrar, gestionar, transportar y entregar el envío solicitado. La información se almacena en la base de datos de la empresa conforme a la Ley N.° 29733 y su reglamento.",
    )


@router.post(
    "/pre-registro",
    response_model=ShipmentPreRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pre_registration_endpoint(
    payload: ShipmentPreRegistrationCreate,
    db: Session = Depends(get_db),
) -> ShipmentPreRegistrationResponse:
    shipment = create_pre_registration(db, payload)
    return ShipmentPreRegistrationResponse(
        id=shipment.id,
        shipment_code=shipment.shipment_code,
        status=shipment.status,
        registration_origin=shipment.registration_origin,
        message="Pre-registro generado correctamente",
    )


@router.post("/registro-publico", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_public_shipment_endpoint(
    payload: ShipmentPreRegistrationCreate,
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    """Registro público informado; no acepta un id de agencia enviado por el cliente."""
    return create_shipment(db, payload, privacy_channel="PUBLIC_WEB")


@router.get("", response_model=list[ShipmentResponse])
def list_shipments_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.read")),
) -> list[ShipmentResponse]:
    return list_scoped_shipments(db, current_user)


@router.get("/reportes/operativo.pdf")
def export_operational_report_pdf_endpoint(
    fecha: date | None = Query(default=None),
    estado: str | None = Query(default=None),
    texto: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.read")),
) -> Response:
    content = generate_operational_report_pdf(
        db,
        report_date=fecha,
        status=estado,
        search=texto,
        agency_id=None if is_global_admin(current_user) else current_user.agency_id,
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="reporte_encomiendas.pdf"'},
    )


@router.get("/reportes/operativo.xlsx")
def export_operational_report_excel_endpoint(
    fecha: date | None = Query(default=None),
    estado: str | None = Query(default=None),
    texto: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.read")),
) -> Response:
    content = generate_operational_report_excel(
        db,
        report_date=fecha,
        status=estado,
        search=texto,
        agency_id=None if is_global_admin(current_user) else current_user.agency_id,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="reporte_encomiendas.xlsx"'},
    )


@router.get("/codigo/{codigo_encomienda}")
def get_public_shipment_status_endpoint(codigo_encomienda: str, db: Session = Depends(get_db)) -> dict:
    shipment = get_shipment_by_code(db, codigo_encomienda)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    events = (
        db.query(ShipmentTraceEvent)
        .filter(ShipmentTraceEvent.shipment_id == shipment.id, ShipmentTraceEvent.visible_to_customer.is_(True))
        .order_by(ShipmentTraceEvent.created_at.asc())
        .all()
    )
    return {
        "codigo_encomienda": shipment.shipment_code,
        "origen": shipment.origin,
        "destino": shipment.destination,
        "estado": shipment.status,
        "trazabilidad": [
            {
                "evento": event.event_type,
                "estado": event.status,
                "lugar": event.location,
                "detalle": event.description,
                "fecha": event.created_at,
            }
            for event in events
        ],
    }


@router.get("/interno/codigo/{codigo_encomienda}", response_model=ShipmentResponse)
def get_internal_shipment_by_code_endpoint(
    codigo_encomienda: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.read")),
) -> ShipmentResponse:
    shipment = get_shipment_by_code(db, codigo_encomienda)
    if shipment is None or (not is_global_admin(current_user) and shipment.agency_id != current_user.agency_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.get("/{encomienda_id}", response_model=ShipmentResponse)
def get_shipment_endpoint(
    encomienda_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.read")),
) -> ShipmentResponse:
    shipment = get_scoped_shipment(db, encomienda_id, current_user)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.post("/{encomienda_id}/confirmar-registro", response_model=ShipmentResponse)
def confirm_pre_registration_endpoint(
    encomienda_id: int,
    payload: ConfirmPreRegistrationRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.update")),
) -> ShipmentResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        shipment = confirm_pre_registration(
            db, encomienda_id, base_orientation=payload.base_orientation if payload else None,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.put("/{encomienda_id}", response_model=ShipmentResponse)
def update_shipment_endpoint(
    encomienda_id: int,
    payload: ShipmentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.update")),
) -> ShipmentResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    origin_agency = get_agency_for_origin(db, payload.origin)
    if origin_agency is not None and not origin_agency.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La agencia de origen está inactiva")
    if is_business_user(current_user) and not is_global_admin(current_user):
        if origin_agency is None or origin_agency.id != current_user.agency_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El origen debe corresponder a la agencia asignada a tu usuario.",
            )
    try:
        shipment = update_shipment(db, encomienda_id, payload, actor_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.post("/{encomienda_id}/anular", response_model=ShipmentDeleteResponse)
def cancel_shipment_with_reason_endpoint(
    encomienda_id: int,
    payload: ShipmentCancelRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.cancel")),
) -> ShipmentDeleteResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        shipment = cancel_shipment_with_reason(
            db, encomienda_id, payload.reason, actor_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return _cancel_response(shipment)


@router.delete(
    "/{encomienda_id}/pre-registro-vencido",
    response_model=ShipmentDeleteResponse,
)
def delete_expired_pre_registration_endpoint(
    encomienda_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.write")),
) -> ShipmentDeleteResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        shipment = delete_expired_pre_registration(
            db, encomienda_id, actor_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return _cancel_response(shipment)


@router.delete("/{encomienda_id}", response_model=ShipmentDeleteResponse)
def cancel_shipment_endpoint(
    encomienda_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("encomiendas.cancel")),
) -> ShipmentDeleteResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        shipment = cancel_shipment(db, encomienda_id, actor_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return _cancel_response(shipment)


@router.get("/{encomienda_id}/etiqueta", response_model=ShipmentLabelResponse)
def get_label_data_endpoint(
    encomienda_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("etiquetas.read")),
) -> ShipmentLabelResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        label = get_label_data(db, encomienda_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return label


@router.get("/{encomienda_id}/etiqueta/qr")
def get_label_qr_endpoint(
    encomienda_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("etiquetas.generate")),
) -> Response:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        png_bytes = generate_label_qr_png(db, encomienda_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if png_bytes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return Response(content=png_bytes, media_type="image/png")


@router.get("/{encomienda_id}/etiqueta/pdf")
def get_label_pdf_endpoint(
    encomienda_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("etiquetas.generate")),
) -> Response:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        result = generate_label_pdf(db, encomienda_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    filename, pdf_bytes = result
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{encomienda_id}/entregar", response_model=DeliveryResponse)
def deliver_shipment_endpoint(
    encomienda_id: int,
    payload: DeliveryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("tracking.update_status")),
) -> DeliveryResponse:
    if get_scoped_shipment(db, encomienda_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        shipment = mark_as_delivered(
            db, encomienda_id, payload, actor_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return DeliveryResponse(
        success=True,
        message="Encomienda entregada correctamente",
        id=shipment.id,
        shipment_code=shipment.shipment_code,
        status=shipment.status,
        delivered_at=shipment.delivered_at,
        receiver_document=shipment.delivery_receiver_document,
        signature_saved=bool(shipment.digital_signature_base64),
    )


def _cancel_response(shipment) -> ShipmentDeleteResponse:
    return ShipmentDeleteResponse(
        success=True,
        message="Encomienda anulada correctamente",
        id=shipment.id,
        shipment_code=shipment.shipment_code,
        status=shipment.status,
        cancellation_reason=shipment.cancellation_reason,
        canceled_at=shipment.canceled_at,
        charge_reversal="PENDIENTE_NO_INTEGRADO",
    )
