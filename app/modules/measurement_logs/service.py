from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.business_time import business_now, business_today
from app.core.security import decode_access_token
from app.modules.measurement_logs.model import LogCargaPaquete, LogEmisionBoleta, LogServicioTransporte
from app.modules.users import repository as users_repository
from app.modules.users.model import InternalUser


Phase = Literal["registro", "carga", "entrega"]
METODO_SISTEMA = "sistema"


def resolve_user_from_authorization(db: Session, authorization: str | None) -> InternalUser | None:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        payload = decode_access_token(parts[1])
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    return users_repository.get_user_by_id(db, user_id)


def username_from_user(current_user: InternalUser | None, fallback: str | None = None) -> str | None:
    if current_user is not None:
        return current_user.username
    # TODO: reemplazar usuario_correo temporal por correo/username obtenido desde el token.
    return fallback


def start_boleta_log(
    db: Session,
    *,
    encomienda_id: int | None = None,
    boleta_id: int | None = None,
    pago_id: int | None = None,
    usuario: str | None = None,
    actor_origen: str | None = None,
    canal: str | None = None,
    timestamp_inicio: datetime | None = None,
    commit: bool = True,
) -> LogEmisionBoleta:
    log = _find_open_boleta_log(
        db,
        encomienda_id=encomienda_id,
        boleta_id=boleta_id,
        pago_id=pago_id,
    )
    if log is not None:
        _fill_boleta_identity(
            log,
            encomienda_id=encomienda_id,
            boleta_id=boleta_id,
            pago_id=pago_id,
            usuario=usuario,
            actor_origen=actor_origen,
            canal=canal,
        )
        if commit:
            db.add(log)
            db.commit()
            db.refresh(log)
        return log

    log = LogEmisionBoleta(
        numero_observacion=None,
        usuario=usuario,
        metodo=METODO_SISTEMA,
        actor_origen=actor_origen,
        canal=canal,
        timestamp_inicio=timestamp_inicio or business_now(),
        encomienda_id=encomienda_id,
        boleta_id=boleta_id,
        pago_id=pago_id,
    )
    db.add(log)
    db.flush()
    if log.numero_observacion is None:
        log.numero_observacion = log.id
    if commit:
        db.commit()
        db.refresh(log)
    return log


def finish_boleta_log(
    db: Session,
    log_id: int,
    *,
    timestamp_fin: datetime | None = None,
    commit: bool = True,
) -> LogEmisionBoleta:
    log = db.query(LogEmisionBoleta).filter(LogEmisionBoleta.id == log_id).first()
    if log is None:
        raise LookupError("Log de emision de boleta no encontrado")
    _finish_boleta_log(log, timestamp_fin or business_now())
    if commit:
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def finish_open_boleta_log_by_shipment(
    db: Session,
    *,
    encomienda_id: int,
    boleta_id: int | None = None,
    timestamp_fin: datetime | None = None,
    commit: bool = True,
) -> LogEmisionBoleta | None:
    log = _find_open_boleta_log(db, encomienda_id=encomienda_id, boleta_id=boleta_id)
    if log is None:
        return None
    if boleta_id is not None and log.boleta_id is None:
        log.boleta_id = boleta_id
    _finish_boleta_log(log, timestamp_fin or business_now())
    if commit:
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def link_boleta_log_to_receipt(
    db: Session,
    *,
    encomienda_id: int,
    boleta_id: int,
    commit: bool = True,
) -> LogEmisionBoleta | None:
    log = _find_open_boleta_log(db, encomienda_id=encomienda_id, boleta_id=boleta_id)
    if log is None:
        return None
    if log.boleta_id is None:
        log.boleta_id = boleta_id
    if commit:
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def list_boleta_logs(
    db: Session,
    *,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    usuario: str | None = None,
) -> list[LogEmisionBoleta]:
    query = db.query(LogEmisionBoleta)
    if fecha_inicio is not None:
        query = query.filter(LogEmisionBoleta.timestamp_inicio >= datetime.combine(fecha_inicio, datetime.min.time()))
    if fecha_fin is not None:
        query = query.filter(LogEmisionBoleta.timestamp_inicio <= datetime.combine(fecha_fin, datetime.max.time()))
    if usuario:
        query = query.filter(LogEmisionBoleta.usuario.ilike(f"%{usuario.strip()}%"))
    return query.order_by(LogEmisionBoleta.numero_observacion.desc()).all()


