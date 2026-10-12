from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.agencies.model import Agency
from app.modules.agencies.service import is_business_user, is_global_admin
from app.modules.claims.model import Claim
from app.modules.claims.schema import (
    ClaimDetailResponse,
    ClaimEventCreate,
    ClaimEventResponse,
    ClaimPrivacyNotice,
    ClaimPaymentVerification,
    ClaimResolutionCreate,
    ClaimResponse,
    ClaimStatusLookup,
    InPersonClaimCreate,
    InPersonClaimShipmentLookupResponse,
    PublicAgencyContact,
    PublicClaimCreate,
    PublicClaimCreateResponse,
    PublicClaimStatusResponse,
    ShipmentTraceCreate,
    ShipmentTraceResponse,
    MAX_IMAGE_BYTES,
)
from app.modules.claims.service import (
    add_claim_event,
    add_shipment_trace_event,
    create_in_person_claim,
    create_public_claim,
    get_claim_detail,
    get_public_claim_for_attachment,
    get_public_claim_status,
    get_scoped_claim,
    list_claims_for_user,
    public_agency_directory,
    public_claim_privacy_notice,
    save_attachment,
    save_claim_resolution,
    verify_claim_payment,
)
from app.modules.shipments.model import Shipment
from app.modules.shipments.repository import get_shipment_by_code
from app.modules.users.model import InternalUser


router = APIRouter(prefix="/reclamos", tags=["Reclamos"])


@router.get("/aviso-privacidad", response_model=ClaimPrivacyNotice)
def claim_privacy_notice_endpoint() -> ClaimPrivacyNotice:
    return public_claim_privacy_notice()


@router.get("/agencias", response_model=list[PublicAgencyContact])
def public_agency_directory_endpoint(db: Session = Depends(get_db)) -> list[PublicAgencyContact]:
    return public_agency_directory(db)


@router.get(
    "/publicos/encomiendas/{shipment_code}/remitente",
    response_model=InPersonClaimShipmentLookupResponse,
)
def lookup_public_claim_sender_endpoint(
    shipment_code: str,
    db: Session = Depends(get_db),
) -> InPersonClaimShipmentLookupResponse:
    shipment = get_shipment_by_code(db, shipment_code)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return InPersonClaimShipmentLookupResponse(
        shipment_code=shipment.shipment_code,
        sender_document_type=shipment.sender_document_type,
        sender_document_number=shipment.sender_document_number,
    )


