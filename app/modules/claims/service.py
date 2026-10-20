from datetime import datetime, timezone
import hashlib
import re
import secrets
from urllib.parse import unquote

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, load_only

from app.core.config import settings
from app.modules.agencies.model import Agency
from app.modules.claims.model import Claim, ClaimAttachment, ClaimEvent, ShipmentTraceEvent
from app.modules.claims.schema import (
    CLAIM_NOTICE_VERSION,
    CLAIM_CATEGORIES,
    CLAIM_STATUSES,
    ClaimAttachmentResponse,
    ClaimEventCreate,
    ClaimEventResponse,
    ClaimResolutionCreate,
    ClaimResponse,
    ClaimShipmentSummary,
    ClaimStatusLookup,
    ClaimDetailResponse,
    ClaimPrivacyNotice,
    InPersonClaimCreate,
    PublicAgencyContact,
    PublicClaimCreate,
    PublicClaimCreateResponse,
    PublicClaimStatusResponse,
    ShipmentTraceCreate,
    ShipmentTraceResponse,
    MAX_IMAGE_BYTES,
)
from app.modules.shipments.model import Shipment
from app.modules.users.model import InternalUser


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
BUSINESS_ROLES = {"AGENCY_ADMIN", "SECRETARIA"}
STATUS_TRANSITIONS = {
    "RECIBIDO": {"EN_REVISION", "CERRADO"},
    "EN_REVISION": {"ESPERANDO_INFORMACION", "INVESTIGANDO", "PROPUESTA_ENVIADA", "PAGO_POR_VERIFICAR", "NO_PROCEDE", "CERRADO"},
    "ESPERANDO_INFORMACION": {"EN_REVISION", "INVESTIGANDO", "CERRADO"},
    "INVESTIGANDO": {"ESPERANDO_INFORMACION", "PROPUESTA_ENVIADA", "PAGO_POR_VERIFICAR", "NO_PROCEDE", "CERRADO"},
    "PROPUESTA_ENVIADA": {"EN_REVISION", "PAGO_POR_VERIFICAR", "RESUELTO", "CERRADO"},
    "PAGO_POR_VERIFICAR": {"RESUELTO", "INVESTIGANDO"},
    "RESUELTO": {"CERRADO", "INVESTIGANDO"},
    "NO_PROCEDE": {"CERRADO", "EN_REVISION"},
    "CERRADO": set(),
}


def public_agency_directory(db: Session) -> list[PublicAgencyContact]:
    agencies = db.query(Agency).filter(Agency.is_active.is_(True)).order_by(Agency.id).all()
    return [
        PublicAgencyContact(
            id=agency.id,
            code=agency.code,
            place=agency.destination.name,
            phone=agency.phone,
            address=agency.address,
        )
        for agency in agencies
    ]


def public_claim_privacy_notice() -> ClaimPrivacyNotice:
    address = (settings.claims_company_address or "").strip() or None
    email = (settings.claims_contact_email or "").strip() or None
    return ClaimPrivacyNotice(
        version=CLAIM_NOTICE_VERSION,
        company_name="CARMENCITA EXPRESS CARGO S.A.C.",
        company_ruc="20609708850",
        company_address=address,
        contact_email=email,
        text=(
            "CARMENCITA EXPRESS CARGO S.A.C. tratará los datos necesarios para atender y dar seguimiento "
            "a tu reporte sobre la encomienda. Los datos se almacenarán para gestionar el caso y comunicarse contigo."
        ),
    )


