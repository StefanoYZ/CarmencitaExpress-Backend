from datetime import date

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.measurement_logs.schema import (
    FinalizarPaqueteCargaRequest,
    IniciarOrdenCargaRequest,
    LogBoletaFinishRequest,
    LogBoletaReportResponse,
    LogBoletaResponse,
    LogBoletaStartRequest,
    LogCargaPaqueteReportResponse,
    LogCargaPaqueteResponse,
    LogServicioFinishRequest,
    LogServicioReportResponse,
    LogServicioResponse,
    LogServicioStartRequest,
    OrdenCargaStatusResponse,
)
from app.modules.measurement_logs.service import (
    finish_boleta_log,
    finish_service_phase,
    finalizar_paquete_carga,
    get_orden_carga_status,
    iniciar_orden_carga,
    list_boleta_logs,
    list_carga_logs,
    list_service_logs,
    resolve_user_from_authorization,
    start_boleta_log,
    start_service_phase,
    username_from_user,
)


boletas_router = APIRouter(prefix="/logs/boletas", tags=["measurement logs"])
servicio_router = APIRouter(prefix="/logs/servicio-transporte", tags=["measurement logs"])
carga_router = APIRouter(prefix="/logs/carga", tags=["measurement logs"])


@boletas_router.post("/iniciar", response_model=LogBoletaResponse, status_code=status.HTTP_201_CREATED)
def start_boleta_log_endpoint(
    payload: LogBoletaStartRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogBoletaResponse:
    current_user = resolve_user_from_authorization(db, authorization)
    return start_boleta_log(
        db,
        encomienda_id=payload.encomienda_id,
        boleta_id=payload.boleta_id,
        pago_id=payload.pago_id,
        usuario=username_from_user(current_user, payload.usuario_correo),
        actor_origen=payload.actor_origen,
        canal=payload.canal,
        timestamp_inicio=payload.timestamp,
    )


@boletas_router.post("/{log_id}/finalizar", response_model=LogBoletaResponse)
def finish_boleta_log_endpoint(
    log_id: int,
    payload: LogBoletaFinishRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> LogBoletaResponse:
    try:
        return finish_boleta_log(db, log_id, timestamp_fin=payload.timestamp_fin if payload else None)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@boletas_router.get("", response_model=list[LogBoletaResponse])
def list_boleta_logs_endpoint(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    usuario: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogBoletaResponse]:
    return list_boleta_logs(db, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, usuario=usuario)


@boletas_router.get("/reporte", response_model=list[LogBoletaReportResponse])
def report_boleta_logs_endpoint(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    usuario: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogBoletaReportResponse]:
    return list_boleta_logs(db, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, usuario=usuario)


@servicio_router.post("/registro/iniciar", response_model=LogServicioResponse, status_code=status.HTTP_201_CREATED)
def start_registration_log_endpoint(
    payload: LogServicioStartRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _start_service_phase_endpoint(db, "registro", payload, authorization)


@servicio_router.post("/registro/finalizar", response_model=LogServicioResponse)
def finish_registration_log_by_identity_endpoint(
    payload: LogServicioFinishRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _finish_service_phase_endpoint(db, "registro", payload, authorization=authorization)


@servicio_router.post("/{log_id}/registro/finalizar", response_model=LogServicioResponse)
def finish_registration_log_endpoint(
    log_id: int,
    payload: LogServicioFinishRequest | None = Body(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _finish_service_phase_endpoint(db, "registro", payload, log_id=log_id, authorization=authorization)


@servicio_router.post("/carga/iniciar", response_model=LogServicioResponse, status_code=status.HTTP_201_CREATED)
def start_loading_log_endpoint(
    payload: LogServicioStartRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _start_service_phase_endpoint(db, "carga", payload, authorization)


@servicio_router.post("/carga/finalizar", response_model=LogServicioResponse)
def finish_loading_log_by_identity_endpoint(
    payload: LogServicioFinishRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _finish_service_phase_endpoint(db, "carga", payload, authorization=authorization)


@servicio_router.post("/{log_id}/carga/finalizar", response_model=LogServicioResponse)
def finish_loading_log_endpoint(
    log_id: int,
    payload: LogServicioFinishRequest | None = Body(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _finish_service_phase_endpoint(db, "carga", payload, log_id=log_id, authorization=authorization)


@servicio_router.post("/entrega/iniciar", response_model=LogServicioResponse, status_code=status.HTTP_201_CREATED)
def start_delivery_log_endpoint(
    payload: LogServicioStartRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _start_service_phase_endpoint(db, "entrega", payload, authorization)


@servicio_router.post("/entrega/finalizar", response_model=LogServicioResponse)
def finish_delivery_log_by_identity_endpoint(
    payload: LogServicioFinishRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _finish_service_phase_endpoint(db, "entrega", payload, authorization=authorization)


@servicio_router.post("/{log_id}/entrega/finalizar", response_model=LogServicioResponse)
def finish_delivery_log_endpoint(
    log_id: int,
    payload: LogServicioFinishRequest | None = Body(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> LogServicioResponse:
    return _finish_service_phase_endpoint(db, "entrega", payload, log_id=log_id, authorization=authorization)


@servicio_router.get("", response_model=list[LogServicioResponse])
def list_service_logs_endpoint(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    metodo: str | None = Query(default=None),
    usuario: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogServicioResponse]:
    return list_service_logs(db, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, metodo=metodo, usuario=usuario)


@servicio_router.get("/reporte", response_model=list[LogServicioReportResponse])
def report_service_logs_endpoint(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    metodo: str | None = Query(default=None),
    usuario: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogServicioReportResponse]:
    return list_service_logs(db, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, metodo=metodo, usuario=usuario)


def _start_service_phase_endpoint(
    db: Session,
    phase: str,
    payload: LogServicioStartRequest,
    authorization: str | None,
) -> LogServicioResponse:
    current_user = resolve_user_from_authorization(db, authorization)
    return start_service_phase(
        db,
        phase,
        encomienda_id=payload.encomienda_id,
        cotizacion_id=payload.cotizacion_id,
        pago_id=payload.pago_id,
        despacho_id=payload.despacho_id,
        usuario_id=current_user.id if current_user else payload.usuario_id,
        usuario_correo=username_from_user(current_user, payload.usuario_correo),
        timestamp_inicio=payload.timestamp,
    )


def _finish_service_phase_endpoint(
    db: Session,
    phase: str,
    payload: LogServicioFinishRequest | None,
    *,
    log_id: int | None = None,
    authorization: str | None,
) -> LogServicioResponse:
    current_user = resolve_user_from_authorization(db, authorization)
    try:
        return finish_service_phase(
            db,
            phase,
            log_id=log_id,
            encomienda_id=payload.encomienda_id if payload else None,
            cotizacion_id=payload.cotizacion_id if payload else None,
            pago_id=payload.pago_id if payload else None,
            despacho_id=payload.despacho_id if payload else None,
            usuario_id=current_user.id if current_user else payload.usuario_id if payload else None,
            usuario_correo=username_from_user(current_user, payload.usuario_correo if payload else None),
            timestamp_fin=payload.timestamp_fin if payload else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ── Carga por paquete ─────────────────────────────────────────────────────────

@carga_router.post(
    "/iniciar-orden",
    response_model=list[LogCargaPaqueteResponse],
    status_code=status.HTTP_201_CREATED,
)
def iniciar_orden_endpoint(
    payload: IniciarOrdenCargaRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> list[LogCargaPaqueteResponse]:
    current_user = resolve_user_from_authorization(db, authorization)
    try:
        return iniciar_orden_carga(
            db,
            encomienda_ids=payload.encomienda_ids,
            orden_carga_id=payload.orden_carga_id,
            usuario_correo=username_from_user(current_user, payload.usuario_correo),
            actor_origen=payload.actor_origen,
            canal=payload.canal,
            modo_prueba=payload.modo_prueba,
            timestamp_inicio=payload.timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@carga_router.post(
    "/{orden_carga_id}/paquete/{encomienda_id}/finalizar",
    response_model=LogCargaPaqueteResponse,
)
def finalizar_paquete_endpoint(
    orden_carga_id: str,
    encomienda_id: int,
    payload: FinalizarPaqueteCargaRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> LogCargaPaqueteResponse:
    try:
        log, _ = finalizar_paquete_carga(
            db,
            orden_carga_id,
            encomienda_id,
            timestamp_fin=payload.timestamp_fin if payload else None,
            accion_fin=payload.accion_fin if payload else "siguiente_simulado",
        )
        return log
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@carga_router.post(
    "/{orden_carga_id}/siguiente-simulado",
    response_model=LogCargaPaqueteResponse,
)
def siguiente_simulado_endpoint(
    orden_carga_id: str,
    encomienda_id: int = Query(..., description="ID de la encomienda actual a finalizar"),
    db: Session = Depends(get_db),
) -> LogCargaPaqueteResponse:
    """Finaliza el paquete actual en modo simulación (equivale a escanear QR)."""
    try:
        log, _ = finalizar_paquete_carga(
            db,
            orden_carga_id,
            encomienda_id,
            accion_fin="siguiente_simulado",
        )
        return log
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@carga_router.get("/reporte", response_model=list[LogCargaPaqueteReportResponse])
def reporte_carga_endpoint(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    orden_carga_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[LogCargaPaqueteReportResponse]:
    return list_carga_logs(db, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, orden_carga_id=orden_carga_id)


@carga_router.get("/{orden_carga_id}", response_model=OrdenCargaStatusResponse)
def get_orden_status_endpoint(
    orden_carga_id: str,
    db: Session = Depends(get_db),
) -> OrdenCargaStatusResponse:
    try:
        return get_orden_carga_status(db, orden_carga_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
