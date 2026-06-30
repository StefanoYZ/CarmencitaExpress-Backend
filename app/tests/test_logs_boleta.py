"""Pruebas unitarias de los logs de emisión de boleta (logs_emision_boleta).

Cubren: inicio tras pago, fin con cálculo de tiempo_ms, no finalizar sin inicio,
no permitir timestamp_fin < timestamp_inicio, registro de actor_origen y evitar
duplicado de log abierto.
"""
from datetime import timedelta

import pytest

from app.core.business_time import business_now
from app.modules.measurement_logs.service import (
    finish_boleta_log,
    start_boleta_log,
)


def test_inicia_log_de_boleta_tras_pago(db_session):
    t0 = business_now()
    log = start_boleta_log(
        db_session,
        pago_id=5001,
        actor_origen="cliente_externo",
        canal="externo",
        usuario="cliente.qa",
        timestamp_inicio=t0,
    )
    assert log.id is not None
    assert log.numero_observacion is not None
    assert log.timestamp_fin is None
    assert log.tiempo_ms is None
    assert log.actor_origen == "cliente_externo"


def test_finaliza_log_y_calcula_tiempo_ms(db_session):
    t0 = business_now()
    log = start_boleta_log(db_session, pago_id=5002, timestamp_inicio=t0)
    finalizado = finish_boleta_log(db_session, log.id, timestamp_fin=t0 + timedelta(seconds=2))
    assert finalizado.timestamp_fin is not None
    assert finalizado.tiempo_ms == 2000


def test_no_finaliza_sin_inicio(db_session):
    with pytest.raises(LookupError):
        finish_boleta_log(db_session, 999999)


def test_no_permite_fin_menor_que_inicio(db_session):
    t0 = business_now()
    log = start_boleta_log(db_session, pago_id=5003, timestamp_inicio=t0)
    with pytest.raises(ValueError):
        finish_boleta_log(db_session, log.id, timestamp_fin=t0 - timedelta(seconds=5))


def test_registra_actor_origen_secretaria(db_session):
    log = start_boleta_log(db_session, pago_id=5004, actor_origen="secretaria", canal="interno")
    assert log.actor_origen == "secretaria"
    assert log.canal == "interno"


def test_evita_duplicado_de_log_abierto(db_session):
    primero = start_boleta_log(db_session, pago_id=5005, actor_origen="secretaria")
    segundo = start_boleta_log(db_session, pago_id=5005, actor_origen="secretaria")
    # No debe crear un segundo log abierto para el mismo pago.
    assert primero.id == segundo.id
