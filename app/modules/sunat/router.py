from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.agencies.service import get_scoped_shipment
from app.modules.measurement_logs.service import finish_open_boleta_log_by_shipment
from app.modules.shipments.service import get_shipment, get_shipment_by_code
from app.modules.shipments.tracing import append_shipment_trace_event
from app.modules.users.model import InternalUser
from app.modules.sunat import repository
from app.modules.sunat.exceptions import LycetClientError, SunatEmissionBlockedError
from app.modules.sunat.pdf_service import generate_electronic_receipt_pdf, generate_mock_receipt_pdf
from app.modules.sunat.schema import ReceiptFromShipmentRequest, ReceiptResponse
from app.modules.sunat.service import (
    generate_beta_pdf_from_shipment,
    generate_beta_xml_from_shipment,
    get_mock_receipt,
    issue_receipt_from_shipment,
)


router = APIRouter(prefix="/sunat", tags=["sunat"])


@router.post("/boletas/emitir-desde-encomienda", response_model=ReceiptResponse)
def issue_receipt_endpoint(
    payload: ReceiptFromShipmentRequest,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("sunat.emit")),
) -> ReceiptResponse:
    if get_scoped_shipment(db, payload.shipment_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        receipt = issue_receipt_from_shipment(
            db=db,
            shipment_id=payload.shipment_id,
            confirm_payment=payload.confirm_payment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SunatEmissionBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LycetClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    shipment = get_shipment(db, payload.shipment_id)
    if shipment is not None:
        append_shipment_trace_event(
            db,
            shipment,
            event_type="BOLETA_EMITIDA",
            description="Se emitió la boleta electrónica del envío.",
            actor=current_user,
            source="INTERNO",
            visible_to_customer=True,
        )
        db.commit()
    return receipt


@router.post("/boletas/beta/pdf-desde-encomienda")
def generate_beta_pdf_endpoint(
    payload: ReceiptFromShipmentRequest,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("sunat.emit")),
) -> Response:
    if get_scoped_shipment(db, payload.shipment_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        filename, pdf_bytes = generate_beta_pdf_from_shipment(
            db=db,
            shipment_id=payload.shipment_id,
            confirm_payment=payload.confirm_payment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SunatEmissionBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LycetClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    finish_open_boleta_log_by_shipment(db, encomienda_id=payload.shipment_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/boletas/beta/xml-desde-encomienda")
def generate_beta_xml_endpoint(
    payload: ReceiptFromShipmentRequest,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("sunat.read")),
) -> dict:
    if get_scoped_shipment(db, payload.shipment_id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    try:
        return generate_beta_xml_from_shipment(
            db=db,
            shipment_id=payload.shipment_id,
            confirm_payment=payload.confirm_payment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SunatEmissionBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LycetClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/boletas/mock/{serie}/{numero}/pdf")
def download_mock_pdf_endpoint(
    serie: str,
    numero: str,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("sunat.download_pdf")),
) -> Response:
    record = get_mock_receipt(serie, numero)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mock receipt not found")

    pdf_bytes = generate_mock_receipt_pdf(record)
    shipment = get_shipment_by_code(db, record.shipment_code)
    if shipment is None or get_scoped_shipment(db, shipment.id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    if shipment is not None:
        finish_open_boleta_log_by_shipment(db, encomienda_id=shipment.id)
    filename = f"boleta_mock_{serie}_{numero}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/boletas/{serie}/{numero}/pdf")
def download_receipt_pdf_endpoint(
    serie: str,
    numero: str,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("sunat.download_pdf")),
) -> Response:
    receipt = repository.get_receipt_by_series_number(db, serie, numero)
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    shipment = get_shipment(db, receipt.shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    if get_scoped_shipment(db, shipment.id, current_user) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    pdf_bytes = generate_electronic_receipt_pdf(receipt, shipment)
    finish_open_boleta_log_by_shipment(db, encomienda_id=shipment.id)
    filename = f"boleta_{receipt.series}_{receipt.number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