def create_public_claim(db: Session, payload: PublicClaimCreate) -> PublicClaimCreateResponse:
    shipment = _find_shipment(db, payload.shipment_code)
    if shipment is None:
        raise _not_found()
    claimant_role = _match_claimant(shipment, payload.document_number)
    agency = db.query(Agency).filter(Agency.id == payload.agency_id, Agency.is_active.is_(True)).first()
    if agency is None:
        raise _not_found()
    if shipment.agency_id is not None and shipment.agency_id != agency.id:
        raise _not_found()

    claim = Claim(
        case_code=_new_case_code(),
        shipment_id=shipment.id,
        agency_id=agency.id,
        source="WEB",
        kind="OPERATIVO",
        formal_type=None,
        category=payload.category,
        claimant_role=claimant_role,
        claimant_name=shipment.sender_name if claimant_role == "REMITENTE" else shipment.recipient_name,
        claimant_document_type=shipment.sender_document_type if claimant_role == "REMITENTE" else (shipment.recipient_document_type or "DNI"),
        claimant_document_number=payload.document_number,
        contact_phone=payload.contact_phone or (shipment.sender_phone if claimant_role == "REMITENTE" else shipment.recipient_phone),
        contact_email=payload.contact_email,
        description=payload.description.strip(),
        requested_solution=(payload.requested_solution or "").strip() or None,
        status="RECIBIDO",
        privacy_notice_version=CLAIM_NOTICE_VERSION,
        privacy_notice_accepted_at=datetime.now(timezone.utc),
        response_due_at=None,
    )
    db.add(claim)
    db.flush()
    _add_claim_event(db, claim, "RECIBIDO", "Hemos recibido tu solicitud.", visible=True)
    db.commit()
    db.refresh(claim)
    return PublicClaimCreateResponse(
        case_code=claim.case_code,
        status=claim.status,
        message="Recibimos tu reclamo. Guarda el número de caso para consultar su avance.",
    )


def create_in_person_claim(
    db: Session,
    agency: Agency,
    payload: InPersonClaimCreate,
    current_user: InternalUser,
) -> ClaimResponse:
    shipment = _find_shipment(db, payload.shipment_code)
    if shipment is None or (shipment.agency_id is not None and shipment.agency_id != agency.id):
        raise _not_found()
    claimant_role = _match_claimant(shipment, payload.claimant_document_number)
    claim = Claim(
        case_code=_new_case_code(),
        shipment_id=shipment.id,
        agency_id=agency.id,
        source="PRESENCIAL",
        kind="OPERATIVO",
        formal_type=None,
        category=_normalize_category(payload.category),
        claimant_role=claimant_role,
        claimant_name=shipment.sender_name if claimant_role == "REMITENTE" else shipment.recipient_name,
        claimant_document_type=shipment.sender_document_type if claimant_role == "REMITENTE" else (shipment.recipient_document_type or "DNI"),
        claimant_document_number=payload.claimant_document_number,
        contact_phone=payload.contact_phone or (shipment.sender_phone if claimant_role == "REMITENTE" else shipment.recipient_phone),
        contact_email=payload.contact_email,
        description=payload.description.strip(),
        requested_solution=(payload.requested_solution or "").strip() or None,
        status="RECIBIDO",
        created_by_user_id=current_user.id,
        privacy_notice_version=CLAIM_NOTICE_VERSION,
        privacy_notice_accepted_at=datetime.now(timezone.utc),
        response_due_at=None,
    )
    db.add(claim)
    db.flush()
    _add_claim_event(db, claim, "RECIBIDO", "Reclamo ingresado presencialmente.", current_user.id, visible=True)
    db.commit()
    db.refresh(claim)
    return ClaimResponse.model_validate(claim)


def list_claims_for_user(
    db: Session,
    current_user: InternalUser,
    *,
    status_filter: str | None = None,
    agency_id: int | None = None,
    kind: str | None = None,
) -> list[ClaimResponse]:
    query = db.query(Claim)
    if _is_global_admin(current_user):
        if agency_id is None:
            return []
        query = query.filter(Claim.agency_id == agency_id)
    else:
        if current_user.agency_id is None or not _has_business_role(current_user):
            return []
        if agency_id is not None and current_user.agency_id != agency_id:
            return []
        query = query.filter(Claim.agency_id == current_user.agency_id)
    if status_filter:
        query = query.filter(Claim.status == status_filter.strip().upper())
    if kind:
        query = query.filter(Claim.kind == kind.strip().upper())
    return [ClaimResponse.model_validate(claim) for claim in query.order_by(Claim.created_at.desc()).limit(300).all()]


def get_scoped_claim(
    db: Session,
    claim_id: int,
    current_user: InternalUser,
    agency_id: int | None = None,
) -> Claim | None:
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if claim is None:
        return None
    if _is_global_admin(current_user):
        return claim if agency_id is not None and agency_id == claim.agency_id else None
    if _has_business_role(current_user) and current_user.agency_id == claim.agency_id and (agency_id is None or agency_id == current_user.agency_id):
        return claim
    return None