def start_service_phase(
    db: Session,
    phase: Phase,
    *,
    encomienda_id: int | None = None,
    cotizacion_id: int | None = None,
    pago_id: int | None = None,
    despacho_id: int | None = None,
    usuario_id: int | None = None,
    usuario_correo: str | None = None,
    timestamp_inicio: datetime | None = None,
    commit: bool = True,
) -> LogServicioTransporte:
    log = _find_service_log(
        db,
        encomienda_id=encomienda_id,
        cotizacion_id=cotizacion_id,
        pago_id=pago_id,
        only_open=False,
    )
    if log is None:
        now = timestamp_inicio or business_now()
        log = LogServicioTransporte(
            numero_observacion=None,
            fecha=now.date(),
            metodo=METODO_SISTEMA,
            encomienda_id=encomienda_id,
            cotizacion_id=cotizacion_id,
            pago_id=pago_id,
            despacho_id=despacho_id,
            usuario_id=usuario_id,
            usuario_correo=usuario_correo,
        )
        db.add(log)
        db.flush()
        if log.numero_observacion is None:
            log.numero_observacion = log.id

    _fill_service_identity(
        log,
        encomienda_id=encomienda_id,
        cotizacion_id=cotizacion_id,
        pago_id=pago_id,
        despacho_id=despacho_id,
        usuario_id=usuario_id,
        usuario_correo=usuario_correo,
    )
    start_field = _phase_start_field(phase)
    if getattr(log, start_field) is None:
        started_at = timestamp_inicio or business_now()
        setattr(log, start_field, started_at)
        if log.fecha is None:
            log.fecha = started_at.date()
    log.metodo = METODO_SISTEMA
    if commit:
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def finish_service_phase(
    db: Session,
    phase: Phase,
    *,
    log_id: int | None = None,
    encomienda_id: int | None = None,
    cotizacion_id: int | None = None,
    pago_id: int | None = None,
    despacho_id: int | None = None,
    usuario_id: int | None = None,
    usuario_correo: str | None = None,
    timestamp_fin: datetime | None = None,
    commit: bool = True,
) -> LogServicioTransporte:
    log = _get_service_log(db, log_id=log_id, encomienda_id=encomienda_id, cotizacion_id=cotizacion_id, pago_id=pago_id)
    _fill_service_identity(
        log,
        encomienda_id=encomienda_id,
        cotizacion_id=cotizacion_id,
        pago_id=pago_id,
        despacho_id=despacho_id,
        usuario_id=usuario_id,
        usuario_correo=usuario_correo,
    )
    _finish_service_phase(log, phase, timestamp_fin or business_now())
    if commit:
        db.add(log)
        db.commit()
        db.refresh(log)
    return log


def ensure_boleta_log_after_payment(
    db: Session,
    *,
    encomienda_id: int,
    pago_id: int | None = None,
    usuario: str | None = None,
    commit: bool = True,
) -> LogEmisionBoleta:
    return start_boleta_log(
        db,
        encomienda_id=encomienda_id,
        pago_id=pago_id,
        usuario=usuario,
        commit=commit,
    )


def list_service_logs(
    db: Session,
    *,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    metodo: str | None = None,
    usuario: str | None = None,
) -> list[LogServicioTransporte]:
    query = db.query(LogServicioTransporte)
    if fecha_inicio is not None:
        query = query.filter(LogServicioTransporte.fecha >= fecha_inicio)
    if fecha_fin is not None:
        query = query.filter(LogServicioTransporte.fecha <= fecha_fin)
    if metodo:
        query = query.filter(LogServicioTransporte.metodo == METODO_SISTEMA)
    if usuario:
        query = query.filter(LogServicioTransporte.usuario_correo.ilike(f"%{usuario.strip()}%"))
    return query.order_by(LogServicioTransporte.numero_observacion.desc()).all()


def _finish_boleta_log(log: LogEmisionBoleta, timestamp_fin: datetime) -> None:
    if log.timestamp_fin is not None:
        return
    if timestamp_fin < log.timestamp_inicio:
        raise ValueError("timestamp_fin no puede ser menor que timestamp_inicio")
    log.timestamp_fin = timestamp_fin
    log.tiempo_ms = _duration_ms(log.timestamp_inicio, timestamp_fin)
    log.metodo = METODO_SISTEMA


def _finish_service_phase(log: LogServicioTransporte, phase: Phase, timestamp_fin: datetime) -> None:
    start_field = _phase_start_field(phase)
    end_field = _phase_end_field(phase)
    duration_field = _phase_duration_field(phase)
    start_value = getattr(log, start_field)
    if start_value is None:
        raise ValueError(f"No se puede finalizar {phase} sin timestamp de inicio")
    current_end = getattr(log, end_field)
    if current_end is not None:
        return
    if timestamp_fin < start_value:
        raise ValueError(f"timestamp_fin_{phase} no puede ser menor que timestamp_inicio_{phase}")
    setattr(log, end_field, timestamp_fin)
    setattr(log, duration_field, _duration_ms(start_value, timestamp_fin))
    log.tiempo_total_ms = _total_service_ms(log)
    log.metodo = METODO_SISTEMA


