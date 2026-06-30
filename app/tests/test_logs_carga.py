"""Pruebas unitarias de los logs de carga secuencial por paquete (logs_carga_paquete).

Cubren: creación de un log por paquete al ordenar, finalización del paquete actual
con cálculo de tiempo, encadenamiento del inicio del siguiente con el fin del anterior,
totales de la orden y manejo de lista vacía / orden inexistente.
"""
from datetime import timedelta

import pytest

from app.core.business_time import business_now
from app.modules.measurement_logs.service import (
    finalizar_paquete_carga,
    get_orden_carga_status,
    iniciar_orden_carga,
)


def test_iniciar_orden_crea_un_log_por_paquete(db_session):
    t0 = business_now()
    logs = iniciar_orden_carga(db_session, encomienda_ids=[101, 102, 103], timestamp_inicio=t0)
    assert len(logs) == 3
    assert logs[0].numero_paquete == 1
    assert logs[0].accion_inicio == "ordenar"
    assert logs[1].accion_inicio == "fin_anterior"
    assert all(log.timestamp_fin is None for log in logs)
    assert all(log.orden_carga_id == logs[0].orden_carga_id for log in logs)


def test_lista_vacia_es_rechazada(db_session):
    with pytest.raises(ValueError):
        iniciar_orden_carga(db_session, encomienda_ids=[])


def test_finalizar_paquete_calcula_tiempo_y_encadena_siguiente(db_session):
    t0 = business_now()
    logs = iniciar_orden_carga(db_session, encomienda_ids=[201, 202], timestamp_inicio=t0)
    orden = logs[0].orden_carga_id
    fin_pkg1 = t0 + timedelta(seconds=5)

    actual, siguiente = finalizar_paquete_carga(db_session, orden, 201, timestamp_fin=fin_pkg1)
    assert actual.tiempo_carga_ms == 5000
    assert actual.accion_fin == "siguiente_simulado"
    # El inicio del paquete 2 se encadena con el fin del paquete 1.
    assert siguiente is not None
    assert siguiente.timestamp_inicio == actual.timestamp_fin
    assert siguiente.accion_inicio == "fin_anterior"


def test_status_de_orden_acumula_totales(db_session):
    t0 = business_now()
    logs = iniciar_orden_carga(db_session, encomienda_ids=[301, 302], timestamp_inicio=t0)
    orden = logs[0].orden_carga_id
    finalizar_paquete_carga(db_session, orden, 301, timestamp_fin=t0 + timedelta(seconds=3))

    status = get_orden_carga_status(db_session, orden)
    assert status["total_paquetes"] == 2
    assert status["paquetes_cargados"] == 1
    assert status["paquetes_pendientes"] == 1
    assert status["tiempo_total_ms"] == 3000


def test_finalizar_paquete_inexistente_falla(db_session):
    with pytest.raises(LookupError):
        finalizar_paquete_carga(db_session, "OC-NOEXISTE", 999)
