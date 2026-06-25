"""Lógica de negocio del Asistente Virtual Inteligente."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.business_time import business_now
from app.modules.asistente.model import (
    AsistenteBaseConocimiento,
    LogInteraccionAsistente,
    SolicitudRecojoExterno,
    TiposContenidoTransporte,
)
from app.modules.asistente.schema import (
    BaseConocimientoCreate,
    ChatRequest,
    ChatResponse,
    LogAsistenteCreate,
    SolicitudRecojoCreate,
    TipoContenidoCreate,
)
from app.services import asistente_llm_service


# ── Chat ──────────────────────────────────────────────────────────────────────

def process_chat(db: Session, request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or uuid.uuid4().hex
    intencion = asistente_llm_service.detectar_intencion(request.mensaje, request.contexto_actual)

    datos_sistema = _build_system_context(db, intencion)
    respuesta = asistente_llm_service.generar_respuesta_controlada(
        request.mensaje,
        contexto=request.contexto_actual,
        datos_sistema=datos_sistema,
    )

    datos_extraidos: dict | None = None
    requiere_accion = False
    accion_sugerida: str | None = None

    if intencion == "recojo_externo":
        datos_extraidos = asistente_llm_service.extraer_datos_recojo_externo(request.mensaje)
        if datos_extraidos:
            requiere_accion = True
            accion_sugerida = "crear_solicitud_recojo_externo"
    elif intencion == "pre_registro":
        datos_extraidos = asistente_llm_service.extraer_datos_preregistro(request.mensaje)
        if datos_extraidos:
            requiere_accion = True
            accion_sugerida = "iniciar_preregistro"

    log = _save_log(
        db,
        etapa=intencion,
        tipo_interaccion=_map_intencion_to_tipo(intencion),
        descripcion_interaccion=f"Mensaje: {request.mensaje[:500]}",
        session_id=session_id,
        cliente_id=request.cliente_id,
        usuario_correo=request.usuario_correo,
        canal=request.canal,
        existe_error=False,
        ayudo_corregir_prevenir_error=False,
    )

    return ChatResponse(
        session_id=session_id,
        respuesta=respuesta,
        intencion_detectada=intencion,
        requiere_accion=requiere_accion,
        accion_sugerida=accion_sugerida,
        datos_extraidos=datos_extraidos,
        log_id=log.id,
    )


# ── Logs ──────────────────────────────────────────────────────────────────────

def create_log(db: Session, payload: LogAsistenteCreate) -> LogInteraccionAsistente:
    log = LogInteraccionAsistente(
        metodo=payload.metodo or "Sistema",
        etapa=payload.etapa,
        tipo_interaccion=payload.tipo_interaccion,
        descripcion_interaccion=payload.descripcion_interaccion,
        existe_error=payload.existe_error,
        ayudo_corregir_prevenir_error=payload.ayudo_corregir_prevenir_error,
        tipo_error=payload.tipo_error,
        accion_correctiva_aplicada=payload.accion_correctiva_aplicada,
        session_id=payload.session_id,
        cliente_id=payload.cliente_id,
        usuario_correo=payload.usuario_correo,
        actor_origen=payload.actor_origen,
        canal=payload.canal,
        pre_registro_id=payload.pre_registro_id,
        encomienda_id=payload.encomienda_id,
        solicitud_recojo_externo_id=payload.solicitud_recojo_externo_id,
        campo_afectado=payload.campo_afectado,
        valor_ingresado=payload.valor_ingresado,
        valor_corregido=payload.valor_corregido,
        resultado=payload.resultado,
        fecha=business_now(),
        timestamp=business_now(),
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


def get_report_summary(db: Session) -> dict:
    logs = db.query(LogInteraccionAsistente).all()
    total = len(logs)
    errores = [log for log in logs if log.existe_error]
    prevenidos = [log for log in errores if log.ayudo_corregir_prevenir_error]
    errores_por_tipo: dict[str, int] = {}
    errores_por_etapa: dict[str, int] = {}
    errores_por_canal: dict[str, int] = {}
    for log in errores:
        if log.tipo_error:
            errores_por_tipo[log.tipo_error] = errores_por_tipo.get(log.tipo_error, 0) + 1
        if log.etapa:
            errores_por_etapa[log.etapa] = errores_por_etapa.get(log.etapa, 0) + 1
        if log.canal:
            errores_por_canal[log.canal] = errores_por_canal.get(log.canal, 0) + 1

    return {
        "total_interacciones": total,
        "total_errores": len(errores),
        "total_errores_prevenidos": len(prevenidos),
        "total_errores_corregidos": len(prevenidos),
        "porcentaje_prevencion": round(len(prevenidos) / len(errores) * 100, 1) if errores else 0.0,
        "errores_por_tipo": errores_por_tipo,
        "errores_por_etapa": errores_por_etapa,
        "errores_por_canal": errores_por_canal,
    }


# ── Recojo Externo ────────────────────────────────────────────────────────────

def create_solicitud_recojo(db: Session, payload: SolicitudRecojoCreate) -> SolicitudRecojoExterno:
    codigo = f"RE-{uuid.uuid4().hex[:8].upper()}"
    solicitud = SolicitudRecojoExterno(
        codigo_solicitud=codigo,
        cliente_id=payload.cliente_id,
        usuario_correo=payload.usuario_correo,
        ciudad_origen=payload.ciudad_origen,
        empresa_transporte_origen=payload.empresa_transporte_origen,
        agencia_o_direccion_llegada=payload.agencia_o_direccion_llegada,
        codigo_guia_o_tracking=payload.codigo_guia_o_tracking,
        hora_aproximada_llegada=payload.hora_aproximada_llegada,
        destino_final=payload.destino_final,
        nombre_destinatario_final=payload.nombre_destinatario_final,
        telefono_destinatario=payload.telefono_destinatario,
        tipo_contenido=payload.tipo_contenido,
        observaciones=payload.observaciones,
        estado="pendiente",
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)

    _save_log(
        db,
        etapa="recojo_externo",
        tipo_interaccion="recojo_externo",
        descripcion_interaccion=f"Solicitud de recojo externo creada: {codigo}",
        usuario_correo=payload.usuario_correo,
        canal="externo",
        solicitud_recojo_externo_id=solicitud.id,
        accion_correctiva_aplicada="Solicitud registrada y derivada a secretaria para revisión.",
    )
    return solicitud


def list_solicitudes_recojo(
    db: Session,
    *,
    estado: str | None = None,
) -> list[SolicitudRecojoExterno]:
    query = db.query(SolicitudRecojoExterno)
    if estado:
        query = query.filter(SolicitudRecojoExterno.estado == estado)
    return query.order_by(SolicitudRecojoExterno.id.desc()).all()


def get_solicitud_recojo(db: Session, solicitud_id: int) -> SolicitudRecojoExterno | None:
    return db.query(SolicitudRecojoExterno).filter(SolicitudRecojoExterno.id == solicitud_id).first()


def update_solicitud_estado(db: Session, solicitud_id: int, estado: str) -> SolicitudRecojoExterno:
    solicitud = get_solicitud_recojo(db, solicitud_id)
    if solicitud is None:
        raise LookupError("Solicitud de recojo externo no encontrada")
    estados_validos = {"pendiente", "revisado", "confirmado", "rechazado", "convertido_a_preregistro"}
    if estado not in estados_validos:
        raise ValueError(f"Estado inválido. Opciones: {', '.join(estados_validos)}")
    solicitud.estado = estado
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud


# ── Base de Conocimiento ──────────────────────────────────────────────────────

def create_base_conocimiento(db: Session, payload: BaseConocimientoCreate) -> AsistenteBaseConocimiento:
    entry = AsistenteBaseConocimiento(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_base_conocimiento(db: Session, *, categoria: str | None = None, activo: bool | None = None) -> list[AsistenteBaseConocimiento]:
    query = db.query(AsistenteBaseConocimiento)
    if categoria:
        query = query.filter(AsistenteBaseConocimiento.categoria == categoria)
    if activo is not None:
        query = query.filter(AsistenteBaseConocimiento.activo == activo)
    return query.order_by(AsistenteBaseConocimiento.id.asc()).all()


# ── Tipos de Contenido ────────────────────────────────────────────────────────

def create_tipo_contenido(db: Session, payload: TipoContenidoCreate) -> TiposContenidoTransporte:
    entry = TiposContenidoTransporte(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_tipos_contenido(db: Session, *, activo: bool | None = None) -> list[TiposContenidoTransporte]:
    query = db.query(TiposContenidoTransporte)
    if activo is not None:
        query = query.filter(TiposContenidoTransporte.activo == activo)
    return query.order_by(TiposContenidoTransporte.nombre.asc()).all()


# ── Helpers privados ──────────────────────────────────────────────────────────

def _save_log(
    db: Session,
    *,
    etapa: str | None = None,
    tipo_interaccion: str | None = None,
    descripcion_interaccion: str | None = None,
    session_id: str | None = None,
    cliente_id: int | None = None,
    usuario_correo: str | None = None,
    actor_origen: str | None = None,
    canal: str | None = None,
    solicitud_recojo_externo_id: int | None = None,
    encomienda_id: int | None = None,
    existe_error: bool = False,
    ayudo_corregir_prevenir_error: bool = False,
    tipo_error: str | None = None,
    accion_correctiva_aplicada: str | None = None,
) -> LogInteraccionAsistente:
    log = LogInteraccionAsistente(
        metodo="Sistema",
        etapa=etapa,
        tipo_interaccion=tipo_interaccion,
        descripcion_interaccion=descripcion_interaccion,
        existe_error=existe_error,
        ayudo_corregir_prevenir_error=ayudo_corregir_prevenir_error,
        tipo_error=tipo_error,
        accion_correctiva_aplicada=accion_correctiva_aplicada,
        session_id=session_id,
        cliente_id=cliente_id,
        usuario_correo=usuario_correo,
        actor_origen=actor_origen,
        canal=canal,
        solicitud_recojo_externo_id=solicitud_recojo_externo_id,
        encomienda_id=encomienda_id,
        fecha=business_now(),
        timestamp=business_now(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _map_intencion_to_tipo(intencion: str) -> str:
    mapping = {
        "cotizacion": "cotizacion",
        "tracking": "tracking",
        "horarios": "consulta_informativa",
        "sedes": "consulta_informativa",
        "recojo_externo": "recojo_externo",
        "pre_registro": "pre_registro_guiado",
        "contenido_permitido": "consulta_informativa",
        "documentacion": "consulta_informativa",
        "consulta_general": "consulta_informativa",
    }
    return mapping.get(intencion, "consulta_informativa")