def _duration_ms(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() * 1000)


def _total_service_ms(log: LogServicioTransporte) -> int | None:
    values = [
        log.tiempo_registro_ms,
        log.tiempo_carga_ms,
        log.tiempo_entrega_ms,
    ]
    completed = [value for value in values if value is not None]
    if not completed:
        return None
    return sum(completed)


def _find_open_boleta_log(
    db: Session,
    *,
    encomienda_id: int | None = None,
    boleta_id: int | None = None,
    pago_id: int | None = None,
) -> LogEmisionBoleta | None:
    clauses = _identity_clauses(
        LogEmisionBoleta,
        encomienda_id=encomienda_id,
        boleta_id=boleta_id,
        pago_id=pago_id,
    )
    if not clauses:
        return None
    return (
        db.query(LogEmisionBoleta)
        .filter(LogEmisionBoleta.timestamp_fin.is_(None))
        .filter(or_(*clauses))
        .order_by(LogEmisionBoleta.id.desc())
        .first()
    )


def _find_service_log(
    db: Session,
    *,
    encomienda_id: int | None = None,
    cotizacion_id: int | None = None,
    pago_id: int | None = None,
    only_open: bool,
) -> LogServicioTransporte | None:
    clauses = _identity_clauses(
        LogServicioTransporte,
        encomienda_id=encomienda_id,
        cotizacion_id=cotizacion_id,
        pago_id=pago_id,
    )
    if not clauses:
        return None
    query = db.query(LogServicioTransporte).filter(or_(*clauses))
    if only_open:
        query = query.filter(
            or_(
                LogServicioTransporte.timestamp_fin_registro.is_(None),
                LogServicioTransporte.timestamp_fin_carga.is_(None),
                LogServicioTransporte.timestamp_fin_entrega.is_(None),
            )
        )
    return query.order_by(LogServicioTransporte.id.desc()).first()


def _get_service_log(
    db: Session,
    *,
    log_id: int | None,
    encomienda_id: int | None,
    cotizacion_id: int | None,
    pago_id: int | None,
) -> LogServicioTransporte:
    if log_id is not None:
        log = db.query(LogServicioTransporte).filter(LogServicioTransporte.id == log_id).first()
    else:
        log = _find_service_log(
            db,
            encomienda_id=encomienda_id,
            cotizacion_id=cotizacion_id,
            pago_id=pago_id,
            only_open=False,
        )
    if log is None:
        raise LookupError("Log de servicio de transporte no encontrado")
    return log


def _identity_clauses(model, **identifiers):
    return [
        getattr(model, field) == value
        for field, value in identifiers.items()
        if value is not None and hasattr(model, field)
    ]


def _fill_boleta_identity(
    log: LogEmisionBoleta,
    *,
    encomienda_id: int | None,
    boleta_id: int | None,
    pago_id: int | None,
    usuario: str | None,
    actor_origen: str | None = None,
    canal: str | None = None,
) -> None:
    if encomienda_id is not None and log.encomienda_id is None:
        log.encomienda_id = encomienda_id
    if boleta_id is not None and log.boleta_id is None:
        log.boleta_id = boleta_id
    if pago_id is not None and log.pago_id is None:
        log.pago_id = pago_id
    if usuario and not log.usuario:
        log.usuario = usuario
    if actor_origen and not log.actor_origen:
        log.actor_origen = actor_origen
    if canal and not log.canal:
        log.canal = canal
    log.metodo = METODO_SISTEMA


def _fill_service_identity(
    log: LogServicioTransporte,
    *,
    encomienda_id: int | None,
    cotizacion_id: int | None,
    pago_id: int | None,
    despacho_id: int | None,
    usuario_id: int | None,
    usuario_correo: str | None,
) -> None:
    if encomienda_id is not None and log.encomienda_id is None:
        log.encomienda_id = encomienda_id
    if cotizacion_id is not None and log.cotizacion_id is None:
        log.cotizacion_id = cotizacion_id
    if pago_id is not None and log.pago_id is None:
        log.pago_id = pago_id
    if despacho_id is not None and log.despacho_id is None:
        log.despacho_id = despacho_id
    if usuario_id is not None and log.usuario_id is None:
        log.usuario_id = usuario_id
    if usuario_correo and not log.usuario_correo:
        log.usuario_correo = usuario_correo
    log.metodo = METODO_SISTEMA


def _phase_start_field(phase: Phase) -> str:
    return f"timestamp_inicio_{phase}"


def _phase_end_field(phase: Phase) -> str:
    return f"timestamp_fin_{phase}"


def _phase_duration_field(phase: Phase) -> str:
    return f"tiempo_{phase}_ms"