def list_claim_events(db: Session, claim_id: int) -> list[ClaimEventResponse]:
    events = db.query(ClaimEvent).filter(ClaimEvent.claim_id == claim_id).order_by(ClaimEvent.created_at.asc()).all()
    return [ClaimEventResponse.model_validate(event) for event in events]


def list_claim_attachments(db: Session, claim_id: int) -> list[ClaimAttachmentResponse]:
    attachments = (
        db.query(ClaimAttachment)
        .options(load_only(
            ClaimAttachment.id, ClaimAttachment.claim_id, ClaimAttachment.attachment_kind,
            ClaimAttachment.file_name, ClaimAttachment.content_type, ClaimAttachment.file_size,
            ClaimAttachment.visible_to_customer, ClaimAttachment.created_at,
        ))
        .filter(ClaimAttachment.claim_id == claim_id)
        .order_by(ClaimAttachment.created_at.asc())
        .all()
    )
    return [ClaimAttachmentResponse.model_validate(item) for item in attachments]


def get_public_claim_status(db: Session, payload: ClaimStatusLookup) -> list[PublicClaimStatusResponse]:
    query = db.query(Claim).join(Shipment, Claim.shipment_id == Shipment.id)
    if payload.case_code:
        query = query.filter(Claim.case_code == payload.case_code)
    if payload.shipment_code:
        query = query.filter(Shipment.shipment_code == payload.shipment_code)
    if payload.document_number:
        query = query.filter(Claim.claimant_document_number == payload.document_number)

    claims = query.order_by(Claim.created_at.desc(), Claim.id.desc()).limit(100).all()
    if not claims:
        raise _not_found()
    return [
        PublicClaimStatusResponse(
            case_code=claim.case_code,
            status=claim.status,
            created_at=claim.created_at,
        )
        for claim in claims
    ]


def get_public_claim_for_attachment(
    db: Session,
    case_code: str,
    shipment_code: str,
    document_number: str,
) -> Claim | None:
    claim = db.query(Claim).filter(Claim.case_code == case_code.strip().upper()).first()
    shipment = _find_shipment(db, shipment_code)
    if claim is None or shipment is None or claim.shipment_id != shipment.id:
        return None
    return claim if _matches_claimant(shipment, document_number.strip()) else None


def get_claim_detail(db: Session, claim: Claim) -> ClaimDetailResponse:
    shipment = _find_shipment_by_id(db, claim.shipment_id)
    if shipment is None:
        raise _not_found()
    shipment_events = list_shipment_trace(db, claim.shipment_id)
    return ClaimDetailResponse(
        claim=ClaimResponse.model_validate(claim),
        shipment=ClaimShipmentSummary(
            id=shipment.id,
            shipment_code=shipment.shipment_code,
            origin=shipment.origin,
            destination=shipment.destination,
            status=shipment.status,
            created_at=shipment.created_at,
        ),
        events=list_claim_events(db, claim.id),
        shipment_events=shipment_events,
        attachments=list_claim_attachments(db, claim.id),
    )


def add_claim_event(db: Session, claim: Claim, payload: ClaimEventCreate, current_user: InternalUser) -> ClaimEventResponse:
    old_status = claim.status
    if payload.to_status:
        active_roles = {role.name for role in current_user.roles if role.is_active}
        privileged_statuses = {"NO_PROCEDE", "CERRADO"}
        forbidden_statuses = {"RESUELTO", "PAGO_POR_VERIFICAR", "PROPUESTA_ENVIADA"}
        if payload.to_status in forbidden_statuses:
            raise ValueError("Este estado solo se aplica mediante el flujo de resolución y verificación")
        if payload.to_status in privileged_statuses and not active_roles.intersection({"ADMIN_GENERAL", "AGENCY_ADMIN", "DEVELOPER"}):
            raise ValueError("Solo el administrador de agencia puede cerrar o descartar un caso")
        if payload.to_status not in CLAIM_STATUSES:
            raise ValueError("Estado de reclamo inválido")
        if payload.to_status not in STATUS_TRANSITIONS.get(old_status, set()):
            raise ValueError(f"No se permite cambiar de {old_status} a {payload.to_status}")
        claim.status = payload.to_status
        if payload.to_status in {"RESUELTO", "CERRADO"}:
            claim.resolved_at = datetime.now(timezone.utc)
    event = _add_claim_event(
        db, claim, payload.event_type, payload.note.strip(), current_user.id,
        from_status=old_status if payload.to_status else None,
        to_status=payload.to_status,
        visible=payload.visible_to_customer,
    )
    db.add(claim)
    db.commit()
    db.refresh(event)
    return ClaimEventResponse.model_validate(event)


