from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.measurement_logs.service import finish_open_boleta_log_by_shipment
from app.modules.shipments.service import get_shipment, get_shipment_by_code
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
def issue_receipt_endpoint(payload: ReceiptFromShipmentRequest, db: Session = Depends(get_db)) -> ReceiptResponse:
    try:
        return issue_receipt_from_shipment(
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


@router.post("/boletas/beta/pdf-desde-encomienda")
def generate_beta_pdf_endpoint(payload: ReceiptFromShipmentRequest, db: Session = Depends(get_db)) -> Response:
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
def generate_beta_xml_endpoint(payload: ReceiptFromShipmentRequest, db: Session = Depends(get_db)) -> dict:
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
def download_mock_pdf_endpoint(serie: str, numero: str, db: Session = Depends(get_db)) -> Response:
    record = get_mock_receipt(serie, numero)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mock receipt not found")

    pdf_bytes = generate_mock_receipt_pdf(record)
    shipment = get_shipment_by_code(db, record.shipment_code)
    if shipment is not None:
        finish_open_boleta_log_by_shipment(db, encomienda_id=shipment.id)
    filename = f"boleta_mock_{serie}_{numero}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/boletas/{serie}/{numero}/pdf")
def download_receipt_pdf_endpoint(serie: str, numero: str, db: Session = Depends(get_db)) -> Response:
    receipt = repository.get_receipt_by_series_number(db, serie, numero)
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    shipment = get_shipment(db, receipt.shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    pdf_bytes = generate_electronic_receipt_pdf(receipt, shipment)
    finish_open_boleta_log_by_shipment(db, encomienda_id=shipment.id)
    filename = f"boleta_{receipt.series}_{receipt.number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
