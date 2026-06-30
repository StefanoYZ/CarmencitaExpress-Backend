"""Lógica de negocio del Asistente Virtual Inteligente."""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.asistente import coherence
from app.modules.asistente import repository
from app.modules.asistente import text_utils
from app.modules.asistente import web_search
from app.modules.asistente import wizard
from app.modules.asistente.model import (
    AsistenteBaseConocimiento,
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
from app.modules.shipments.model import Shipment
from app.modules.shipments import service as shipments_service
from app.integrations import llm as asistente_llm_service

logger = logging.getLogger(__name__)

_siguiente_campo_cotizacion = wizard.siguiente_campo_cotizacion
_message_skips_phone = wizard.message_skips_phone

# Alias a las utilidades de texto (definidas en text_utils) para uso interno.
_norm_simple = text_utils.norm_simple
_extract_dni = text_utils.extract_dni
_contiene_numero = text_utils.contiene_numero
_contiene_numero_no_dni = text_utils.contiene_numero_no_dni
_es_solo_numero = text_utils.es_solo_numero


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

    # Dispatch por intención (OCP): cada intent tiene su handler en _INTENT_HANDLERS.
    # Agregar una intención = registrar un handler nuevo, sin tocar process_chat.
    ctx = _IntentContext(db=db, request=request, historial=historial, session_id=session_id, intencion=intencion)
    handler = _INTENT_HANDLERS.get(intencion, _handle_intent_default)
    respuesta, datos_extraidos, requiere_accion, accion_sugerida, encomienda_id_creada = handler(ctx)

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


# ── Dispatch de intenciones (OCP) ─────────────────────────────────────────────
# Cada handler recibe un _IntentContext y devuelve la tupla normalizada
# (respuesta, datos_extraidos, requiere_accion, accion_sugerida, encomienda_id).

@dataclass
class _IntentContext:
    db: Session
    request: ChatRequest
    historial: list[dict]
    session_id: str
    intencion: str


def _handle_intent_preregistro(ctx: "_IntentContext"):
    return wizard.handle_preregistro_wizard(ctx.db, ctx.request, ctx.historial, ctx.session_id)


def _handle_intent_cotizacion(ctx: "_IntentContext"):
    respuesta, datos, requiere, accion = wizard.handle_cotizacion_wizard(ctx.request)
    return respuesta, datos, requiere, accion, None


def _handle_intent_tracking(ctx: "_IntentContext"):
    return _handle_tracking_response(ctx.db, ctx.request.mensaje), None, False, None, None


def _handle_intent_info(ctx: "_IntentContext"):
    topicos = _detectar_topicos_info(ctx.request.mensaje)
    if len(topicos) >= 2:
        respuesta = _respuesta_info_combinada(topicos)
    elif ctx.intencion == "horarios":
        respuesta = _respuesta_horarios()
    elif ctx.intencion == "sedes":
        respuesta = _respuesta_sedes()
    else:
        respuesta = _respuesta_metodos_pago()
    return respuesta, None, False, None, None


def _handle_intent_orientacion_base(ctx: "_IntentContext"):
    return _respuesta_orientacion_base(), None, False, None, None


def _handle_intent_recojo_externo(ctx: "_IntentContext"):
    return web_search.handle_recojo_externo(ctx.db, ctx.request.mensaje, ctx.session_id), None, False, None, None


def _handle_intent_default(ctx: "_IntentContext"):
    datos_sistema = _build_system_context(ctx.db, ctx.intencion)
    respuesta = asistente_llm_service.generar_respuesta_controlada(
        ctx.request.mensaje,
        contexto=ctx.request.contexto_actual,
        datos_sistema=datos_sistema,
    )
    return respuesta, None, False, None, None


_INTENT_HANDLERS = {
    "pre_registro": _handle_intent_preregistro,
    "cotizacion": _handle_intent_cotizacion,
    "tracking": _handle_intent_tracking,
    "horarios": _handle_intent_info,
    "sedes": _handle_intent_info,
    "metodos_pago": _handle_intent_info,
    "orientacion_base": _handle_intent_orientacion_base,
    "recojo_externo": _handle_intent_recojo_externo,
}


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
    return repository.ultimas_encomiendas_por_dni(db, dni, limite=5)


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


# ── Validación de coherencia del paquete ──────────────────────────────────────

def validar_coherencia_paquete(db: Session, payload, *, session_id: str | None = None) -> dict:
    return coherence.validar_coherencia_paquete(db, payload, session_id=session_id)


# ── Logs ──────────────────────────────────────────────────────────────────────

def create_log(db: Session, payload: LogAsistenteCreate):
    return repository.add_log(
        db,
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
    )


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
):
    return repository.list_logs(
        db,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        etapa=etapa,
        tipo_interaccion=tipo_interaccion,
        existe_error=existe_error,
        ayudo_corregir_prevenir_error=ayudo_corregir_prevenir_error,
        tipo_error=tipo_error,
        actor_origen=actor_origen,
        canal=canal,
    )


def get_report_summary(db: Session) -> dict:
    logs = repository.all_logs(db)
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
    solicitud = repository.add_solicitud_recojo(db, solicitud)

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


def list_solicitudes_recojo(db: Session, *, estado: str | None = None):
    return repository.list_solicitudes_recojo(db, estado=estado)


def get_solicitud_recojo(db: Session, solicitud_id: int):
    return repository.get_solicitud_recojo(db, solicitud_id)


def update_solicitud_estado(db: Session, solicitud_id: int, estado: str):
    solicitud = repository.get_solicitud_recojo(db, solicitud_id)
    if solicitud is None:
        raise LookupError("Solicitud de recojo externo no encontrada")
    estados_validos = {"pendiente", "revisado", "confirmado", "rechazado", "convertido_a_preregistro"}
    if estado not in estados_validos:
        raise ValueError(f"Estado inválido. Opciones: {', '.join(estados_validos)}")
    solicitud.estado = estado
    return repository.save_solicitud_recojo(db, solicitud)


# ── Base de Conocimiento ──────────────────────────────────────────────────────

def create_base_conocimiento(db: Session, payload: BaseConocimientoCreate):
    return repository.add_base_conocimiento(db, AsistenteBaseConocimiento(**payload.model_dump()))


def list_base_conocimiento(db: Session, *, categoria: str | None = None, activo: bool | None = None):
    return repository.list_base_conocimiento(db, categoria=categoria, activo=activo)


# ── Tipos de Contenido ────────────────────────────────────────────────────────

def create_tipo_contenido(db: Session, payload: TipoContenidoCreate):
    return repository.add_tipo_contenido(db, TiposContenidoTransporte(**payload.model_dump()))


def list_tipos_contenido(db: Session, *, activo: bool | None = None):
    return repository.list_tipos_contenido(db, activo=activo)


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
):
    return repository.add_log(
        db,
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
    )


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