@router.post("/publicos", response_model=PublicClaimCreateResponse, status_code=status.HTTP_201_CREATED)
def create_public_claim_endpoint(payload: PublicClaimCreate, db: Session = Depends(get_db)) -> PublicClaimCreateResponse:
    try:
        return create_public_claim(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/consulta", response_model=PublicClaimStatusResponse)
def public_claim_status_endpoint(payload: ClaimStatusLookup, db: Session = Depends(get_db)) -> PublicClaimStatusResponse:
    return get_public_claim_status(db, payload)


@router.post("/publicos/{case_code}/adjuntos", status_code=status.HTTP_201_CREATED)
async def upload_public_claim_evidence_endpoint(
    case_code: str,
    request: Request,
    codigo_encomienda: str = Header(alias="X-Codigo-Encomienda"),
    numero_documento: str = Header(alias="X-Numero-Documento"),
    nombre_archivo: str = Header(default="evidencia", alias="X-Nombre-Archivo"),
    db: Session = Depends(get_db),
) -> dict:
    from app.modules.claims.service import get_public_claim_for_attachment

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="La imagen supera 5 MB")
    claim = get_public_claim_for_attachment(db, case_code, codigo_encomienda, numero_documento)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")
    if claim.status in {"RESUELTO", "NO_PROCEDE", "CERRADO"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El caso ya está cerrado")
    try:
        item = save_attachment(
            db, claim, data=await _read_bounded_body(request), file_name=nombre_archivo,
            content_type=request.headers.get("content-type", ""),
            attachment_kind="EVIDENCIA_CLIENTE", current_user=None, visible_to_customer=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return item.model_dump(mode="json")


@router.get("", response_model=list[ClaimResponse])
def list_claims_endpoint(
    estado: str | None = Query(default=None),
    tipo: str | None = Query(default=None),
    agency_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.read")),
) -> list[ClaimResponse]:
    if is_global_admin(current_user) and agency_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selecciona una agencia para consultar sus reclamos")
    if not is_global_admin(current_user) and not is_business_user(current_user):
        return []
    return list_claims_for_user(db, current_user, status_filter=estado, agency_id=agency_id, kind=tipo)


@router.post("/presencial", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
def create_in_person_claim_endpoint(
    payload: InPersonClaimCreate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.create")),
) -> ClaimResponse:
    agency_id = payload.agency_id if is_global_admin(current_user) else current_user.agency_id
    if agency_id is None or (payload.agency_id is not None and payload.agency_id != agency_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agencia no encontrada")
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if agency is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agencia no encontrada")
    try:
        return create_in_person_claim(db, agency, payload, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/agencia/{agency_id}/encomiendas/{shipment_code}/remitente",
    response_model=InPersonClaimShipmentLookupResponse,
)
def lookup_in_person_claim_sender_endpoint(
    agency_id: int,
    shipment_code: str,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.create")),
) -> InPersonClaimShipmentLookupResponse:
    if not is_global_admin(current_user) and (
        not is_business_user(current_user) or current_user.agency_id != agency_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    agency = db.query(Agency).filter(Agency.id == agency_id, Agency.is_active.is_(True)).first()
    shipment = get_shipment_by_code(db, shipment_code)
    if (
        agency is None
        or shipment is None
        or (shipment.agency_id is not None and shipment.agency_id != agency_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return InPersonClaimShipmentLookupResponse(
        shipment_code=shipment.shipment_code,
        sender_document_type=shipment.sender_document_type,
        sender_document_number=shipment.sender_document_number,
    )


@router.get("/{claim_id}", response_model=ClaimDetailResponse)
def get_claim_endpoint(
    claim_id: int,
    agency_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.read")),
) -> ClaimDetailResponse:
    claim = get_scoped_claim(db, claim_id, current_user, agency_id=agency_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reclamo no encontrado")
    return get_claim_detail(db, claim)


@router.post("/{claim_id}/eventos", response_model=ClaimEventResponse)
def create_claim_event_endpoint(
    claim_id: int,
    payload: ClaimEventCreate,
    agency_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.update")),
) -> ClaimEventResponse:
    claim = get_scoped_claim(db, claim_id, current_user, agency_id=agency_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reclamo no encontrado")
    try:
        return add_claim_event(db, claim, payload, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{claim_id}/resolucion", response_model=ClaimResponse)
def resolve_claim_endpoint(
    claim_id: int,
    payload: ClaimResolutionCreate,
    agency_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.resolve")),
) -> ClaimResponse:
    claim = get_scoped_claim(db, claim_id, current_user, agency_id=agency_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reclamo no encontrado")
    try:
        return save_claim_resolution(db, claim, payload, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{claim_id}/verificar-pago", response_model=ClaimResponse)
def verify_claim_payment_endpoint(
    claim_id: int,
    payload: ClaimPaymentVerification,
    agency_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.verify_payment")),
) -> ClaimResponse:
    claim = get_scoped_claim(db, claim_id, current_user, agency_id=agency_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reclamo no encontrado")
    try:
        return verify_claim_payment(db, claim, current_user, payload.verified, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{claim_id}/adjuntos", status_code=status.HTTP_201_CREATED)
async def upload_internal_claim_attachment_endpoint(
    claim_id: int,
    request: Request,
    agency_id: int | None = Query(default=None, gt=0),
    attachment_kind: str = Header(alias="X-Tipo-Adjunto"),
    file_name: str = Header(default="evidencia", alias="X-Nombre-Archivo"),
    visible_to_customer: bool = Header(default=False, alias="X-Visible-Cliente"),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.update")),
) -> dict:
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="La imagen supera 5 MB")
    claim = get_scoped_claim(db, claim_id, current_user, agency_id=agency_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reclamo no encontrado")
    try:
        item = save_attachment(
            db, claim, data=await _read_bounded_body(request), file_name=file_name,
            content_type=request.headers.get("content-type", ""), attachment_kind=attachment_kind,
            current_user=current_user, visible_to_customer=visible_to_customer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return item.model_dump(mode="json")


@router.get("/{claim_id}/adjuntos/{attachment_id}")
def download_claim_attachment_endpoint(
    claim_id: int,
    attachment_id: int,
    agency_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("reclamos.read")),
) -> Response:
    from app.modules.claims.service import get_attachment

    claim = get_scoped_claim(db, claim_id, current_user, agency_id=agency_id)
    attachment = get_attachment(db, claim_id, attachment_id) if claim else None
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Adjunto no encontrado")
    return Response(content=attachment.data, media_type=attachment.content_type, headers={
        "Content-Disposition": f'inline; filename="{attachment.file_name}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


async def _read_bounded_body(request: Request) -> bytes:
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="La imagen supera 5 MB")
    return bytes(chunks)


@router.post("/agencia/{agency_id}/encomiendas/{shipment_id}/trazabilidad", response_model=ShipmentTraceResponse)
def add_shipment_trace_endpoint(
    agency_id: int,
    shipment_id: int,
    payload: ShipmentTraceCreate,
    db: Session = Depends(get_db),
    current_user: InternalUser = Depends(require_permission("tracking.update_status")),
) -> ShipmentTraceResponse:
    if not is_global_admin(current_user) and current_user.agency_id != agency_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id, Shipment.agency_id == agency_id).first()
    if shipment is None and is_global_admin(current_user):
        shipment = db.query(Shipment).filter(Shipment.id == shipment_id, Shipment.agency_id.is_(None)).first()
    if shipment is None and current_user.agency_id == agency_id:
        # An unassigned public/legacy shipment may be traced only after a complaint
        # explicitly associates it with this agency.
        shipment = db.query(Shipment).join(Claim, Claim.shipment_id == Shipment.id).filter(
            Shipment.id == shipment_id, Shipment.agency_id.is_(None), Claim.agency_id == agency_id
        ).first()
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encomienda no encontrada")
    return add_shipment_trace_event(db, shipment, agency_id, payload, current_user)
