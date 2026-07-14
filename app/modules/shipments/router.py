from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
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
    ShipmentResponse,
    ShipmentUpdate,
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


router = APIRouter(prefix="/encomiendas", tags=["shipments"])


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_shipment_endpoint(payload: ShipmentCreate, db: Session = Depends(get_db)) -> ShipmentResponse:
    return create_shipment(db, payload)


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


@router.get("", response_model=list[ShipmentResponse])
def list_shipments_endpoint(db: Session = Depends(get_db)) -> list[ShipmentResponse]:
    return list_shipments(db)


@router.get("/reportes/operativo.pdf")
def export_operational_report_pdf_endpoint(
    fecha: date | None = Query(default=None),
    estado: str | None = Query(default=None),
    texto: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("encomiendas.read")),
) -> Response:
    content = generate_operational_report_pdf(
        db,
        report_date=fecha,
        status=estado,
        search=texto,
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
    _current_user=Depends(require_permission("encomiendas.read")),
) -> Response:
    content = generate_operational_report_excel(
        db,
        report_date=fecha,
        status=estado,
        search=texto,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="reporte_encomiendas.xlsx"'},
    )


@router.get("/codigo/{codigo_encomienda}", response_model=ShipmentResponse)
def get_shipment_by_code_endpoint(codigo_encomienda: str, db: Session = Depends(get_db)) -> ShipmentResponse:
    shipment = get_shipment_by_code(db, codigo_encomienda)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.get("/{encomienda_id}", response_model=ShipmentResponse)
def get_shipment_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> ShipmentResponse:
    shipment = get_shipment(db, encomienda_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


@router.post("/{encomienda_id}/confirmar-registro", response_model=ShipmentResponse)
def confirm_pre_registration_endpoint(
    encomienda_id: int,
    payload: ConfirmPreRegistrationRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    try:
        shipment = confirm_pre_registration(
            db, encomienda_id, base_orientation=payload.base_orientation if payload else None
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
) -> ShipmentResponse:
    try:
        shipment = update_shipment(db, encomienda_id, payload)
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
) -> ShipmentDeleteResponse:
    try:
        shipment = cancel_shipment_with_reason(db, encomienda_id, payload.reason)
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
    _current_user=Depends(require_permission("encomiendas.write")),
) -> ShipmentDeleteResponse:
    try:
        shipment = delete_expired_pre_registration(db, encomienda_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return _cancel_response(shipment)


@router.delete("/{encomienda_id}", response_model=ShipmentDeleteResponse)
def cancel_shipment_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> ShipmentDeleteResponse:
    try:
        shipment = cancel_shipment(db, encomienda_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return _cancel_response(shipment)


@router.get("/{encomienda_id}/etiqueta", response_model=ShipmentLabelResponse)
def get_label_data_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> ShipmentLabelResponse:
    try:
        label = get_label_data(db, encomienda_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return label


@router.get("/{encomienda_id}/etiqueta/qr")
def get_label_qr_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> Response:
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
def get_label_pdf_endpoint(encomienda_id: int, db: Session = Depends(get_db)) -> Response:
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
) -> DeliveryResponse:
    try:
        shipment = mark_as_delivered(db, encomienda_id, payload)
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