def save_claim_resolution(db: Session, claim: Claim, payload: ClaimResolutionCreate, current_user: InternalUser) -> ClaimResponse:
    if claim.status in {"RESUELTO", "CERRADO", "NO_PROCEDE"}:
        raise ValueError("El caso ya está cerrado y no admite una nueva resolución")
    old_status = claim.status
    claim.resolution_recorded_by_user_id = current_user.id
    claim.resolution_type = payload.resolution_type
    claim.resolution_text = payload.resolution_text.strip()
    claim.resolution_amount = payload.amount
    claim.resolution_currency = payload.currency if payload.amount else None
    claim.payment_method = payload.payment_method
    claim.payment_reference = payload.payment_reference
    claim.payment_proof_attachment_id = payload.payment_proof_attachment_id
    if payload.resolution_type == "MONETARIA":
        proof = db.query(ClaimAttachment).filter(
            ClaimAttachment.id == payload.payment_proof_attachment_id,
            ClaimAttachment.claim_id == claim.id,
            ClaimAttachment.attachment_kind == "COMPROBANTE_PAGO",
        ).first()
        if proof is None:
            raise ValueError("Adjunta el comprobante de pago de este reclamo")
        claim.status = "PAGO_POR_VERIFICAR"
        note = "Se registró una solución monetaria; el pago está pendiente de verificación."
        event_type = "PAGO_POR_VERIFICAR"
    else:
        claim.status = "RESUELTO"
        claim.resolved_by_user_id = current_user.id
        claim.resolved_at = datetime.now(timezone.utc)
        note = f"Solución registrada: {claim.resolution_text}"
        event_type = "RESOLUCION_REGISTRADA"
    db.add(claim)
    _add_claim_event(db, claim, event_type, note, current_user.id, old_status, claim.status, visible=True)
    db.commit()
    db.refresh(claim)
    return ClaimResponse.model_validate(claim)


def verify_claim_payment(db: Session, claim: Claim, current_user: InternalUser, verified: bool, note: str) -> ClaimResponse:
    if claim.status != "PAGO_POR_VERIFICAR" or claim.resolution_type != "MONETARIA":
        raise ValueError("El caso no tiene un pago pendiente de verificación")
    old_status = claim.status
    if verified:
        claim.status = "RESUELTO"
        claim.resolved_by_user_id = current_user.id
        claim.payment_verified_by_id = current_user.id
        claim.payment_verified_at = datetime.now(timezone.utc)
        claim.resolved_at = claim.payment_verified_at
        event_type = "PAGO_VERIFICADO"
        public_note = "El pago de la solución fue verificado y el reclamo está resuelto."
    else:
        claim.status = "INVESTIGANDO"
        event_type = "PAGO_OBSERVADO"
        public_note = "El comprobante requiere revisión. La agencia se comunicará contigo."
    db.add(claim)
    _add_claim_event(db, claim, event_type, note.strip() or public_note, current_user.id, old_status, claim.status, visible=False)
    _add_claim_event(db, claim, "ACTUALIZACION_CLIENTE", public_note, current_user.id, old_status, claim.status, visible=True)
    db.commit()
    db.refresh(claim)
    return ClaimResponse.model_validate(claim)


