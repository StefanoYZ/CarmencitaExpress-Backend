from io import BytesIO
import json

from sqlalchemy.orm import Session

from app.modules.shipments import repository
from app.modules.shipments.constants import (
    CANCELED_STATUS,
    DELIVERED_STATUS,
    EDITABLE_STATUS_VALUES,
    PRE_REGISTERED_STATUS,
)
from app.modules.shipments.model import Shipment
from app.modules.shipments.schema import (
    DeliveryRequest,
    LabelQrPayload,
    ShipmentCreate,
    ShipmentLabelResponse,
    ShipmentPreRegistrationCreate,
    ShipmentUpdate,
)


def create_shipment(db: Session, payload: ShipmentCreate) -> Shipment:
    return repository.create_shipment(db, payload)


def create_pre_registration(db: Session, payload: ShipmentPreRegistrationCreate) -> Shipment:
    return repository.create_pre_registration(db, payload)


def list_shipments(db: Session) -> list[Shipment]:
    return repository.list_shipments(db)


def get_shipment(db: Session, shipment_id: int) -> Shipment | None:
    return repository.get_shipment_by_id(db, shipment_id)


def get_shipment_by_code(db: Session, shipment_code: str) -> Shipment | None:
    return repository.get_shipment_by_code(db, shipment_code)


def mark_shipment_as_quoted(db: Session, shipment: Shipment) -> Shipment:
    return repository.mark_shipment_as_quoted(db, shipment)


def confirm_pre_registration(db: Session, shipment_id: int) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status == CANCELED_STATUS:
        raise ValueError("No se puede confirmar una encomienda anulada")
    if shipment.status != PRE_REGISTERED_STATUS:
        raise ValueError(f"No se puede confirmar una encomienda en estado {shipment.status}")
    return repository.confirm_pre_registration(db, shipment)


def update_shipment(db: Session, shipment_id: int, payload: ShipmentUpdate) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status not in EDITABLE_STATUS_VALUES:
        raise ValueError(f"No se puede editar una encomienda en estado {shipment.status}")
    if payload.status is not None and payload.status != shipment.status:
        raise ValueError("No se puede modificar el estado desde este endpoint")
    return repository.update_shipment(db, shipment, payload)


def cancel_shipment_with_reason(db: Session, shipment_id: int, reason: str) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status == CANCELED_STATUS:
        raise ValueError("La encomienda ya esta anulada")
    if shipment.status == DELIVERED_STATUS:
        raise ValueError("No se puede anular una encomienda entregada")
    if not reason or not reason.strip():
        raise ValueError("El motivo de anulacion es obligatorio")
    return repository.cancel_shipment_with_reason(db, shipment, reason.strip())


def cancel_shipment(db: Session, shipment_id: int) -> Shipment | None:
    return cancel_shipment_with_reason(db, shipment_id, "Anulacion solicitada desde endpoint DELETE")


def get_label_data(db: Session, shipment_id: int) -> ShipmentLabelResponse | None:
    shipment = repository.get_label_data(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status == CANCELED_STATUS:
        raise ValueError("No se puede generar etiqueta para una encomienda anulada")
    return ShipmentLabelResponse(
        shipment_code=shipment.shipment_code,
        origin=shipment.origin,
        destination=shipment.destination,
        sender=shipment.sender_name,
        recipient=shipment.recipient_name,
        qr_payload=LabelQrPayload(
            shipment_code=shipment.shipment_code,
            origin=shipment.origin,
            destination=shipment.destination,
            tracking=f"/tracking/{shipment.shipment_code}",
        ),
    )


def generate_label_qr_png(db: Session, shipment_id: int) -> bytes | None:
    label = get_label_data(db, shipment_id)
    if label is None:
        return None
    return _build_qr_png(label.qr_payload)


def generate_label_pdf(db: Session, shipment_id: int) -> tuple[str, bytes] | None:
    label = get_label_data(db, shipment_id)
    if label is None:
        return None

    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    width = 100 * mm
    height = 150 * mm
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setTitle(f"Etiqueta {label.shipment_code}")

    margin = 10 * mm
    qr_size = 38 * mm
    qr_bytes = _build_qr_png(label.qr_payload)

    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawString(margin, height - 18 * mm, "Carmencita Express Cargo")
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(margin, height - 32 * mm, label.shipment_code)

    pdf.drawImage(
        ImageReader(BytesIO(qr_bytes)),
        width - margin - qr_size,
        height - margin - qr_size,
        width=qr_size,
        height=qr_size,
    )

    y = height - 58 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, y, "Origen")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(margin, y - 6 * mm, _truncate(label.origin, 34))

    y -= 20 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, y, "Destino")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(margin, y - 6 * mm, _truncate(label.destination, 34))

    y -= 22 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, y, "Remitente")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, y - 6 * mm, _truncate(label.sender, 42))

    y -= 18 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, y, "Destinatario")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, y - 6 * mm, _truncate(label.recipient, 42))

    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin, 10 * mm, label.qr_payload.tracking)
    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    return f"etiqueta_{label.shipment_code}.pdf", buffer.read()


def mark_as_delivered(db: Session, shipment_id: int, payload: DeliveryRequest) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status == CANCELED_STATUS:
        raise ValueError("No se puede entregar una encomienda anulada")
    if shipment.status == DELIVERED_STATUS:
        raise ValueError("La encomienda ya fue entregada")
    if shipment.recipient_document_number and payload.receiver_document != shipment.recipient_document_number:
        raise ValueError("El DNI del receptor no coincide con el destinatario")
    if shipment.security_key and payload.security_key != shipment.security_key:
        raise ValueError("La clave de seguridad no coincide")
    return repository.mark_as_delivered(
        db=db,
        shipment=shipment,
        receiver_document=payload.receiver_document,
        signature_base64=payload.signature_base64,
    )


def _build_qr_png(qr_payload: LabelQrPayload) -> bytes:
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError("La dependencia qrcode no esta instalada") from exc

    qr_data = json.dumps(qr_payload.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))
    image = qrcode.make(qr_data)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."
