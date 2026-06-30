from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.asistente.schema import (
    BaseConocimientoCreate,
    BaseConocimientoResponse,
    ChatRequest,
    ChatResponse,
    LogAsistenteCreate,
    LogAsistenteReportResponse,
    LogAsistenteResponse,
    SolicitudRecojoCreate,
    SolicitudRecojoEstadoUpdate,
    SolicitudRecojoResponse,
    TipoContenidoCreate,
    TipoContenidoResponse,
    ValidacionCoherenciaRequest,
    ValidacionCoherenciaResponse,
)
from app.modules.asistente import service
from app.core.config import settings


asistente_router = APIRouter(prefix="/asistente", tags=["asistente"])
logs_asistente_router = APIRouter(prefix="/logs/asistente", tags=["logs asistente"])
base_conocimiento_router = APIRouter(prefix="/asistente/base-conocimiento", tags=["asistente"])
tipos_contenido_router = APIRouter(prefix="/asistente/tipos-contenido", tags=["asistente"])


# ── Status / Diagnóstico ──────────────────────────────────────────────────────

@asistente_router.get("/status")
def asistente_status() -> dict:
    """Estado de configuración del asistente (no expone claves completas)."""
    from app.integrations.llm import _call_groq_raw
    gk = settings.groq_api_key or ""
    result: dict = {
        "llm_enabled": settings.assistant_llm_enabled,
        "groq_key_set": bool(gk),
        "groq_model": settings.groq_model,
        "groq_test": None,
        "groq_error": None,
    }
    if settings.assistant_llm_enabled and gk:
        try:
            result["groq_test"] = _call_groq_raw("Responde solo: ok")
        except Exception as exc:
            result["groq_error"] = f"{type(exc).__name__}: {exc}"
    return result


# ── Chat ──────────────────────────────────────────────────────────────────────

@asistente_router.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    return service.process_chat(db, payload)


# ── Validación de coherencia del paquete ──────────────────────────────────────

@asistente_router.post("/validar-coherencia", response_model=ValidacionCoherenciaResponse)
def validar_coherencia_endpoint(
    payload: ValidacionCoherenciaRequest,
    db: Session = Depends(get_db),
) -> ValidacionCoherenciaResponse:
    resultado = service.validar_coherencia_paquete(db, payload)
    return ValidacionCoherenciaResponse(**resultado)


# ── Recojo Externo ────────────────────────────────────────────────────────────

@asistente_router.post(
    "/recojo-externo",
    response_model=SolicitudRecojoResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_recojo_externo(payload: SolicitudRecojoCreate, db: Session = Depends(get_db)) -> SolicitudRecojoResponse:
    return service.create_solicitud_recojo(db, payload)


@asistente_router.get("/recojo-externo", response_model=list[SolicitudRecojoResponse])
def list_recojo_externo(
    estado: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SolicitudRecojoResponse]:
    return service.list_solicitudes_recojo(db, estado=estado)


@asistente_router.get("/recojo-externo/{solicitud_id}", response_model=SolicitudRecojoResponse)
def get_recojo_externo(solicitud_id: int, db: Session = Depends(get_db)) -> SolicitudRecojoResponse:
    solicitud = service.get_solicitud_recojo(db, solicitud_id)
    if solicitud is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitud no encontrada")
    return solicitud


@asistente_router.patch("/recojo-externo/{solicitud_id}/estado", response_model=SolicitudRecojoResponse)
def update_recojo_estado(
    solicitud_id: int,
    payload: SolicitudRecojoEstadoUpdate,
    db: Session = Depends(get_db),
) -> SolicitudRecojoResponse:
    try:
        return service.update_solicitud_estado(db, solicitud_id, payload.estado)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ── Logs Asistente ────────────────────────────────────────────────────────────

@logs_asistente_router.post("", response_model=LogAsistenteResponse, status_code=status.HTTP_201_CREATED)
def create_log_asistente(payload: LogAsistenteCreate, db: Session = Depends(get_db)) -> LogAsistenteResponse:
    return service.create_log(db, payload)


@logs_asistente_router.get("", response_model=list[LogAsistenteResponse])
def list_logs_asistente(
    fecha_inicio: datetime | None = Query(default=None),
    fecha_fin: datetime | None = Query(default=None),
    etapa: str | None = Query(default=None),
    tipo_interaccion: str | None = Query(default=None),
    existe_error: bool | None = Query(default=None),
    ayudo_corregir_prevenir_error: bool | None = Query(default=None),
    tipo_error: str | None = Query(default=None),
    actor_origen: str | None = Query(default=None),
    canal: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogAsistenteResponse]:
    return service.list_logs(
        db,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        etapa=etapa,
        tipo_interaccion=tipo_interaccion,
        existe_error=existe_error,
        ayudo_corregir_prevenir_error=ayudo_corregir_prevenir_error,
        tipo_error=tipo_error,
        actor_origen=actor_origen,
        canal=canal,
    )


@logs_asistente_router.get("/reporte", response_model=list[LogAsistenteReportResponse])
def report_logs_asistente(
    fecha_inicio: datetime | None = Query(default=None),
    fecha_fin: datetime | None = Query(default=None),
    etapa: str | None = Query(default=None),
    tipo_interaccion: str | None = Query(default=None),
    existe_error: bool | None = Query(default=None),
    ayudo_corregir_prevenir_error: bool | None = Query(default=None),
    tipo_error: str | None = Query(default=None),
    actor_origen: str | None = Query(default=None),
    canal: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogAsistenteReportResponse]:
    return service.list_logs(
        db,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        etapa=etapa,
        tipo_interaccion=tipo_interaccion,
        existe_error=existe_error,
        ayudo_corregir_prevenir_error=ayudo_corregir_prevenir_error,
        tipo_error=tipo_error,
        actor_origen=actor_origen,
        canal=canal,
    )


@logs_asistente_router.get("/reporte/resumen")
def report_resumen_asistente(db: Session = Depends(get_db)) -> dict:
    return service.get_report_summary(db)


# ── Base de Conocimiento ──────────────────────────────────────────────────────

@base_conocimiento_router.post("", response_model=BaseConocimientoResponse, status_code=status.HTTP_201_CREATED)
def create_base_conocimiento(payload: BaseConocimientoCreate, db: Session = Depends(get_db)) -> BaseConocimientoResponse:
    return service.create_base_conocimiento(db, payload)


@base_conocimiento_router.get("", response_model=list[BaseConocimientoResponse])
def list_base_conocimiento(
    categoria: str | None = Query(default=None),
    activo: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[BaseConocimientoResponse]:
    return service.list_base_conocimiento(db, categoria=categoria, activo=activo)


# ── Tipos de Contenido ────────────────────────────────────────────────────────

@tipos_contenido_router.post("", response_model=TipoContenidoResponse, status_code=status.HTTP_201_CREATED)
def create_tipo_contenido(payload: TipoContenidoCreate, db: Session = Depends(get_db)) -> TipoContenidoResponse:
    return service.create_tipo_contenido(db, payload)


@tipos_contenido_router.get("", response_model=list[TipoContenidoResponse])
def list_tipos_contenido(
    activo: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[TipoContenidoResponse]:
    return service.list_tipos_contenido(db, activo=activo)
