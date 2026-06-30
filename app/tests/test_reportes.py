"""Pruebas unitarias de reportes y logs del asistente / mediciones.

Cubren: creación de logs con/sin error, flags de prevención/corrección, filtros
(etapa, existe_error), resumen del reporte (totales y % de prevención) y filtros
por fecha en los logs de boleta y carga.
"""
from datetime import timedelta

from app.core.business_time import business_now, business_today
from app.modules.asistente import service as asistente_service
from app.modules.asistente.schema import LogAsistenteCreate
from app.modules.measurement_logs.service import (
    iniciar_orden_carga,
    list_boleta_logs,
    list_carga_logs,
    start_boleta_log,
)


def _log(**kw) -> LogAsistenteCreate:
    base = dict(etapa="chat", tipo_interaccion="consulta", descripcion_interaccion="qa", canal="externo")
    base.update(kw)
    return LogAsistenteCreate(**base)


def test_crea_log_sin_error(db_session):
    log = asistente_service.create_log(db_session, _log(existe_error=False))
    assert log.id is not None
    assert log.existe_error is False


def test_crea_log_con_error_y_prevencion(db_session):
    log = asistente_service.create_log(
        db_session,
        _log(existe_error=True, ayudo_corregir_prevenir_error=True, tipo_error="dni_invalido"),
    )
    assert log.existe_error is True
    assert log.ayudo_corregir_prevenir_error is True
    assert log.tipo_error == "dni_invalido"


def test_filtra_logs_por_existe_error(db_session):
    asistente_service.create_log(db_session, _log(existe_error=False))
    asistente_service.create_log(db_session, _log(existe_error=True, tipo_error="peso_invalido"))
    con_error = asistente_service.list_logs(db_session, existe_error=True)
    assert con_error and all(l.existe_error for l in con_error)


def test_filtra_logs_por_etapa(db_session):
    asistente_service.create_log(db_session, _log(etapa="validacion_coherencia", existe_error=True))
    asistente_service.create_log(db_session, _log(etapa="chat"))
    coherencia = asistente_service.list_logs(db_session, etapa="validacion_coherencia")
    assert coherencia and all(l.etapa == "validacion_coherencia" for l in coherencia)


def test_resumen_reporte_calcula_totales_y_porcentaje(db_session):
    # 2 errores, 1 prevenido => 50% de prevención.
    asistente_service.create_log(db_session, _log(existe_error=False))
    asistente_service.create_log(db_session, _log(existe_error=True, ayudo_corregir_prevenir_error=True, tipo_error="dni"))
    asistente_service.create_log(db_session, _log(existe_error=True, ayudo_corregir_prevenir_error=False, tipo_error="peso"))

    resumen = asistente_service.get_report_summary(db_session)
    assert resumen["total_interacciones"] == 3
    assert resumen["total_errores"] == 2
    assert resumen["total_errores_prevenidos"] == 1
    assert resumen["porcentaje_prevencion"] == 50.0
    assert resumen["errores_por_tipo"] == {"dni": 1, "peso": 1}


def test_filtro_por_fecha_en_logs_de_boleta(db_session):
    hoy = business_today()
    start_boleta_log(db_session, pago_id=7001, timestamp_inicio=business_now() - timedelta(days=3))
    start_boleta_log(db_session, pago_id=7002, timestamp_inicio=business_now())
    recientes = list_boleta_logs(db_session, fecha_inicio=hoy)
    pagos = {l.pago_id for l in recientes}
    assert 7002 in pagos
    assert 7001 not in pagos


def test_filtro_por_orden_en_logs_de_carga(db_session):
    logs = iniciar_orden_carga(db_session, encomienda_ids=[401, 402])
    orden = logs[0].orden_carga_id
    de_la_orden = list_carga_logs(db_session, orden_carga_id=orden)
    assert len(de_la_orden) == 2
    assert all(l.orden_carga_id == orden for l in de_la_orden)
