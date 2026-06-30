"""Capa de acceso a datos del módulo asistente.

Contiene únicamente consultas/persistencia (sin reglas de negocio). El service
orquesta y aplica la lógica; aquí solo se habla con la base de datos.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.business_time import business_now
from app.modules.asistente.model import (
    AsistenteBaseConocimiento,
    AsistenteBusquedaWebCache,
    LogInteraccionAsistente,
    SolicitudRecojoExterno,
    TiposContenidoTransporte,
)
from app.modules.shipments.model import Shipment


# ── Logs de interacción ───────────────────────────────────────────────────────

def add_log(db: Session, **campos) -> LogInteraccionAsistente:
    """Crea y persiste un log de interacción del asistente."""
    campos.setdefault("metodo", "Sistema")
    log = LogInteraccionAsistente(
        fecha=business_now(),
        timestamp=business_now(),
        **campos,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_logs(
    db: Session,
    *,
    fecha_inicio: datetime | None = None,
    fecha_fin: datetime | None = None,
    etapa: str | None = None,
    tipo_interaccion: str | None = None,
    existe_error: bool | None = None,
    ayudo_corregir_prevenir_error: bool | None = None,
    tipo_error: str | None = None,
    actor_origen: str | None = None,
    canal: str | None = None,
) -> list[LogInteraccionAsistente]:
    query = db.query(LogInteraccionAsistente)
    if fecha_inicio:
        query = query.filter(LogInteraccionAsistente.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(LogInteraccionAsistente.fecha <= fecha_fin)
    if etapa:
        query = query.filter(LogInteraccionAsistente.etapa == etapa)
    if tipo_interaccion:
        query = query.filter(LogInteraccionAsistente.tipo_interaccion == tipo_interaccion)
    if existe_error is not None:
        query = query.filter(LogInteraccionAsistente.existe_error == existe_error)
    if ayudo_corregir_prevenir_error is not None:
        query = query.filter(
            LogInteraccionAsistente.ayudo_corregir_prevenir_error == ayudo_corregir_prevenir_error
        )
    if tipo_error:
        query = query.filter(LogInteraccionAsistente.tipo_error == tipo_error)
    if actor_origen:
        query = query.filter(LogInteraccionAsistente.actor_origen == actor_origen)
    if canal:
        query = query.filter(LogInteraccionAsistente.canal == canal)
    return query.order_by(LogInteraccionAsistente.id.desc()).all()


def all_logs(db: Session) -> list[LogInteraccionAsistente]:
    return db.query(LogInteraccionAsistente).all()


# ── Solicitudes de recojo externo ─────────────────────────────────────────────

def add_solicitud_recojo(db: Session, solicitud: SolicitudRecojoExterno) -> SolicitudRecojoExterno:
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud


def list_solicitudes_recojo(db: Session, *, estado: str | None = None) -> list[SolicitudRecojoExterno]:
    query = db.query(SolicitudRecojoExterno)
    if estado:
        query = query.filter(SolicitudRecojoExterno.estado == estado)
    return query.order_by(SolicitudRecojoExterno.id.desc()).all()


def get_solicitud_recojo(db: Session, solicitud_id: int) -> SolicitudRecojoExterno | None:
    return (
        db.query(SolicitudRecojoExterno)
        .filter(SolicitudRecojoExterno.id == solicitud_id)
        .first()
    )


def save_solicitud_recojo(db: Session, solicitud: SolicitudRecojoExterno) -> SolicitudRecojoExterno:
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud


# ── Base de conocimiento ──────────────────────────────────────────────────────

def add_base_conocimiento(db: Session, entry: AsistenteBaseConocimiento) -> AsistenteBaseConocimiento:
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_base_conocimiento(
    db: Session, *, categoria: str | None = None, activo: bool | None = None
) -> list[AsistenteBaseConocimiento]:
    query = db.query(AsistenteBaseConocimiento)
    if categoria:
        query = query.filter(AsistenteBaseConocimiento.categoria == categoria)
    if activo is not None:
        query = query.filter(AsistenteBaseConocimiento.activo == activo)
    return query.order_by(AsistenteBaseConocimiento.id.asc()).all()


# ── Tipos de contenido ────────────────────────────────────────────────────────

def add_tipo_contenido(db: Session, entry: TiposContenidoTransporte) -> TiposContenidoTransporte:
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_tipos_contenido(db: Session, *, activo: bool | None = None) -> list[TiposContenidoTransporte]:
    query = db.query(TiposContenidoTransporte)
    if activo is not None:
        query = query.filter(TiposContenidoTransporte.activo == activo)
    return query.order_by(TiposContenidoTransporte.nombre.asc()).all()


# ── Caché de búsquedas web ────────────────────────────────────────────────────

def get_cache_web(db: Session, clave: str) -> AsistenteBusquedaWebCache | None:
    return (
        db.query(AsistenteBusquedaWebCache)
        .filter(AsistenteBusquedaWebCache.consulta_clave == clave)
        .first()
    )


def upsert_cache_web(
    db: Session, *, clave: str, consulta_original: str, respuesta: str, resultados_json: str
) -> AsistenteBusquedaWebCache:
    entry = get_cache_web(db, clave)
    if entry:
        entry.respuesta = respuesta
        entry.resultados_json = resultados_json
        entry.consulta_original = consulta_original
        entry.veces_consultada = (entry.veces_consultada or 1) + 1
    else:
        entry = AsistenteBusquedaWebCache(
            consulta_clave=clave,
            consulta_original=consulta_original,
            respuesta=respuesta,
            resultados_json=resultados_json,
            veces_consultada=1,
        )
        db.add(entry)
    db.commit()
    return entry


def increment_cache_web(db: Session, entry: AsistenteBusquedaWebCache) -> None:
    entry.veces_consultada = (entry.veces_consultada or 1) + 1
    db.commit()


# ── Encomiendas (consultas que necesita el asistente) ─────────────────────────

def ultimas_encomiendas_por_dni(db: Session, dni: str, *, limite: int = 5) -> list[Shipment]:
    return (
        db.query(Shipment)
        .filter(
            (Shipment.sender_document_number == dni)
            | (Shipment.recipient_document_number == dni)
        )
        .order_by(Shipment.created_at.desc(), Shipment.id.desc())
        .limit(limite)
        .all()
    )
