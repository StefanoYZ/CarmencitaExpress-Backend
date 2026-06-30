"""Pruebas unitarias de tipos de contenido y base de conocimiento (módulo asistente).

Cubren: contenido permitido, contenido que requiere documentación, contenido con
revisión manual (restringido), filtro por activo, y alta/listado de base de
conocimiento.
"""
from app.modules.asistente import service
from app.modules.asistente.schema import BaseConocimientoCreate, TipoContenidoCreate


def test_crear_contenido_permitido(db_session):
    tipo = service.create_tipo_contenido(
        db_session,
        TipoContenidoCreate(nombre="Ropa", categoria="ROPA", permitido=True),
    )
    assert tipo.id is not None
    assert tipo.permitido is True
    assert tipo.requiere_documentacion in (False, None)


def test_crear_contenido_con_documentacion_requerida(db_session):
    tipo = service.create_tipo_contenido(
        db_session,
        TipoContenidoCreate(
            nombre="Medicamentos",
            categoria="OTROS",
            permitido=True,
            requiere_documentacion=True,
            documentacion_requerida="Receta médica / registro sanitario",
        ),
    )
    assert tipo.requiere_documentacion is True
    assert "Receta" in (tipo.documentacion_requerida or "")


def test_crear_contenido_con_revision_manual(db_session):
    tipo = service.create_tipo_contenido(
        db_session,
        TipoContenidoCreate(
            nombre="Líquidos inflamables",
            categoria="RESTRINGIDO",
            permitido=False,
            requiere_revision_manual=True,
            mensaje_cliente="Este contenido requiere revisión manual antes de aceptarse.",
        ),
    )
    assert tipo.requiere_revision_manual is True
    assert tipo.permitido is False


def test_filtra_tipos_contenido_por_activo(db_session):
    service.create_tipo_contenido(db_session, TipoContenidoCreate(nombre="Activo QA", activo=True))
    service.create_tipo_contenido(db_session, TipoContenidoCreate(nombre="Inactivo QA", activo=False))
    activos = service.list_tipos_contenido(db_session, activo=True)
    assert activos and all(t.activo for t in activos)


def test_alta_y_listado_base_conocimiento(db_session):
    creado = service.create_base_conocimiento(
        db_session,
        BaseConocimientoCreate(
            categoria="documentacion",
            pregunta_base="¿Qué documentos necesito?",
            respuesta="Para encomiendas con valor declarado se solicita DNI del remitente.",
        ),
    )
    assert creado.id is not None
    items = service.list_base_conocimiento(db_session, categoria="documentacion")
    assert any(i.id == creado.id for i in items)