# ── LogCargaPaquete ───────────────────────────────────────────────────────────

def iniciar_orden_carga(
    db: Session,
    *,
    encomienda_ids: list[int],
    orden_carga_id: str | None = None,
    usuario_correo: str | None = None,
    actor_origen: str | None = "interno",
    canal: str | None = "interno",
    modo_prueba: bool = True,
    timestamp_inicio: datetime | None = None,
) -> list[LogCargaPaquete]:
    """Crea un log por cada paquete. El inicio del primero es ahora; los demás quedan pending."""
    if not encomienda_ids:
        raise ValueError("Se requiere al menos un encomienda_id")
    orden_id = orden_carga_id or f"OC-{uuid.uuid4().hex[:8].upper()}"
    now = timestamp_inicio or business_now()
    today = now.date()
    logs: list[LogCargaPaquete] = []
    for numero, enc_id in enumerate(encomienda_ids, start=1):
        log = LogCargaPaquete(
            fecha=today,
            metodo=METODO_SISTEMA,
            orden_carga_id=orden_id,
            encomienda_id=enc_id,
            numero_paquete=numero,
            timestamp_inicio=now,
            accion_inicio="ordenar" if numero == 1 else "fin_anterior",
            usuario_correo=usuario_correo,
            actor_origen=actor_origen,
            canal=canal,
            modo_prueba=modo_prueba,
        )
        db.add(log)
        db.flush()
        log.numero_observacion = log.id
        logs.append(log)
    db.commit()
    for log in logs:
        db.refresh(log)
    return logs


def finalizar_paquete_carga(
    db: Session,
    orden_carga_id: str,
    encomienda_id: int,
    *,
    timestamp_fin: datetime | None = None,
    accion_fin: str = "siguiente_simulado",
) -> tuple[LogCargaPaquete, LogCargaPaquete | None]:
    """Finaliza el log del paquete actual y actualiza el inicio del siguiente."""
    log = (
        db.query(LogCargaPaquete)
        .filter(
            LogCargaPaquete.orden_carga_id == orden_carga_id,
            LogCargaPaquete.encomienda_id == encomienda_id,
            LogCargaPaquete.timestamp_fin.is_(None),
        )
        .first()
    )
    if log is None:
        raise LookupError(f"Log abierto no encontrado para orden {orden_carga_id} paquete {encomienda_id}")

    fin = timestamp_fin or business_now()
    if fin < log.timestamp_inicio:
        raise ValueError("timestamp_fin no puede ser menor que timestamp_inicio")
    log.timestamp_fin = fin
    log.tiempo_carga_ms = _duration_ms(log.timestamp_inicio, fin)
    log.accion_fin = accion_fin
    db.add(log)

    # Actualizar inicio del siguiente paquete en la secuencia
    siguiente = (
        db.query(LogCargaPaquete)
        .filter(
            LogCargaPaquete.orden_carga_id == orden_carga_id,
            LogCargaPaquete.numero_paquete == log.numero_paquete + 1,
        )
        .first()
    )
    if siguiente is not None and siguiente.timestamp_fin is None:
        siguiente.timestamp_inicio = fin
        siguiente.accion_inicio = "fin_anterior"
        db.add(siguiente)

    db.commit()
    db.refresh(log)
    if siguiente:
        db.refresh(siguiente)
    return log, siguiente


def get_orden_carga_status(db: Session, orden_carga_id: str) -> dict:
    logs = (
        db.query(LogCargaPaquete)
        .filter(LogCargaPaquete.orden_carga_id == orden_carga_id)
        .order_by(LogCargaPaquete.numero_paquete.asc())
        .all()
    )
    if not logs:
        raise LookupError(f"Orden de carga {orden_carga_id} no encontrada")
    cargados = [log for log in logs if log.timestamp_fin is not None]
    tiempo_total = sum(log.tiempo_carga_ms for log in cargados if log.tiempo_carga_ms) or None
    return {
        "orden_carga_id": orden_carga_id,
        "total_paquetes": len(logs),
        "paquetes_cargados": len(cargados),
        "paquetes_pendientes": len(logs) - len(cargados),
        "tiempo_total_ms": tiempo_total,
        "logs": logs,
    }


def list_carga_logs(
    db: Session,
    *,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    orden_carga_id: str | None = None,
) -> list[LogCargaPaquete]:
    query = db.query(LogCargaPaquete)
    if fecha_inicio:
        query = query.filter(LogCargaPaquete.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(LogCargaPaquete.fecha <= fecha_fin)
    if orden_carga_id:
        query = query.filter(LogCargaPaquete.orden_carga_id == orden_carga_id)
    return query.order_by(LogCargaPaquete.id.desc()).all()
