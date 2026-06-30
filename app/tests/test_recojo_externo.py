"""Pruebas unitarias del recojo externo de encomiendas (módulo asistente).

Cubren: creación de solicitud completa, rechazo por datos obligatorios faltantes,
listado/consulta, cambio de estado válido e inválido, y solicitud inexistente.
"""
import pytest

from app.modules.asistente import service
from app.modules.asistente.schema import SolicitudRecojoCreate


def _payload(**overrides) -> SolicitudRecojoCreate:
    base = dict(
        ciudad_origen="Lima",
        empresa_transporte_origen="Shalom",
        agencia_o_direccion_llegada="Agencia Shalom Trujillo - Av. España",
        destino_final="Angasmarca",
        nombre_destinatario_final="QA DESTINATARIO",
        usuario_correo="cliente.qa@test.local",
    )
    base.update(overrides)
    return SolicitudRecojoCreate(**base)


def test_crear_solicitud_completa(db_session):
    solicitud = service.create_solicitud_recojo(db_session, _payload())
    assert solicitud.id is not None
    assert solicitud.codigo_solicitud.startswith("RE-")
    assert solicitud.estado == "pendiente"
    assert solicitud.destino_final == "Angasmarca"


def test_rechaza_sin_destino_final():
    with pytest.raises(Exception):
        _payload(destino_final=None)


def test_rechaza_sin_empresa_de_origen():
    with pytest.raises(Exception):
        SolicitudRecojoCreate(
            ciudad_origen="Lima",
            agencia_o_direccion_llegada="Agencia X",
            destino_final="Angasmarca",
            nombre_destinatario_final="QA",
        )


def test_listar_y_consultar_solicitud(db_session):
    creada = service.create_solicitud_recojo(db_session, _payload())
    todas = service.list_solicitudes_recojo(db_session)
    assert any(s.id == creada.id for s in todas)
    una = service.get_solicitud_recojo(db_session, creada.id)
    assert una is not None and una.id == creada.id


def test_filtrar_solicitudes_por_estado(db_session):
    creada = service.create_solicitud_recojo(db_session, _payload())
    service.update_solicitud_estado(db_session, creada.id, "revisado")
    revisadas = service.list_solicitudes_recojo(db_session, estado="revisado")
    pendientes = service.list_solicitudes_recojo(db_session, estado="pendiente")
    assert all(s.estado == "revisado" for s in revisadas)
    assert creada.id not in {s.id for s in pendientes}


def test_cambiar_estado_valido(db_session):
    creada = service.create_solicitud_recojo(db_session, _payload())
    actualizada = service.update_solicitud_estado(db_session, creada.id, "convertido_a_preregistro")
    assert actualizada.estado == "convertido_a_preregistro"


def test_cambiar_estado_invalido_es_rechazado(db_session):
    creada = service.create_solicitud_recojo(db_session, _payload())
    with pytest.raises(ValueError):
        service.update_solicitud_estado(db_session, creada.id, "estado_que_no_existe")


def test_solicitud_inexistente_falla(db_session):
    with pytest.raises(LookupError):
        service.update_solicitud_estado(db_session, 999999, "revisado")
