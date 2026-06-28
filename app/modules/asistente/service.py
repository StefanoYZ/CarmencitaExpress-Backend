"""Lógica de negocio del Asistente Virtual Inteligente."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.business_time import business_now
from app.modules.asistente.model import (
    AsistenteBaseConocimiento,
    AsistenteBusquedaWebCache,
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
from app.modules.clients import service as clients_service
from app.modules.quotes.service import DEFAULT_BASE_RATE, FRAGILITY_SURCHARGES, ROUTE_BASE_RATES
from app.modules.reniec.client import consultar_api_reniec
from app.modules.shipments.model import Shipment
from app.modules.shipments.schema import ShipmentPreRegistrationCreate
from app.modules.shipments import service as shipments_service
from app.services import asistente_llm_service
from app.services import web_search_service

logger = logging.getLogger(__name__)


# ── Chat ──────────────────────────────────────────────────────────────────────

def process_chat(db: Session, request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or uuid.uuid4().hex
    historial = (request.contexto_actual or {}).get("historial") or []
    datos_contexto = (request.contexto_actual or {}).get("datos_acumulados") or {}
    active_wizard = datos_contexto.get("_wizard")
    intencion = asistente_llm_service.detectar_intencion(request.mensaje, request.contexto_actual)
    if intencion == "consulta_general" and not datos_contexto:
        intencion_llm = asistente_llm_service.detectar_intencion_llm(request.mensaje, request.contexto_actual)
        if intencion_llm:
            intencion = intencion_llm

    # Si el pre-registro ya fue creado y espera elección de pago, todo el mensaje
    # (incluido "tarjeta"/"yape"/"agencia") debe ir al wizard, no a otra intención.
    if datos_contexto.get("_pago_pendiente"):
        intencion = "pre_registro"

    if active_wizard == "cotizacion_completada" and _message_accepts_quote(request.mensaje):
        intencion = "pre_registro"
        datos_contexto = {k: v for k, v in datos_contexto.items() if k != "_wizard"}
        contexto_actual = dict(request.contexto_actual or {})
        contexto_actual["datos_acumulados"] = datos_contexto
        request.contexto_actual = contexto_actual
        active_wizard = "pre_registro"

    # Si hay un wizard activo, se conserva solo cuando el mensaje no expresa
    # una intención clara distinta. Esto permite interrumpir con "horarios",
    # "sedes", "tracking", etc. y luego retomar el flujo anterior.
    if datos_contexto and _should_continue_active_wizard(
        intencion,
        request.mensaje,
        request.contexto_actual,
    ):
        # "cotizacion_completada" no es un intent manejable: una vez cotizado, la
        # continuación corresponde al pre-registro. Sin este mapeo, el flujo caía
        # al LLM libre y respondía como tracking/consulta genérica.
        if active_wizard == "cotizacion":
            intencion = "cotizacion"
        elif active_wizard in (None, "cotizacion_completada", "pre_registro"):
            intencion = "pre_registro"
        else:
            intencion = active_wizard

    # Fallback por keyword del último mensaje del bot (cubre el primer turno sin datos_acumulados).
    # Se incluye "documentacion" porque "DNI" activa ese intent accidentalmente.
    _INTENCIONES_DEBILES = {"consulta_general", "documentacion"}
    if intencion in _INTENCIONES_DEBILES and historial:
        ultimo_bot = next(
            (h.get("texto", "") for h in reversed(historial) if h.get("rol") == "asistente"),
            "",
        )
        _palabras_preregistro = (
            "para pre-registrar", "pre-registro",
            "dni del remitente", "dni del destinatario",
            "nombre del remitente", "nombre del destinatario",
            "nombre completo", "descripción del contenido",
            "peso aproximado", "datos faltantes", "datos adicionales",
            "necesito saber", "los siguientes datos", "los datos",
            "contenido del paquete", "dimensiones del paquete",
            "nivel de fragilidad", "sedes quieres enviar",
            "remitente encontrado", "destinatario encontrado",
        )
        _palabras_recojo = (
            "recojo externo", "empresa de transporte", "código de guía",
            "dirección de llegada", "recojo de tu paquete",
        )
        _palabras_tracking = (
            "código de seguimiento", "codigo de seguimiento",
            "código de encomienda", "codigo de encomienda",
            "últimos envíos", "ultimos envios", "envíame tu dni", "enviame tu dni",
        )
        # Limpiar markdown antes de comparar keywords
        ultimo_bot_limpio = ultimo_bot.replace("**", "").lower()
        if any(kw in ultimo_bot_limpio for kw in _palabras_preregistro):
            intencion = "pre_registro"
            logger.info("Intent sobreescrito a pre_registro por contexto del historial")
        elif any(kw in ultimo_bot_limpio for kw in _palabras_recojo):
            intencion = "recojo_externo"
            logger.info("Intent sobreescrito a recojo_externo por contexto del historial")
        elif any(kw in ultimo_bot_limpio for kw in _palabras_tracking):
            intencion = "tracking"
            logger.info("Intent sobreescrito a tracking por contexto del historial")

    datos_extraidos: dict | None = None
    requiere_accion = False
    accion_sugerida: str | None = None
    encomienda_id_creada: int | None = None

    if intencion == "pre_registro":
        # Wizard paso a paso — no necesita LLM para generar respuesta
        respuesta, datos_extraidos, requiere_accion, accion_sugerida, encomienda_id_creada = (
            _handle_preregistro_wizard(db, request, historial, session_id)
        )
    elif intencion == "tracking":
        respuesta = _handle_tracking_response(db, request.mensaje)
    elif intencion == "cotizacion":
        respuesta, datos_extraidos, requiere_accion, accion_sugerida = _handle_cotizacion_wizard(request)
    elif intencion in ("horarios", "sedes", "metodos_pago"):
        topicos = _detectar_topicos_info(request.mensaje)
        if len(topicos) >= 2:
            respuesta = _respuesta_info_combinada(topicos)
        elif intencion == "horarios":
            respuesta = _respuesta_horarios()
        elif intencion == "sedes":
            respuesta = _respuesta_sedes()
        else:
            respuesta = _respuesta_metodos_pago()
    elif intencion == "orientacion_base":
        respuesta = _respuesta_orientacion_base()
    elif intencion == "recojo_externo":
        respuesta = _handle_recojo_externo(db, request.mensaje, session_id)
    else:
        datos_sistema = _build_system_context(db, intencion)
        respuesta = asistente_llm_service.generar_respuesta_controlada(
            request.mensaje,
            contexto=request.contexto_actual,
            datos_sistema=datos_sistema,
        )

    log = _save_log(
        db,
        etapa=intencion,
        tipo_interaccion=_map_intencion_to_tipo(intencion),
        descripcion_interaccion=f"Mensaje: {request.mensaje[:500]}",
        session_id=session_id,
        cliente_id=request.cliente_id,
        usuario_correo=request.usuario_correo,
        canal=request.canal,
        encomienda_id=encomienda_id_creada,
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


def _extract_tracking_code(mensaje: str) -> str | None:
    match = re.search(r"\b([A-Za-z]\d{6,12})\b", mensaje or "")
    return match.group(1).upper() if match else None


def _message_accepts_quote(mensaje: str) -> bool:
    msg = _norm_simple(mensaje)
    return any(
        marker in msg
        for marker in (
            "quiero enviarlo",
            "quiero enviar",
            "acepto",
            "aceptar",
            "de acuerdo",
            "estoy de acuerdo",
            "perfecto",
            "me parece",
            "claro",
            "obvio",
            "ok",
            "okey",
            "dale",
            "listo",
            "esta bien",
            "esta ok",
            "esta perfecto",
            "continuar",
            "continuemos",
            "sigamos",
            "seguir",
            "adelante",
            "proceder",
            "procede",
            "hagamoslo",
            "hagamos el envio",
            "enviarlo",
            "registrarlo",
            "que necesito",
            "que se necesita",
            "que mas necesitas",
            "como lo envio",
            "como lo registro",
        )
    )


def _should_continue_active_wizard(intencion: str, mensaje: str, contexto: dict | None = None) -> bool:
    """Define si un mensaje debe alimentar el wizard activo o responder otra consulta.

    Un wizard activo no debe secuestrar preguntas claras como horarios, sedes,
    tracking o contenido permitido. Si el mensaje es genérico, un dato suelto o
    una continuación ("continuar", "sigamos"), se mantiene el flujo.
    """
    datos = (contexto or {}).get("datos_acumulados") or {}
    if datos.get("_wizard") == "cotizacion":
        campo_pendiente = _siguiente_campo_cotizacion(datos)
    else:
        campo_pendiente = asistente_llm_service.siguiente_campo_pendiente(datos)
    if campo_pendiente and _message_answers_expected_field(campo_pendiente, mensaje):
        return True

    explicit_interruptions = {
        "cotizacion",
        "tracking",
        "contenido_permitido",
        "horarios",
        "sedes",
        "metodos_pago",
        "recojo_externo",
        "orientacion_base",
    }
    if intencion in explicit_interruptions:
        return False

    msg = _norm_simple(mensaje)
    if intencion == "documentacion":
        document_question_markers = (
            "que documento",
            "que documentos",
            "que requisito",
            "que requisitos",
            "documentos necesito",
            "que necesito",
            "que piden",
        )
        return not any(marker in msg for marker in document_question_markers)

    continuation_markers = (
        "continuar",
        "sigamos",
        "seguir",
        "retomar",
        "volvamos",
        "continuemos",
        "ok",
        "listo",
    )
    if any(marker in msg for marker in continuation_markers):
        return True

    return intencion in {"consulta_general", "documentacion", "pre_registro"}


def _message_answers_expected_field(campo: str, mensaje: str) -> bool:
    msg = _norm_simple(mensaje)
    if campo in {"remitente_dni", "destinatario_dni"}:
        # DNI válido, o un mensaje que es esencialmente un número (intento de DNI,
        # aunque sea inválido → el wizard mostrará la validación). Evita capturar
        # interrupciones con números como "¿cuánto cuesta enviar 5 kg?".
        if _extract_dni(mensaje):
            return True
        return _es_solo_numero(mensaje)
    if campo in {"remitente_telefono", "destinatario_telefono"}:
        return _es_solo_numero(mensaje) or _message_skips_phone(mensaje)
    if campo in {"remitente_nombre", "destinatario_nombre"}:
        return bool(re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", mensaje or ""))
    if campo == "destino":
        return any(destino in msg for destino in asistente_llm_service._DESTINOS_VALIDOS)
    if campo == "descripcion":
        interruption_markers = (
            "horario",
            "sede",
            "direccion",
            "tracking",
            "seguimiento",
            "estado",
            "consultar",
            "rastrear",
            "rastreo",
            "donde esta",
            "codigo",
            "cotizar",
            "precio",
            "costo",
            "recojo",
        )
        content_markers = (
            "contenido",
            "paquete",
            "envio",
            "encomienda",
            "refrigeradora",
            "cocina",
            "televisor",
            "licuadora",
            "ropa",
            "documentos",
            "zapatos",
            "colchon",
            "canasta",
            "saco",
            "electrodomestico",
        )
        return any(marker in msg for marker in content_markers) and not any(
            marker in msg for marker in interruption_markers if marker not in {"paquete", "encomienda"}
        )
    if campo == "peso_kg":
        return bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:kg|kilo|kilogramo)?\b", mensaje or "", re.IGNORECASE))
    if campo == "dimensiones":
        return len(re.findall(r"(\d+(?:[.,]\d+)?)", mensaje or "")) >= 3
    if campo == "fragilidad":
        return any(valor in msg for valor in ("baja", "media", "alta", "fragil", "delicado"))
    return False


def _message_requests_missing_content_correction(mensaje: str) -> bool:
    msg = _norm_simple(mensaje)
    content_refs = ("contenido", "que se envia", "que voy a enviar", "que cosa", "paquete")
    missing_refs = (
        "no te di",
        "no te he dado",
        "no te dije",
        "no he dicho",
        "falta",
        "primero el contenido",
        "dar primero",
    )
    return any(ref in msg for ref in content_refs) and any(ref in msg for ref in missing_refs)


def _extract_dni(mensaje: str) -> str | None:
    match = re.search(r"\b(\d{8})\b", mensaje or "")
    return match.group(1) if match else None


def _contiene_numero_no_dni(mensaje: str) -> bool:
    """True si el mensaje trae dígitos pero ningún DNI válido de 8 dígitos.

    Sirve para detectar intentos de DNI mal escritos (ej. "1799") y dar una
    validación clara en vez de interpretarlos como nombre.
    """
    texto = mensaje or ""
    if re.search(r"\b\d{8}\b", texto):
        return False
    return bool(re.search(r"\d", texto))


def _contiene_numero(mensaje: str) -> bool:
    return bool(re.search(r"\d", mensaje or ""))


def _es_solo_numero(mensaje: str) -> bool:
    """True si el mensaje es esencialmente un número (dígitos y separadores)."""
    texto = (mensaje or "").strip()
    return bool(texto) and re.fullmatch(r"[\d\s.,-]+", texto) is not None


_OMITIR_TELEFONO = (
    "no tengo", "no tiene", "no cuento", "sin numero", "sin celular",
    "no hay numero", "no tengo numero", "no tengo celular", "omitir",
    "saltar", "no aplica", "no se el", "no lo tengo",
)


def _message_skips_phone(mensaje: str) -> bool:
    msg = _norm_simple(mensaje)
    return any(marker in msg for marker in _OMITIR_TELEFONO)


def _status_label(status: str | None) -> str:
    labels = {
        "PRE_REGISTRADA": "Pendiente de pago en agencia",
        "REGISTRADA": "Recepcionada",
        "COTIZADA": "Cotizada",
        "EN_TRANSITO": "En tránsito",
        "EN_DESTINO": "En destino",
        "ENTREGADA": "Entregada",
        "ANULADA": "Anulada",
    }
    normalized = (status or "").strip().upper()
    return labels.get(normalized, normalized.replace("_", " ").title() or "Sin estado")


def _shipment_line(shipment: Shipment, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    contenido = (shipment.description or shipment.content_type or "Sin descripción").strip()
    return (
        f"{prefix}**{shipment.shipment_code}** — {_status_label(shipment.status)} — "
        f"{shipment.origin} → {shipment.destination} — {contenido}"
    )


def _buscar_ultimas_encomiendas_por_dni(db: Session, dni: str) -> list[Shipment]:
    return (
        db.query(Shipment)
        .filter(
            (Shipment.sender_document_number == dni)
            | (Shipment.recipient_document_number == dni)
        )
        .order_by(Shipment.created_at.desc(), Shipment.id.desc())
        .limit(5)
        .all()
    )


def _handle_tracking_response(db: Session, mensaje: str) -> str:
    code = _extract_tracking_code(mensaje)
    if code:
        shipment = shipments_service.get_shipment_by_code(db, code)
        if not shipment:
            return (
                f"No encontré una encomienda con el código **{code}**. "
                "Verifica que esté escrito completo, por ejemplo **V000000027**. "
                "Si no tienes el código, envíame tu **DNI de 8 dígitos** y busco tus últimos envíos."
            )
        return (
            f"Encontré tu encomienda **{shipment.shipment_code}**.\n\n"
            f"• Estado: **{_status_label(shipment.status)}**\n"
            f"• Ruta: {shipment.origin} → {shipment.destination}\n"
            f"• Contenido: {shipment.description or 'Sin descripción'}\n"
            f"• Destinatario: {shipment.recipient_name}"
        )

    dni = _extract_dni(mensaje)
    if dni:
        shipments = _buscar_ultimas_encomiendas_por_dni(db, dni)
        if not shipments:
            return (
                "No encontré encomiendas asociadas a ese DNI. "
                "Si tienes el **código de seguimiento**, envíamelo para buscar directamente."
            )
        lines = "\n".join(_shipment_line(shipment, idx) for idx, shipment in enumerate(shipments, start=1))
        return (
            "Encontré estos últimos envíos asociados a tu DNI:\n\n"
            f"{lines}\n\n"
            "Si quieres el detalle de uno, envíame su código de seguimiento."
        )

    msg = _norm_simple(mensaje)
    if any(phrase in msg for phrase in ("no se", "no tengo", "no recuerdo", "no lo tengo", "no se a que")):
        return (
            "El código de seguimiento se ve por ejemplo así: **V000000027** o **L000000038**. "
            "Lo encuentras en tu comprobante o en la etiqueta del paquete. "
            "Si no lo tienes, envíame tu **DNI de 8 dígitos** y puedo buscar tus últimos 5 envíos."
        )

    return "¿Me podrías brindar tu **código de seguimiento**? Por ejemplo: **V000000027**."


def _respuesta_inicio_cotizacion() -> str:
    return (
        "Para cotizar tu envío necesitaré la siguiente información:\n\n"
        "• Sede de destino\n"
        "• Descripción del contenido\n"
        "• Peso (kg)\n"
        "• Dimensiones del paquete (largo × ancho × alto en cm)\n"
        "• Nivel de fragilidad\n\n"
        "Comencemos. Por favor indícame la **Sede de destino**."
    )


_PREGUNTAS_COTIZACION: dict[str, str] = {
    "destino": "Por favor indícame la **Sede de destino**.",
    "descripcion": "¿Cuál es la **descripción del contenido** que deseas enviar?",
    "peso_kg": "¿Cuál es el **peso aproximado en kg**?",
    "dimensiones": "¿Cuáles son las **dimensiones del paquete**? Ingresa largo × ancho × alto en cm. Ejemplo: 30x20x15",
    "fragilidad": "¿Qué **nivel de fragilidad** tiene? Puedes responder **BAJA**, **MEDIA** o **ALTA**.",
}


def _siguiente_campo_cotizacion(datos: dict) -> str | None:
    destino = datos.get("destino") or ""
    if not (destino and asistente_llm_service._normalize(destino) in asistente_llm_service._DESTINOS_VALIDOS):
        return "destino"
    if not datos.get("descripcion"):
        return "descripcion"
    try:
        if not (datos.get("peso_kg") and float(datos["peso_kg"]) > 0):
            return "peso_kg"
    except (TypeError, ValueError):
        return "peso_kg"
    if not (datos.get("largo_cm") and datos.get("ancho_cm") and datos.get("alto_cm")):
        return "dimensiones"
    if datos.get("fragilidad") not in ("BAJA", "MEDIA", "ALTA"):
        return "fragilidad"
    return None


def _extract_cotizacion_fields(datos: dict, mensaje: str, *, force_expected: str | None = None) -> None:
    msg_norm = _norm_simple(mensaje)

    if force_expected:
        valor = asistente_llm_service.extraer_campo_wizard(force_expected, mensaje)
        if force_expected == "dimensiones" and isinstance(valor, dict):
            datos.update(valor)
        elif valor is not None:
            datos[force_expected] = valor
        return

    destino = asistente_llm_service.extraer_campo_wizard("destino", mensaje)
    if destino:
        datos["destino"] = destino

    if force_expected == "descripcion" or any(
        marker in msg_norm
        for marker in (
            "contenido",
            "refrigeradora",
            "cocina",
            "televisor",
            "licuadora",
            "ropa",
            "documentos",
            "zapatos",
            "colchon",
            "canasta",
            "saco",
            "electrodomestico",
        )
    ):
        descripcion = asistente_llm_service.extraer_campo_wizard("descripcion", mensaje)
        if descripcion:
            datos["descripcion"] = descripcion

    peso = asistente_llm_service.extraer_campo_wizard("peso_kg", mensaje)
    if peso is not None:
        datos["peso_kg"] = peso

    dimensiones = asistente_llm_service.extraer_campo_wizard("dimensiones", mensaje)
    if isinstance(dimensiones, dict):
        datos.update(dimensiones)

    fragilidad = asistente_llm_service.extraer_campo_wizard("fragilidad", mensaje)
    if fragilidad:
        datos["fragilidad"] = fragilidad


def _generar_resumen_cotizacion(datos: dict) -> str:
    subtotal, total = _calcular_precio_estimado(datos)
    return (
        "Cotización estimada:\n\n"
        f"• Destino: **{datos.get('destino', '—')}**\n"
        f"• Contenido: {datos.get('descripcion', '—')}\n"
        f"• Peso: {datos.get('peso_kg', '—')} kg\n"
        f"• Dimensiones: {datos.get('largo_cm', '—')} × {datos.get('ancho_cm', '—')} × {datos.get('alto_cm', '—')} cm\n"
        f"• Fragilidad: {datos.get('fragilidad', '—')}\n\n"
        f"Precio estimado: **S/ {total:.2f}** (subtotal S/ {subtotal:.2f} + IGV 18%).\n\n"
        "¿Estás de acuerdo y deseas continuar con el envío? Responde **Sí** para registrar tu paquete."
    )


def _handle_cotizacion_wizard(request: ChatRequest) -> tuple[str, dict | None, bool, str | None]:
    datos_previos: dict = (request.contexto_actual or {}).get("datos_acumulados") or {}
    datos = dict(datos_previos) if datos_previos.get("_wizard") == "cotizacion" else {"_wizard": "cotizacion"}

    campo_esperado = _siguiente_campo_cotizacion(datos)
    _extract_cotizacion_fields(datos, request.mensaje, force_expected=campo_esperado)

    siguiente = _siguiente_campo_cotizacion(datos)
    if siguiente is None:
        datos_limpios = {k: v for k, v in datos.items() if k != "_wizard"}
        datos_limpios["_wizard"] = "cotizacion_completada"
        return _generar_resumen_cotizacion(datos_limpios), datos_limpios, False, "cotizacion_completada"

    intro_ya_enviado = any(
        "para cotizar tu envío" in h.get("texto", "").lower()
        for h in ((request.contexto_actual or {}).get("historial") or [])
        if h.get("rol") == "asistente"
    )

    if not intro_ya_enviado and not any(k in datos for k in ("destino", "descripcion", "peso_kg")):
        respuesta = _respuesta_inicio_cotizacion()
    else:
        respuesta = _PREGUNTAS_COTIZACION[siguiente]

    return respuesta, datos, True, "iniciar_cotizacion"


# Palabras clave para detectar consultas informativas combinadas
# (p. ej. "¿horarios y dónde están las sedes?" debe responder ambos temas).
_INFO_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "horarios": ("horario", "hora de atencion", "a que hora", "que hora",
                 "atienden", "atencion", "abren", "cierran", "abierto"),
    "sedes": ("sede", "sedes", "donde estan", "donde queda", "ubicacion",
              "direccion", "oficina", "agencia", "sucursal"),
    "metodos_pago": ("metodo de pago", "metodos de pago", "forma de pago",
                     "formas de pago", "medios de pago", "medio de pago",
                     "yape", "tarjeta", "efectivo"),
}


def _detectar_topicos_info(mensaje: str) -> list[str]:
    """Devuelve los temas informativos presentes en el mensaje (horarios/sedes/pagos)."""
    msg = _norm_simple(mensaje)
    return [tema for tema, kws in _INFO_TOPIC_KEYWORDS.items() if any(kw in msg for kw in kws)]


def _respuesta_info_combinada(topicos: list[str]) -> str:
    """Combina las respuestas de varios temas informativos en una sola."""
    generadores = {
        "horarios": _respuesta_horarios,
        "sedes": _respuesta_sedes,
        "metodos_pago": _respuesta_metodos_pago,
    }
    partes = [generadores[t]() for t in ("horarios", "sedes", "metodos_pago") if t in topicos]
    return "\n\n".join(partes)


def _respuesta_orientacion_base() -> str:
    return (
        "La **cara que eliges** es la que irá apoyada hacia abajo durante el viaje, es decir, "
        "sobre qué lado se transportará el paquete.\n\n"
        "Por ejemplo, una **refrigeradora** debe viajar **parada**: su base es la cara de abajo "
        "(la más pequeña), no una lateral. Si eligieras una cara lateral, viajaría acostada y "
        "podría dañarse.\n\n"
        "En resumen: elige la cara sobre la que el paquete queda **estable y seguro** para su traslado."
    )


def _respuesta_horarios() -> str:
    return (
        "Atendemos de **7:30 a. m. a 6:00 p. m.** en la sede principal de Trujillo. "
        "Para consultas puntuales sobre recepción, recojo o seguimiento, puedes comunicarte con la agencia."
    )


def _respuesta_sedes() -> str:
    return (
        "La sede principal está en **Av. América Sur 257, Trujillo 13006**. "
        "Para envíos trabajamos con sedes de destino en la ruta Trujillo–Angasmarca."
    )


def _respuesta_metodos_pago() -> str:
    return "Si, aceptamos **Yape**, **tarjeta** y **efectivo/pago en agencia**."


def _respuesta_inicio_recojo_externo() -> str:
    return (
        "Para solicitar un recojo externo primero necesito cotizar la encomienda.\n\n"
        "Indícame estos datos:\n"
        "• **Sede exacta** o dirección donde debemos recogerla (nombre de la agencia y su dirección)\n"
        "• Qué se va a recoger\n"
        "• Peso aproximado en kg\n"
        "• Dimensiones del paquete (largo × ancho × alto en cm)\n"
        "• Nivel de fragilidad\n\n"
        "Con eso te doy una cotización. Si la aceptas, luego te pediré los datos de recepción.\n\n"
        "Comencemos: ¿de qué **sede o dirección exacta** debemos recoger tu paquete? "
        "Si no estás seguro de la sede, dime el nombre de la agencia (por ejemplo, OLVA) y te ayudo a ubicarla."
    )


def _es_consulta_sedes_agencia(mensaje: str) -> bool:
    """Detecta si el cliente está preguntando por las sedes/sucursales de una agencia."""
    msg = _norm_simple(mensaje)
    marcadores = (
        "sede", "sedes", "sucursal", "sucursales", "agencias",
        "cuantas", "cuantos", "donde queda", "donde esta", "donde estan",
        "ubicacion", "ubicada", "direccion de", "que agencias", "en trujillo",
    )
    return any(m in msg for m in marcadores)


# Agencias de transporte/courier conocidas (para agrupar la caché por agencia,
# de modo que "sedes de shalom" y "en shalom recógelo" reusen el mismo resultado).
_AGENCIAS_CONOCIDAS = (
    "shalom", "olva", "marvisur", "cruz del sur", "oltursa", "civa",
    "emtrafesa", "ittsa", "flores", "tepsa", "cromotex", "beltran",
    "movil tours", "moderno", "ave fenix", "sullana",
)

# Días que se considera vigente un resultado de búsqueda guardado en caché.
_CACHE_SEDES_DIAS = 30


def _clave_busqueda_sedes(mensaje: str) -> str:
    """Clave de caché: por agencia si se reconoce, si no por el mensaje normalizado."""
    msg = _norm_simple(mensaje)
    agencia = next((a for a in _AGENCIAS_CONOCIDAS if a in msg), None)
    base = agencia if agencia else " ".join(msg.split())
    return ("sedes:" + base)[:120]


def _buscar_cache_web(db: Session, clave: str) -> AsistenteBusquedaWebCache | None:
    return (
        db.query(AsistenteBusquedaWebCache)
        .filter(AsistenteBusquedaWebCache.consulta_clave == clave)
        .first()
    )


def _cache_web_vigente(entry: AsistenteBusquedaWebCache | None) -> bool:
    if not entry or not entry.respuesta:
        return False
    referencia = entry.updated_at or entry.created_at
    if referencia is None:
        return True
    try:
        return (business_now() - referencia).days < _CACHE_SEDES_DIAS
    except (TypeError, ValueError):
        return True


def _guardar_cache_web(
    db: Session, clave: str, consulta_original: str, respuesta: str, resultados: list[dict]
) -> None:
    try:
        resultados_json = json.dumps(resultados, ensure_ascii=False)[:8000]
        entry = _buscar_cache_web(db, clave)
        if entry:
            entry.respuesta = respuesta
            entry.resultados_json = resultados_json
            entry.consulta_original = (consulta_original or "")[:500]
            entry.veces_consultada = (entry.veces_consultada or 1) + 1
        else:
            db.add(AsistenteBusquedaWebCache(
                consulta_clave=clave,
                consulta_original=(consulta_original or "")[:500],
                respuesta=respuesta,
                resultados_json=resultados_json,
                veces_consultada=1,
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("No se pudo guardar la caché de búsqueda web: %s", exc)


def _resumir_resultados_sedes(mensaje: str, resultados: list[dict]) -> str | None:
    """Resume los resultados de búsqueda en una respuesta para el cliente.

    Usa el LLM SOLO sobre los resultados encontrados (no inventa datos). Si el LLM
    no está disponible, lista los resultados. Devuelve None si no hay nada útil.
    """
    contexto = "\n".join(
        f"- {r.get('titulo', '')}: {r.get('snippet', '')} ({r.get('link', '')})"
        for r in resultados if r.get("titulo")
    )
    if not contexto.strip():
        return None

    cierre = "\n\nCuando tengas la **sede o dirección exacta** del recojo, indícamela para continuar."

    if asistente_llm_service._llm_enabled():
        prompt = (
            "El cliente pregunta por las sedes/sucursales de una agencia de transporte en Trujillo (Perú). "
            "Resume de forma breve y clara, EN ESPAÑOL, usando ÚNICAMENTE los resultados de búsqueda dados. "
            "No inventes direcciones ni datos que no estén en los resultados. Si no hay suficiente información, "
            "dilo y pide la dirección exacta. Máximo 5 líneas.\n\n"
            f"Consulta del cliente: {mensaje}\n\n"
            f"Resultados de búsqueda:\n{contexto}"
        )
        try:
            resumen = asistente_llm_service._call_llm(prompt).strip()
            if resumen:
                return f"{resumen}{cierre}"
        except Exception as exc:
            logger.warning("No se pudo resumir la búsqueda de sedes: %s", exc)

    # Respaldo sin LLM: listar los resultados encontrados.
    lineas = [
        f"• {r['titulo']}" + (f" — {r['snippet']}" if r.get("snippet") else "")
        for r in resultados if r.get("titulo")
    ][:5]
    if not lineas:
        return None
    return "Esto encontré sobre las sedes:\n\n" + "\n".join(lineas) + cierre


def _responder_consulta_sedes_agencia(
    db: Session, mensaje: str, session_id: str | None = None
) -> str | None:
    """Responde sobre sedes de una agencia usando caché en BD o búsqueda web.

    Devuelve None si la búsqueda no está disponible o no hay resultados, para que
    el asistente pida la dirección exacta en su lugar.
    """
    # Validación: necesita texto y la búsqueda web debe estar configurada.
    if not mensaje or not mensaje.strip() or not web_search_service.busqueda_web_disponible():
        return None

    clave = _clave_busqueda_sedes(mensaje)

    # 1. Caché: si ya se consultó algo equivalente y sigue vigente, responder al instante.
    entry = _buscar_cache_web(db, clave)
    if _cache_web_vigente(entry):
        try:
            entry.veces_consultada = (entry.veces_consultada or 1) + 1
            db.commit()
        except Exception:
            db.rollback()
        _save_log(
            db,
            etapa="recojo_externo",
            tipo_interaccion="busqueda_web_cache",
            descripcion_interaccion=f"Resultado reusado de caché ({clave})",
            session_id=session_id,
            canal="externo",
            resultado="cache_hit",
        )
        return entry.respuesta

    # 2. Búsqueda web (con validación de resultados).
    query = f"{mensaje.strip()} agencias sedes en Trujillo Perú dirección"
    resultados = web_search_service.buscar_web(query, num=6)
    if not resultados:
        return None

    respuesta = _resumir_resultados_sedes(mensaje, resultados)
    if not respuesta:
        return None

    # 3. Guardar para futuras consultas iguales.
    _guardar_cache_web(db, clave, mensaje, respuesta, resultados)
    _save_log(
        db,
        etapa="recojo_externo",
        tipo_interaccion="busqueda_web",
        descripcion_interaccion=f"Búsqueda web guardada en caché ({clave})",
        session_id=session_id,
        canal="externo",
        resultado="busqueda_web_guardada",
    )
    return respuesta


def _handle_recojo_externo(db: Session, mensaje: str, session_id: str | None = None) -> str:
    """Maneja el recojo externo: consulta de sedes (con caché) o el flujo normal."""
    if _es_consulta_sedes_agencia(mensaje):
        respuesta = _responder_consulta_sedes_agencia(db, mensaje, session_id)
        if respuesta:
            return respuesta
        # Sin búsqueda web disponible o sin resultados: pedir la dirección exacta.
        return (
            "Para coordinar el recojo necesito la **dirección exacta** o el nombre de la sede "
            "donde debemos recoger tu paquete. ¿Me la indicas?"
        )
    return _respuesta_inicio_recojo_externo()


def _calcular_precio_estimado(datos: dict) -> tuple[float, float]:
    """Aplica la misma fórmula que quotes/service.py. Devuelve (subtotal, total_con_igv)."""
    import unicodedata

    def _norm(v: str) -> str:
        t = " ".join(v.strip().split()).lower()
        return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")

    route_key = (_norm("Trujillo"), _norm(datos.get("destino") or ""))
    base_rate = ROUTE_BASE_RATES.get(route_key, DEFAULT_BASE_RATE)

    peso = float(datos.get("peso_kg") or 1.0)
    largo = float(datos.get("largo_cm") or 30.0)
    ancho = float(datos.get("ancho_cm") or 30.0)
    alto = float(datos.get("alto_cm") or 30.0)
    frag = datos.get("fragilidad") or "BAJA"

    weight_cost = peso * 2.00
    volume_m3 = largo * ancho * alto / 1_000_000
    volume_cost = volume_m3 * 20.00
    frag_surcharge = FRAGILITY_SURCHARGES.get(frag, 0.00)

    subtotal = base_rate + weight_cost + volume_cost + frag_surcharge
    total = subtotal * 1.18
    return round(subtotal, 2), round(total, 2)


def _generar_resumen_confirmacion(datos: dict) -> str:
    """Construye el mensaje de resumen con precio estimado para que el usuario confirme."""
    frag_labels = {"BAJA": "Baja (resistente)", "MEDIA": "Media (requiere cuidado)", "ALTA": "Alta (muy frágil)"}
    subtotal, total = _calcular_precio_estimado(datos)

    rem_dni = f" (DNI: {datos['remitente_dni']})" if datos.get("remitente_dni") else ""
    dest_dni = f" (DNI: {datos['destinatario_dni']})" if datos.get("destinatario_dni") else ""
    rem_tel = f" · Cel: {datos['remitente_telefono']}" if datos.get("remitente_telefono") else ""
    dest_tel = f" · Cel: {datos['destinatario_telefono']}" if datos.get("destinatario_telefono") else ""

    return (
        "Resumen del envío a pre-registrar:\n\n"
        f"• Remitente: **{datos.get('remitente_nombre', '—')}**{rem_dni}{rem_tel}\n"
        f"• Destinatario: **{datos.get('destinatario_nombre', '—')}**{dest_dni}{dest_tel}\n"
        f"• Destino: **{datos.get('destino', '—')}**\n"
        f"• Contenido: {datos.get('descripcion', '—')}\n"
        f"• Peso: {datos.get('peso_kg', '—')} kg\n"
        f"• Dimensiones: {datos.get('largo_cm', '—')} × {datos.get('ancho_cm', '—')} × {datos.get('alto_cm', '—')} cm\n"
        f"• Fragilidad: {frag_labels.get(datos.get('fragilidad', ''), '—')}\n\n"
        f"Costo estimado: **S/ {total:.2f}** (subtotal S/ {subtotal:.2f} + IGV 18%)\n\n"
        "¿Confirmas el pre-registro? Responde **Sí** para continuar o **No** para modificar algún dato."
    )


def _consultar_persona(db: Session, dni: str) -> tuple[str | None, str | None]:
    """Busca por DNI: BD de clientes primero, luego RENIEC.

    Devuelve (nombre_completo, telefono). El teléfono solo proviene de la BD de
    clientes (RENIEC no entrega celular); si no está registrado, se devuelve None
    para pedírselo al cliente.
    """
    dni = str(dni).strip()
    if not dni.isdigit() or len(dni) != 8:
        return None, None
    nombre: str | None = None
    telefono: str | None = None
    # 1. Base de datos propia (nombre + teléfono).
    # OJO: el modelo Client expone los atributos Python `full_name` y `phone`
    # (mapeados a las columnas nombre_completo/telefono). Usar los nombres de
    # columna devuelve None y haría pedir el celular aunque ya esté registrado.
    cliente = clients_service.get_client_by_dni(db, dni)
    if cliente:
        nombre = (getattr(cliente, "full_name", None) or "").strip() or None
        telefono = (getattr(cliente, "phone", None) or "").strip() or None
    # 2. RENIEC (solo nombre) si la BD no lo tenía.
    if not nombre:
        try:
            res = consultar_api_reniec(dni)
            if "error" not in res:
                partes = [res.get("nombres", ""), res.get("apellido_paterno", ""), res.get("apellido_materno", "")]
                nombre = " ".join(p for p in partes if p).strip() or None
        except Exception as exc:
            logger.warning("RENIEC error para DNI %s: %s", dni, exc)
    return nombre, telefono


_KEYWORDS_MODIFICAR: dict[str, list[str]] = {
    "remitente": ["remitente", "quien envia", "quien manda", "el que envia"],
    "destinatario": ["destinatario", "quien recibe", "el que recibe"],
    "destino": ["destino", "sede", "lugar", "ciudad", "a donde", "adonde", "para donde"],
    "descripcion": ["descripcion", "contenido", "que contiene", "que envio", "que mando"],
    "peso": ["peso", "kilogramo", "kg"],
    "dimensiones": ["dimension", "largo", "ancho", "alto", "tamano", "medida"],
    "fragilidad": ["fragilidad", "fragil", "delicado"],
    "telefono_remitente": ["telefono del remitente", "celular del remitente", "numero del remitente"],
    "telefono_destinatario": ["telefono del destinatario", "celular del destinatario", "numero del destinatario"],
}

_AFIRMATIVOS = frozenset(["si", "sí", "yes", "confirmo", "correcto", "ok", "dale", "adelante",
                           "procede", "esta bien", "esta ok", "listo", "afirmativo", "confirmar"])
_NEGATIVOS = frozenset(["no", "nope", "modificar", "cambiar", "corregir", "incorrecto",
                         "quiero cambiar", "quiero modificar", "equivoque", "equivoqué"])

# Frases que indican que el cliente quiere abandonar el pre-registro por completo
# (distinto de "No" para modificar un dato).
_CANCELAR = (
    "ya no quiero", "ya no deseo", "ya no necesito", "ya no voy", "ya no",
    "no deseo", "no quiero enviar", "no quiero nada", "no enviar nada", "no enviar",
    "cancelar", "cancela", "anular", "anula", "olvidalo", "olvidar", "dejalo",
    "dejarlo", "mejor no", "no gracias", "no, gracias", "ya no gracias",
)


def _message_requests_cancel(mensaje: str) -> bool:
    msg = _norm_simple(mensaje)
    return any(marker in msg for marker in _CANCELAR)


def _cancelar_wizard() -> tuple[str, dict | None, bool, str | None, int | None]:
    """Aborta el pre-registro y limpia el estado del wizard en el frontend."""
    return (
        "De acuerdo, cancelé el pre-registro. No se guardó nada. "
        "Si más adelante deseas enviar un paquete, aquí estaré para ayudarte. 😊",
        None, False, "preregistro_cancelado", None,
    )


def _norm_simple(texto: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")


def _detectar_campo_a_modificar(mensaje: str) -> str | None:
    msg = _norm_simple(mensaje)
    for campo, palabras in _KEYWORDS_MODIFICAR.items():
        if any(p in msg for p in palabras):
            return campo
    return None


def _resetear_campo(datos: dict, campo: str) -> None:
    mapa = {
        "remitente": ["remitente_dni", "remitente_nombre", "remitente_telefono", "_pedir_remitente_tel", "_remitente_tel_omitido"],
        "destinatario": ["destinatario_dni", "destinatario_nombre", "destinatario_telefono", "_pedir_destinatario_tel", "_destinatario_tel_omitido"],
        "destino": ["destino"],
        "descripcion": ["descripcion"],
        "peso": ["peso_kg"],
        "dimensiones": ["largo_cm", "ancho_cm", "alto_cm"],
        "fragilidad": ["fragilidad"],
        "telefono_remitente": ["remitente_telefono"],
        "telefono_destinatario": ["destinatario_telefono"],
    }
    for key in mapa.get(campo, []):
        datos.pop(key, None)


def _actualizar_flag_telefono(datos: dict, quien: str) -> None:
    """Marca _pedir_<quien>_tel cuando hay nombre pero no celular (no está en la BD)."""
    if datos.get(f"_{quien}_tel_omitido"):
        # El cliente ya indicó que no tiene/no dará el celular: no volver a pedirlo.
        datos.pop(f"_pedir_{quien}_tel", None)
        return
    if datos.get(f"{quien}_nombre"):
        if datos.get(f"{quien}_telefono"):
            datos.pop(f"_pedir_{quien}_tel", None)
        else:
            datos[f"_pedir_{quien}_tel"] = True


def _enriquecer_reniec(db: Session, datos: dict) -> tuple[str | None, str | None]:
    """Completa nombre y celular desde BD/RENIEC y marca si falta pedir el celular.

    Devuelve (nombre_rem_nuevo, nombre_dest_nuevo) para anunciarlos en el chat.
    """
    nombre_rem_nuevo = None
    nombre_dest_nuevo = None
    if datos.get("remitente_dni") and (
        not datos.get("remitente_nombre") or not datos.get("remitente_telefono")
    ):
        nombre, telefono = _consultar_persona(db, str(datos["remitente_dni"]))
        if nombre and not datos.get("remitente_nombre"):
            datos["remitente_nombre"] = nombre
            nombre_rem_nuevo = nombre
        if telefono and not datos.get("remitente_telefono"):
            datos["remitente_telefono"] = telefono
    if datos.get("destinatario_dni") and (
        not datos.get("destinatario_nombre") or not datos.get("destinatario_telefono")
    ):
        nombre, telefono = _consultar_persona(db, str(datos["destinatario_dni"]))
        if nombre and not datos.get("destinatario_nombre"):
            datos["destinatario_nombre"] = nombre
            nombre_dest_nuevo = nombre
        if telefono and not datos.get("destinatario_telefono"):
            datos["destinatario_telefono"] = telefono

    # Si tras la búsqueda no hay celular registrado, marcar para pedirlo.
    _actualizar_flag_telefono(datos, "remitente")
    _actualizar_flag_telefono(datos, "destinatario")
    return nombre_rem_nuevo, nombre_dest_nuevo


def _manejar_respuesta_confirmacion(
    db: Session, datos: dict, mensaje: str, session_id: str
) -> tuple[str, dict | None, bool, str | None, int | None]:
    msg = _norm_simple(mensaje)
    es_afirmativo = any(a in msg for a in _AFIRMATIVOS)
    es_negativo = any(n in msg for n in _NEGATIVOS)

    if es_afirmativo and not es_negativo:
        datos.pop("_confirmado", None)
        resultado = _crear_preregistro_desde_chat(db, datos, session_id)
        if resultado:
            codigo = resultado.shipment_code
            datos["codigo_encomienda"] = codigo
            datos["encomienda_id"] = resultado.id
            # Pasa a elegir método de pago (en línea ahora o en agencia).
            datos["_pago_pendiente"] = True
            respuesta = (
                "¡Pre-registro creado con éxito!\n"
                f"Código: **{codigo}**\n\n"
                "¿Cómo deseas pagar?\n"
                "• **En línea** — paga ahora con Yape o tarjeta y tu encomienda queda registrada al instante.\n"
                "• **En agencia** — paga de forma presencial al llegar a la sede de Trujillo.\n\n"
                "Responde **en línea** o **en agencia**."
            )
            return respuesta, datos, True, "elegir_metodo_pago", resultado.id
        return (
            "Tuve un problema al registrar tu envío. "
            "Comunícate con la secretaría o intenta de nuevo.",
            datos or None, False, None, None,
        )

    if es_negativo:
        # Si ya especificó el campo a modificar en el mismo mensaje, resetear directamente
        campo = _detectar_campo_a_modificar(mensaje)
        if campo:
            _resetear_campo(datos, campo)
            datos.pop("_confirmado", None)
            siguiente = asistente_llm_service.siguiente_campo_pendiente(datos)
            pregunta = asistente_llm_service._PREGUNTAS_CAMPO.get(siguiente, "")
            return pregunta, datos or None, True, "iniciar_preregistro", None
        datos["_confirmado"] = "modificando"
        return (
            "Entendido. ¿Qué dato deseas modificar?\n\n"
            "Puedes decirme: **remitente**, **destinatario**, **destino**, "
            "**descripción**, **peso**, **dimensiones** o **fragilidad**.",
            datos, True, "pendiente_confirmacion", None,
        )

    return (
        "Por favor confirma respondiendo **Sí** para crear el pre-registro "
        "o **No** si deseas modificar algún dato.",
        datos, True, "pendiente_confirmacion", None,
    )


_PAGO_ONLINE_MARKERS = (
    "en linea", "linea", "online", "internet", "ahora", "pagar ahora",
    "por internet", "web", "tarjeta", "yape", "plin", "de una vez", "ya mismo",
)
_PAGO_AGENCIA_MARKERS = (
    "agencia", "presencial", "al llegar", "en la sede", "en sede", "despues",
    "luego", "mas tarde", "efectivo", "en persona", "voy a la agencia",
)


def _manejar_eleccion_pago(
    datos: dict, mensaje: str
) -> tuple[str, dict | None, bool, str | None, int | None]:
    """Tras crear el pre-registro, decide si el cliente paga en línea o en agencia."""
    msg = _norm_simple(mensaje)
    online = any(m in msg for m in _PAGO_ONLINE_MARKERS)
    agencia = any(m in msg for m in _PAGO_AGENCIA_MARKERS)
    encomienda_id = datos.get("encomienda_id")

    if online and not agencia:
        datos_pago = {k: v for k, v in datos.items() if not k.startswith("_")}
        return (
            "Perfecto, te llevo a la pantalla de **confirmación y pago en línea** para que pagues "
            "ahora con Yape o tarjeta. Al aprobarse el pago, tu encomienda quedará registrada. 💳",
            datos_pago, True, "pagar_online", encomienda_id,
        )
    if agencia and not online:
        return (
            "Listo. Puedes acercarte a la **agencia en Trujillo** para pagar y formalizar tu envío. "
            "La secretaria validará la cara/base del paquete antes del cobro. 😊",
            None, True, "preregistro_creado", encomienda_id,
        )
    return (
        "¿Cómo prefieres pagar? Responde **en línea** para pagar ahora con Yape o tarjeta, "
        "o **en agencia** para pagar de forma presencial al llegar.",
        datos, True, "elegir_metodo_pago", encomienda_id,
    )


def _handle_preregistro_wizard(
    db: Session,
    request,
    historial: list[dict],
    session_id: str,
) -> tuple[str, dict | None, bool, str | None, int | None]:
    """Wizard guiado de pre-registro: recoge campos, muestra resumen con precio y confirma antes de crear."""
    datos_previos: dict = (request.contexto_actual or {}).get("datos_acumulados") or {}
    datos = dict(datos_previos)
    # Marca el wizard activo como pre-registro para que los turnos siguientes
    # mantengan el flujo determinista y no caigan al LLM libre (lo que provocaba
    # respuestas tipo tracking o re-preguntar datos ya entregados).
    datos["_wizard"] = "pre_registro"
    confirmado = datos.get("_confirmado")

    # --- Fase: pre-registro ya creado, eligiendo método de pago ---
    if datos.get("_pago_pendiente"):
        return _manejar_eleccion_pago(datos, request.mensaje)

    # --- Cancelación: el cliente abandona el pre-registro en cualquier fase ---
    if datos and _message_requests_cancel(request.mensaje):
        return _cancelar_wizard()

    # --- Fase: esperando Sí / No ---
    if confirmado is False:
        return _manejar_respuesta_confirmacion(db, datos, request.mensaje, session_id)

    # --- Fase: usuario dijo "No", debe indicar qué cambiar ---
    if confirmado == "modificando":
        campo = _detectar_campo_a_modificar(request.mensaje)
        if campo:
            _resetear_campo(datos, campo)
            datos.pop("_confirmado", None)
            _enriquecer_reniec(db, datos)
            siguiente = asistente_llm_service.siguiente_campo_pendiente(datos)
            pregunta = asistente_llm_service._PREGUNTAS_CAMPO.get(siguiente, "")
            return pregunta, datos or None, True, "iniciar_preregistro", None
        return (
            "No entendí qué dato deseas modificar. Puedes decirme: "
            "**remitente**, **destinatario**, **destino**, **descripción**, "
            "**peso**, **dimensiones** o **fragilidad**.",
            datos, True, "pendiente_confirmacion", None,
        )

    # --- Fase: recolección de campos ---
    if _message_requests_missing_content_correction(request.mensaje):
        datos.pop("descripcion", None)
        datos.pop("_confirmado", None)
        return (
            asistente_llm_service._PREGUNTAS_CAMPO["descripcion"],
            datos or None,
            True,
            "iniciar_preregistro",
            None,
        )

    campo_esperado = asistente_llm_service.siguiente_campo_pendiente(datos)

    if campo_esperado in ("remitente_dni", "destinatario_dni"):
        dni = asistente_llm_service.extraer_campo_wizard(campo_esperado, request.mensaje)
        nombre_dest = (
            asistente_llm_service.extraer_campo_wizard("destinatario_nombre", request.mensaje)
            if campo_esperado == "destinatario_dni" and not dni
            else None
        )
        if dni:
            datos[campo_esperado] = dni
        elif nombre_dest:
            # Para el destinatario el DNI es opcional: se acepta el nombre directamente.
            datos["destinatario_nombre"] = nombre_dest
        elif _contiene_numero_no_dni(request.mensaje):
            # El cliente escribió un número que NO es un DNI válido de 8 dígitos.
            quien = "remitente" if campo_esperado == "remitente_dni" else "destinatario"
            extra = (
                "" if campo_esperado == "remitente_dni"
                else " Si no lo tienes, escribe directamente su **nombre completo**."
            )
            return (
                f"El **DNI del {quien}** debe tener exactamente **8 dígitos** (solo números). "
                f"Por favor ingrésalo nuevamente.{extra}",
                datos or None, True, "iniciar_preregistro", None,
            )
    elif campo_esperado in ("remitente_telefono", "destinatario_telefono"):
        quien = "remitente" if campo_esperado == "remitente_telefono" else "destinatario"
        if _message_skips_phone(request.mensaje):
            # El cliente no tiene/ no desea dar el celular: continuar sin él.
            datos[f"_{quien}_tel_omitido"] = True
            datos.pop(f"_pedir_{quien}_tel", None)
        else:
            telefono = asistente_llm_service.extraer_campo_wizard(campo_esperado, request.mensaje)
            if telefono:
                datos[campo_esperado] = telefono
                datos.pop(f"_pedir_{quien}_tel", None)
            elif _contiene_numero(request.mensaje):
                return (
                    f"El **número de celular del {quien}** debe tener **9 dígitos** y empezar con **9** "
                    "(ej: 987654321). Por favor ingrésalo nuevamente, o escribe *no tengo* para continuar.",
                    datos or None, True, "iniciar_preregistro", None,
                )
    elif campo_esperado == "destino":
        valor = asistente_llm_service.extraer_campo_wizard("destino", request.mensaje)
        if valor:
            datos["destino"] = valor
        elif request.mensaje.strip():
            return (
                "No reconozco esa sede. " + asistente_llm_service._PREGUNTAS_CAMPO["destino"],
                datos or None, True, "iniciar_preregistro", None,
            )
    elif campo_esperado == "peso_kg":
        valor = asistente_llm_service.extraer_campo_wizard("peso_kg", request.mensaje)
        if valor is not None:
            datos["peso_kg"] = valor
        elif _contiene_numero(request.mensaje):
            return (
                "El **peso** debe ser un número mayor a 0 en kilogramos (ej: 2.5). "
                "Por favor ingrésalo nuevamente.",
                datos or None, True, "iniciar_preregistro", None,
            )
    elif campo_esperado == "dimensiones":
        valor = asistente_llm_service.extraer_campo_wizard("dimensiones", request.mensaje)
        if isinstance(valor, dict):
            datos.update(valor)
        elif _contiene_numero(request.mensaje):
            return (
                "Necesito las **3 dimensiones**: largo × ancho × alto en cm (ej: 30x20x15). "
                "Por favor ingrésalas nuevamente.",
                datos or None, True, "iniciar_preregistro", None,
            )
    elif campo_esperado == "fragilidad":
        valor = asistente_llm_service.extraer_campo_wizard("fragilidad", request.mensaje)
        if valor:
            datos["fragilidad"] = valor
        elif request.mensaje.strip():
            return (
                "No reconocí el nivel de fragilidad. Responde **BAJA**, **MEDIA** o **ALTA**.",
                datos or None, True, "iniciar_preregistro", None,
            )
    elif campo_esperado:
        valor = asistente_llm_service.extraer_campo_wizard(campo_esperado, request.mensaje)
        if valor is not None:
            datos[campo_esperado] = valor

    nombre_rem_nuevo, nombre_dest_nuevo = _enriquecer_reniec(db, datos)
    siguiente = asistente_llm_service.siguiente_campo_pendiente(datos)

    # --- Todos los campos completos → mostrar resumen y pedir confirmación ---
    if siguiente is None:
        datos["_confirmado"] = False
        return _generar_resumen_confirmacion(datos), datos, True, "pendiente_confirmacion", None

    # --- Campos incompletos → siguiente pregunta ---
    intro_ya_enviado = any(
        "para pre-registrar" in h.get("texto", "").lower()
        for h in historial
        if h.get("rol") == "asistente"
    )

    partes: list[str] = []
    if nombre_rem_nuevo:
        partes.append(f"Remitente encontrado: **{nombre_rem_nuevo}** (DNI: {datos['remitente_dni']}).")
    if nombre_dest_nuevo:
        partes.append(f"Destinatario encontrado: **{nombre_dest_nuevo}** (DNI: {datos['destinatario_dni']}).")

    if siguiente == "remitente_dni" and not intro_ya_enviado:
        respuesta = asistente_llm_service._INTRO_PREREGISTRO
    else:
        if partes:
            partes.append("")
        partes.append(asistente_llm_service._PREGUNTAS_CAMPO[siguiente])
        respuesta = "\n".join(partes)

    return respuesta, datos or None, True, "iniciar_preregistro", None


def _crear_preregistro_desde_chat(db: Session, datos: dict, session_id: str):
    """Crea el pre-registro en BD a partir de los datos del wizard."""
    try:
        def _f(v) -> float:
            return float(str(v).replace(",", ".")) if v else 0.0

        fragilidad = (datos.get("fragilidad") or "BAJA").strip().upper()
        if fragilidad not in ("BAJA", "MEDIA", "ALTA"):
            fragilidad = "BAJA"

        payload = ShipmentPreRegistrationCreate.model_validate({
            "remitente_tipo_documento": "DNI",
            "remitente_numero_documento": str(datos.get("remitente_dni") or "").strip(),
            "remitente_nombre": str(datos.get("remitente_nombre") or "").strip(),
            "remitente_telefono": str(datos.get("remitente_telefono") or "").strip() or None,
            "destinatario_nombre": str(datos.get("destinatario_nombre") or "").strip(),
            "destinatario_tipo_documento": "DNI" if datos.get("destinatario_dni") else None,
            "destinatario_numero_documento": str(datos.get("destinatario_dni") or "").strip() or None,
            "destinatario_telefono": str(datos.get("destinatario_telefono") or "").strip() or None,
            "origen": "Trujillo",
            "destino": str(datos.get("destino") or "").strip(),
            "descripcion": str(datos.get("descripcion") or "").strip(),
            "tipo_contenido": None,
            "peso_kg": _f(datos.get("peso_kg")) or 1.0,
            "largo_cm": _f(datos.get("largo_cm")) or 30.0,
            "ancho_cm": _f(datos.get("ancho_cm")) or 30.0,
            "alto_cm": _f(datos.get("alto_cm")) or 30.0,
            "fragilidad": fragilidad,
            "orientacion_base": "LARGO_ANCHO",
        })
        shipment = shipments_service.create_pre_registration(db, payload)
        # CarmiBot no tiene interfaz visual para que el cliente elija la cara/base.
        # Se deja pendiente para que secretaria la seleccione al completar el cobro.
        shipment.base_orientation = None
        db.add(shipment)
        db.commit()
        db.refresh(shipment)
        return shipment
    except (ValidationError, ValueError, Exception) as exc:
        logger.warning("No se pudo crear pre-registro desde chat: %s", exc)
        return None


# ── Validación de coherencia del paquete ──────────────────────────────────────

# Mapeo de campo del paquete → tipo de error registrado en la tabla de logs.
_TIPO_ERROR_POR_CAMPO = {
    "peso_kg": "valor_numerico_invalido",
    "largo_cm": "valor_numerico_invalido",
    "ancho_cm": "valor_numerico_invalido",
    "alto_cm": "valor_numerico_invalido",
    "descripcion": "descripcion_inconsistente",
    "tipo_contenido": "incoherencia_tipo_contenido",
    "orientacion_base": "orientacion_incorrecta",
}


def validar_coherencia_paquete(db: Session, payload, *, session_id: str | None = None) -> dict:
    """Valida la coherencia de los datos del paquete y registra cada error detectado.

    Cada advertencia se guarda como un log independiente, mapeado a la estructura de
    la tabla de errores (campo_afectado, valor_ingresado, tipo_error, etc.) para que
    el reporte del asistente pueda analizar los errores prevenidos por campo y tipo.
    """
    advertencias = asistente_llm_service.validar_coherencia_paquete(
        tipo_contenido=payload.tipo_contenido,
        descripcion=payload.descripcion,
        peso_kg=payload.peso_kg,
        largo_cm=payload.largo_cm,
        ancho_cm=payload.ancho_cm,
        alto_cm=payload.alto_cm,
        fragilidad=payload.fragilidad,
        orientacion_base=payload.orientacion_base,
    )

    valores_por_campo = {
        "peso_kg": payload.peso_kg,
        "largo_cm": payload.largo_cm,
        "ancho_cm": payload.ancho_cm,
        "alto_cm": payload.alto_cm,
        "descripcion": payload.descripcion,
        "tipo_contenido": payload.tipo_contenido,
        "orientacion_base": payload.orientacion_base,
    }

    for adv in advertencias:
        campo = adv.get("campo")
        valor = valores_por_campo.get(campo)
        _save_log(
            db,
            etapa="validacion_coherencia",
            tipo_interaccion="prevencion_error",
            descripcion_interaccion=str(adv.get("mensaje", ""))[:480],
            session_id=session_id,
            canal="externo",
            existe_error=True,
            ayudo_corregir_prevenir_error=True,
            tipo_error=_TIPO_ERROR_POR_CAMPO.get(campo, "incoherencia_datos_paquete"),
            accion_correctiva_aplicada="Se advirtió al cliente sobre un posible error antes de enviar.",
            campo_afectado=campo,
            valor_ingresado=None if valor is None else str(valor)[:255],
            resultado="advertencia_mostrada",
        )

    return {"tiene_advertencias": bool(advertencias), "advertencias": advertencias}


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

_STATIC_KNOWLEDGE_BASE = [
    {
        "categoria": "horarios",
        "pregunta_base": "Horario de atención",
        "respuesta": "Atendemos de 7:30 a. m. a 6:00 p. m. en la sede principal de Trujillo.",
    },
    {
        "categoria": "sedes",
        "pregunta_base": "Sede principal",
        "respuesta": "La sede principal está en Av. América Sur 257, Trujillo 13006.",
    },
    {
        "categoria": "metodos_pago",
        "pregunta_base": "Metodos de pago aceptados",
        "respuesta": "Si, aceptamos Yape, tarjeta y efectivo/pago en agencia.",
    },
    {
        "categoria": "tracking",
        "pregunta_base": "Consulta de estado de paquete",
        "respuesta": (
            "Para consultar el estado necesito el código de seguimiento, por ejemplo V000000027. "
            "Si no tienes el código, puedo buscar tus últimos envíos con tu DNI de 8 dígitos."
        ),
    },
    {
        "categoria": "cotizacion",
        "pregunta_base": "Datos para cotizar",
        "respuesta": (
            "Para cotizar un envío necesito sede de destino, descripción del contenido, peso, "
            "dimensiones del paquete y nivel de fragilidad."
        ),
    },
    {
        "categoria": "recojo_externo",
        "pregunta_base": "Recojo externo",
        "respuesta": (
            "Para solicitar recojo externo primero se cotiza la encomienda con agencia o dirección "
            "de recojo, contenido, peso, dimensiones y fragilidad. Si el cliente acepta, se piden "
            "los datos de recepción."
        ),
    },
    {
        "categoria": "contenido",
        "pregunta_base": "Contenido permitido",
        "respuesta": (
            "Transportamos documentos, ropa, paquetes personales, alimentos no perecibles y "
            "electrodomésticos. Los artículos frágiles deben declararse para aplicar el cuidado correspondiente."
        ),
    },
    {
        "categoria": "documentacion",
        "pregunta_base": "Documentos necesarios",
        "respuesta": "Para envíos estándar se solicita DNI del remitente y datos del destinatario.",
    },
]


# Categorías de la base de conocimiento relevantes según la intención detectada.
_INTENCION_CATEGORIAS = {
    "cotizacion": ["cotizacion", "tarifas", "precios"],
    "tracking": ["tracking", "seguimiento", "estados"],
    "horarios": ["horarios"],
    "sedes": ["sedes", "ubicaciones"],
    "metodos_pago": ["metodos_pago", "pagos"],
    "recojo_externo": ["recojo_externo"],
    "pre_registro": ["pre_registro", "registro"],
    "contenido_permitido": ["contenido", "tipos_contenido"],
    "documentacion": ["documentacion", "requisitos"],
}


def _build_system_context(db: Session, intencion: str) -> dict:
    """Arma el contexto de datos REALES que se pasa al LLM.

    Solo entrega información existente en la base de datos (base de conocimiento
    y tipos de contenido). Esto evita que el asistente invente precios, horarios,
    sedes, estados, tarifas o reglas que no estén registradas.
    """
    categorias = _INTENCION_CATEGORIAS.get(intencion, [])

    entradas_db = [
        {
            "categoria": e.categoria,
            "pregunta_base": e.pregunta_base,
            "respuesta": e.respuesta,
        }
        for e in list_base_conocimiento(db, activo=True)
    ]
    entradas = entradas_db + _STATIC_KNOWLEDGE_BASE
    relevantes = [e for e in entradas if e["categoria"] in categorias] if categorias else []
    # Si no hay coincidencias por categoría, se entregan todas las activas como respaldo.
    seleccionadas = relevantes or entradas

    base_conocimiento = seleccionadas

    datos: dict = {"base_conocimiento": base_conocimiento}

    if intencion in ("contenido_permitido", "documentacion"):
        tipos = list_tipos_contenido(db, activo=True)
        datos["tipos_contenido"] = [
            {
                "nombre": t.nombre,
                "categoria": t.categoria,
                "permitido": t.permitido,
                "requiere_documentacion": t.requiere_documentacion,
                "documentacion_requerida": t.documentacion_requerida,
                "requiere_revision_manual": t.requiere_revision_manual,
                "mensaje_cliente": t.mensaje_cliente,
            }
            for t in tipos
        ]

    return datos


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
    campo_afectado: str | None = None,
    valor_ingresado: str | None = None,
    valor_corregido: str | None = None,
    resultado: str | None = None,
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
        campo_afectado=campo_afectado,
        valor_ingresado=valor_ingresado,
        valor_corregido=valor_corregido,
        resultado=resultado,
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
        "metodos_pago": "consulta_informativa",
        "recojo_externo": "recojo_externo",
        "pre_registro": "pre_registro_guiado",
        "contenido_permitido": "consulta_informativa",
        "documentacion": "consulta_informativa",
        "orientacion_base": "consulta_informativa",
        "consulta_general": "consulta_informativa",
    }
    return mapping.get(intencion, "consulta_informativa")
