"""Pruebas de caracterización del asistente (CarmiBot).

Cubren el enrutamiento de intenciones y los wizards sin depender del LLM
(en el entorno de test no hay GROQ_API_KEY, así que se usan las respuestas por
reglas). Sirven de red de seguridad para refactorizar el módulo.
"""
from app.modules.asistente import service
from app.modules.asistente.schema import ChatRequest, ValidacionCoherenciaRequest


def _chat(db, mensaje, contexto=None):
    return service.process_chat(
        db,
        ChatRequest(mensaje=mensaje, canal="externo", contexto_actual=contexto),
    )


def test_intencion_horarios(db_session):
    resp = _chat(db_session, "¿a qué hora atienden?")
    assert resp.intencion_detectada == "horarios"
    assert "7:30" in resp.respuesta


def test_intencion_sedes(db_session):
    resp = _chat(db_session, "¿dónde están ubicados?")
    assert resp.intencion_detectada == "sedes"
    assert "América Sur" in resp.respuesta


def test_cotizacion_inicia_pidiendo_destino(db_session):
    resp = _chat(db_session, "quiero cotizar un envío")
    assert resp.intencion_detectada == "cotizacion"
    assert "destino" in resp.respuesta.lower()


def test_pre_registro_inicia_pidiendo_dni_remitente(db_session):
    resp = _chat(db_session, "quiero pre-registrar un envío")
    assert resp.intencion_detectada == "pre_registro"
    assert "DNI del remitente" in resp.respuesta


def test_recojo_externo_pide_agencia(db_session):
    resp = _chat(db_session, "quiero solicitar un recojo externo de encomienda")
    assert resp.intencion_detectada == "recojo_externo"
    assert "agencia" in resp.respuesta.lower()


def test_recojo_externo_detecta_agencia_shalom(db_session):
    # Sin SEARCH_API_KEY la búsqueda web no está disponible: pide la dirección,
    # pero igualmente debe enrutar a recojo_externo (no a pre_registro/tracking).
    resp = _chat(db_session, "en shalom")
    assert resp.intencion_detectada == "recojo_externo"


def test_tracking_pide_codigo(db_session):
    resp = _chat(db_session, "quiero rastrear mi paquete")
    assert resp.intencion_detectada == "tracking"
    assert "seguimiento" in resp.respuesta.lower()


def test_cotizacion_completa_muestra_precio(db_session):
    datos = {
        "_wizard": "cotizacion",
        "destino": "Shorey",
        "descripcion": "ropa",
        "peso_kg": 3,
        "largo_cm": 30,
        "ancho_cm": 20,
        "alto_cm": 15,
    }
    # Falta solo la fragilidad: al darla, debe cerrar con el precio estimado.
    resp = _chat(db_session, "fragilidad baja", contexto={"datos_acumulados": datos})
    assert resp.intencion_detectada == "cotizacion"
    assert "Precio estimado" in resp.respuesta


def test_pre_registro_confirma_crea_y_pide_metodo_pago(db_session):
    datos = {
        "_wizard": "pre_registro",
        "_confirmado": False,
        "remitente_dni": "70123456",
        "remitente_nombre": "Juan Perez",
        "destinatario_dni": "70876543",
        "destinatario_nombre": "Maria Lopez",
        "destino": "Shorey",
        "descripcion": "ropa",
        "peso_kg": 3,
        "largo_cm": 30,
        "ancho_cm": 20,
        "alto_cm": 15,
        "fragilidad": "BAJA",
    }
    resp = _chat(db_session, "sí", contexto={"datos_acumulados": datos})
    assert resp.accion_sugerida == "elegir_metodo_pago"
    assert resp.datos_extraidos.get("encomienda_id")

    # Elegir pago en línea debe redirigir al pago online.
    resp2 = _chat(db_session, "en línea", contexto={"datos_acumulados": resp.datos_extraidos})
    assert resp2.accion_sugerida == "pagar_online"


def test_validar_coherencia_detecta_incoherencia(db_session):
    payload = ValidacionCoherenciaRequest(
        tipo_contenido="ALIMENTOS",
        descripcion="refrigeradora",
        peso_kg="20",
        largo_cm="60",
        ancho_cm="60",
        alto_cm="170",
        fragilidad="MEDIA",
        orientacion_base="LARGO_ANCHO",
    )
    resultado = service.validar_coherencia_paquete(db_session, payload)
    assert isinstance(resultado, dict)
    assert "advertencias" in resultado
    assert "tiene_advertencias" in resultado


def _campos_advertidos(db_session, descripcion):
    payload = ValidacionCoherenciaRequest(
        tipo_contenido="OTROS", descripcion=descripcion,
    )
    resultado = service.validar_coherencia_paquete(db_session, payload)
    return {adv["campo"] for adv in resultado["advertencias"]}


def test_validar_coherencia_marca_descripcion_sin_sentido(db_session):
    # Teclazos, patrones repetidos o solo números deben marcar la descripción.
    for basura in ("asdasdasd", "1111111", "qwerty", "aaaa", "..."):
        assert "descripcion" in _campos_advertidos(db_session, basura), basura


def test_validar_coherencia_no_molesta_descripciones_reales(db_session):
    # Descripciones válidas no deben generar advertencia en la descripción.
    for real in ("ropa", "documentos varios", "repuestos de auto", "dvd"):
        assert "descripcion" not in _campos_advertidos(db_session, real), real


def test_preregistro_chat_paquete_que_debe_ir_parado(db_session):
    """Regresión: un paquete que debe ir parado (p. ej. 'cocina') fallaba al
    pre-registrar desde el chat porque el wizard fijaba orientacion_base=LARGO_ANCHO.
    Ahora el wizard elige una base segura según las dimensiones."""
    from app.modules.asistente.wizard import _crear_preregistro_desde_chat

    datos = {
        "remitente_dni": "17935065",
        "remitente_nombre": "JAIME ANGEL YEPEZ BENITES",
        "remitente_telefono": "968222374",
        "destinatario_dni": "76619947",
        "destinatario_nombre": "ANGEL STEFANO YEPEZ ZAPATA",
        "destinatario_telefono": "954684440",
        "destino": "Shorey",
        "descripcion": "cocina",
        "peso_kg": "50",
        "largo_cm": "120",
        "ancho_cm": "50",
        "alto_cm": "75",
        "fragilidad": "MEDIA",
    }
    shipment = _crear_preregistro_desde_chat(db_session, datos, "sess-test")
    assert shipment is not None
    assert shipment.shipment_code
