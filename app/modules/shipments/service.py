from io import BytesIO
import json

from sqlalchemy.orm import Session

from app.modules.clients.service import upsert_client_from_person_data
from app.modules.measurement_logs.service import (
    ensure_boleta_log_after_payment,
    finish_service_phase,
    start_service_phase,
)
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
    _upsert_clients_from_shipment_payload(db, payload, commit=False)
    return repository.create_shipment(db, payload)


def create_pre_registration(db: Session, payload: ShipmentPreRegistrationCreate) -> Shipment:
    _upsert_clients_from_shipment_payload(db, payload, commit=False)
    shipment = repository.create_pre_registration(db, payload)
    start_service_phase(
        db,
        "registro",
        encomienda_id=shipment.id,
        timestamp_inicio=shipment.created_at,
    )
    return shipment


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
    shipment = repository.confirm_pre_registration(db, shipment)
    try:
        finish_service_phase(db, "registro", encomienda_id=shipment.id)
    except LookupError:
        start_service_phase(
            db,
            "registro",
            encomienda_id=shipment.id,
            timestamp_inicio=shipment.created_at,
        )
        finish_service_phase(db, "registro", encomienda_id=shipment.id)
    ensure_boleta_log_after_payment(db, encomienda_id=shipment.id)
    return shipment


def update_shipment(db: Session, shipment_id: int, payload: ShipmentUpdate) -> Shipment | None:
    shipment = repository.get_shipment_by_id(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status not in EDITABLE_STATUS_VALUES:
        raise ValueError(f"No se puede editar una encomienda en estado {shipment.status}")
    if payload.status is not None and payload.status != shipment.status:
        raise ValueError("No se puede modificar el estado desde este endpoint")
    _upsert_clients_from_shipment_payload(db, payload, commit=False)
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

    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    width = 100 * mm
    height = 150 * mm
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    pdf.setTitle(f"Etiqueta {label.shipment_code}")

    margin = 9 * mm
    qr_size = 34 * mm
    qr_bytes = _build_qr_png(label.qr_payload)
    primary = colors.HexColor("#28A745")
    dark = colors.HexColor("#212529")
    accent = colors.HexColor("#3C5940")
    soft = colors.HexColor("#E4ECE2")
    muted = colors.HexColor("#6C757D")

    pdf.setFillColor(primary)
    pdf.roundRect(0, height - 31 * mm, width, 31 * mm, 0, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(margin, height - 13 * mm, "CARMENCITA EXPRESS")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin, height - 19 * mm, "TRANSPORTE Y CARGA GENERAL")
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(margin, height - 26 * mm, "ETIQUETA DE ENCOMIENDA")

    card_top = height - 37 * mm
    pdf.setFillColor(soft)
    pdf.roundRect(margin, card_top - 28 * mm, width - (2 * margin), 28 * mm, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(margin + 5 * mm, card_top - 8 * mm, "CODIGO DE ENCOMIENDA")
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(margin + 5 * mm, card_top - 19 * mm, label.shipment_code)

    qr_x = width - margin - qr_size
    qr_y = card_top - 28 * mm - qr_size - 5 * mm
    pdf.setFillColor(colors.white)
    pdf.roundRect(qr_x - 2 * mm, qr_y - 2 * mm, qr_size + 4 * mm, qr_size + 4 * mm, 2 * mm, fill=1, stroke=0)
    pdf.drawImage(ImageReader(BytesIO(qr_bytes)), qr_x, qr_y, width=qr_size, height=qr_size)

    route_x = margin
    route_y = qr_y + qr_size - 1 * mm
    route_width = width - (3 * margin) - qr_size
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(route_x, route_y, "ORIGEN")
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(route_x, route_y - 6 * mm, _truncate(label.origin, 20))
    pdf.setStrokeColor(primary)
    pdf.setLineWidth(1.2)
    pdf.line(route_x, route_y - 11 * mm, route_x + route_width, route_y - 11 * mm)
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(route_x, route_y - 18 * mm, "DESTINO")
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(route_x, route_y - 24 * mm, _truncate(label.destination, 20))

    details_y = qr_y - 10 * mm
    pdf.setStrokeColor(soft)
    pdf.setLineWidth(0.8)
    pdf.line(margin, details_y + 4 * mm, width - margin, details_y + 4 * mm)

    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(margin, details_y, "REMITENTE")
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(margin, details_y - 6 * mm, _truncate(label.sender, 44))

    details_y -= 14 * mm
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(margin, details_y, "DESTINATARIO")
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(margin, details_y - 6 * mm, _truncate(label.recipient, 44))

    pdf.setFillColor(primary)
    pdf.rect(0, 0, width, 13 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(margin, 8 * mm, "ESCANEA EL QR PARA RASTREAR TU ENVIO")
    pdf.setFont("Helvetica", 7)
    pdf.drawString(margin, 3.5 * mm, _truncate(label.qr_payload.tracking, 48))
    pdf.setFillColor(muted)
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
    delivered = repository.mark_as_delivered(
        db=db,
        shipment=shipment,
        receiver_document=payload.receiver_document,
        signature_base64=payload.signature_base64,
    )
    try:
        finish_service_phase(db, "entrega", encomienda_id=delivered.id)
    except (LookupError, ValueError):
        pass
    return delivered


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


def _upsert_clients_from_shipment_payload(
    db: Session,
    payload: ShipmentCreate | ShipmentPreRegistrationCreate | ShipmentUpdate,
    *,
    commit: bool,
) -> None:
    if _is_dni_document(getattr(payload, "sender_document_type", None)):
        upsert_client_from_person_data(
            db,
            dni=getattr(payload, "sender_document_number", None),
            nombre_completo=getattr(payload, "sender_name", None),
            telefono=getattr(payload, "sender_phone", None),
            correo=getattr(payload, "sender_email", None),
            direccion=getattr(payload, "sender_address", None),
            commit=commit,
        )
    if _is_dni_document(getattr(payload, "recipient_document_type", None)):
        upsert_client_from_person_data(
            db,
            dni=getattr(payload, "recipient_document_number", None),
            nombre_completo=getattr(payload, "recipient_name", None),
            telefono=getattr(payload, "recipient_phone", None),
            correo=getattr(payload, "recipient_email", None),
            direccion=getattr(payload, "recipient_address", None),
            commit=commit,
        )


def _is_dni_document(document_type: str | None) -> bool:
    return bool(document_type and document_type.strip().upper() == "DNI")