def add_shipment_trace_event(
    db: Session,
    shipment: Shipment,
    agency_id: int,
    payload: ShipmentTraceCreate,
    current_user: InternalUser,
) -> ShipmentTraceResponse:
    event = ShipmentTraceEvent(
        shipment_id=shipment.id,
        agency_id=agency_id,
        actor_user_id=current_user.id,
        event_type=payload.event_type,
        status=payload.status,
        location=payload.location.strip(),
        description=payload.description.strip(),
        source="MANUAL",
        visible_to_customer=payload.visible_to_customer,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return ShipmentTraceResponse.model_validate(event)


def list_shipment_trace(db: Session, shipment_id: int, public_only: bool = False) -> list[ShipmentTraceResponse]:
    query = db.query(ShipmentTraceEvent).filter(ShipmentTraceEvent.shipment_id == shipment_id)
    if public_only:
        query = query.filter(ShipmentTraceEvent.visible_to_customer.is_(True))
    events = query.order_by(ShipmentTraceEvent.created_at.asc()).all()
    return [ShipmentTraceResponse.model_validate(event) for event in events]


def save_attachment(
    db: Session,
    claim: Claim,
    *,
    data: bytes,
    file_name: str,
    content_type: str,
    attachment_kind: str,
    current_user: InternalUser | None,
    visible_to_customer: bool = False,
) -> ClaimAttachmentResponse:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("La imagen debe pesar como máximo 5 MB")
    if content_type not in ALLOWED_IMAGE_TYPES or not _matches_image_signature(data, content_type):
        raise ValueError("Formato de imagen no válido; usa JPG, PNG o WebP")
    kind = attachment_kind.strip().upper()
    if kind not in {"EVIDENCIA_CLIENTE", "COMPROBANTE_PAGO", "OTRO"}:
        raise ValueError("Tipo de adjunto no válido")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", unquote(file_name).strip())[-180:] or "evidencia"
    item = ClaimAttachment(
        claim_id=claim.id,
        uploaded_by_user_id=current_user.id if current_user else None,
        attachment_kind=kind,
        file_name=safe_name,
        content_type=content_type,
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
        visible_to_customer=visible_to_customer,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ClaimAttachmentResponse.model_validate(item)


def get_attachment(db: Session, claim_id: int, attachment_id: int) -> ClaimAttachment | None:
    return db.query(ClaimAttachment).filter(
        ClaimAttachment.id == attachment_id, ClaimAttachment.claim_id == claim_id
    ).first()


def _add_claim_event(
    db: Session,
    claim: Claim,
    event_type: str,
    note: str,
    actor_user_id: int | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    visible: bool = False,
) -> ClaimEvent:
    event = ClaimEvent(
        claim_id=claim.id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        note=note,
        visible_to_customer=visible,
    )
    db.add(event)
    return event


def _find_shipment(db: Session, code: str) -> Shipment | None:
    from app.modules.shipments.repository import get_shipment_by_code

    return get_shipment_by_code(db, code)


def _find_shipment_by_id(db: Session, shipment_id: int) -> Shipment | None:
    return db.query(Shipment).filter(Shipment.id == shipment_id).first()


def _match_claimant(shipment: Shipment, document_number: str) -> str:
    document_number = document_number.strip()
    if secrets.compare_digest(shipment.sender_document_number, document_number):
        return "REMITENTE"
    if shipment.recipient_document_number and secrets.compare_digest(shipment.recipient_document_number, document_number):
        return "DESTINATARIO"
    raise _not_found()


def _new_case_code() -> str:
    return f"RC-{secrets.token_hex(7).upper()}"


def _normalize_category(value: str) -> str:
    value = value.strip().upper()
    if value not in CLAIM_CATEGORIES:
        raise ValueError("Selecciona una categoría válida")
    return value


def _is_global_admin(user: InternalUser) -> bool:
    return any(role.name in {"ADMIN_GENERAL", "DEVELOPER"} and role.is_active for role in user.roles)


def _has_business_role(user: InternalUser) -> bool:
    return any(role.name in BUSINESS_ROLES and role.is_active for role in user.roles)


def _matches_claimant(shipment: Shipment, document_number: str) -> bool:
    return (
        secrets.compare_digest(shipment.sender_document_number, document_number)
        or bool(shipment.recipient_document_number and secrets.compare_digest(shipment.recipient_document_number, document_number))
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos el caso o no se pudo validar la encomienda")


def _matches_image_signature(data: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False
