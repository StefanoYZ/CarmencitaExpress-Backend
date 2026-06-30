"""Wizards conversacionales del asistente: cotización y pre-registro.

Recogen los datos paso a paso, muestran resumen con precio, confirman y crean el
pre-registro. Es un módulo hoja: depende de utilidades, LLM y repositorios, nunca
del service (que lo orquesta).
"""
from __future__ import annotations

import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.asistente import text_utils
from app.modules.asistente.schema import ChatRequest
from app.modules.clients import service as clients_service
from app.modules.quotes.service import DEFAULT_BASE_RATE, FRAGILITY_SURCHARGES, ROUTE_BASE_RATES
from app.modules.reniec.client import consultar_api_reniec
from app.modules.shipments.schema import ShipmentPreRegistrationCreate
from app.modules.shipments import service as shipments_service
from app.integrations import llm as asistente_llm_service

logger = logging.getLogger(__name__)

_norm_simple = text_utils.norm_simple
_extract_dni = text_utils.extract_dni
_contiene_numero = text_utils.contiene_numero
_contiene_numero_no_dni = text_utils.contiene_numero_no_dni
_es_solo_numero = text_utils.es_solo_numero


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


_OMITIR_TELEFONO = (
    "no tengo", "no tiene", "no cuento", "sin numero", "sin celular",
    "no hay numero", "no tengo numero", "no tengo celular", "omitir",
    "saltar", "no aplica", "no se el", "no lo tengo",
)


def _message_skips_phone(mensaje: str) -> bool:
    msg = _norm_simple(mensaje)
    return any(marker in msg for marker in _OMITIR_TELEFONO)




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




# Nombres públicos usados por el orquestador (service.py).
handle_cotizacion_wizard = _handle_cotizacion_wizard
handle_preregistro_wizard = _handle_preregistro_wizard
siguiente_campo_cotizacion = _siguiente_campo_cotizacion
message_skips_phone = _message_skips_phone
