"""Servicio de integración con LLM (Gemini API) para el Asistente Virtual.

El backend es el único que conoce GEMINI_API_KEY.
El frontend nunca recibe la clave.

Flujo:
  React Chat UI → FastAPI endpoint → este servicio → Gemini API → respuesta controlada
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
Eres CarmiBot, el Asistente Virtual Inteligente de Carmencita Express Cargo.
Ayudas a clientes externos e internos con consultas sobre encomiendas, cotizaciones,
tracking, horarios, sedes, tipos de contenido y solicitudes de recojo externo.

REGLAS ESTRICTAS:
- No inventes precios, horarios, sedes, estados ni tarifas.
- Solo usa la información del contexto del sistema que se te provee.
- Si no tienes la información, indica que la secretaria puede ayudar.
- No confirmes pagos ni entregas que el sistema no haya confirmado.
- No crees encomiendas directamente; guía al usuario hacia el formulario.
- Responde siempre en español, de forma amigable y concisa.
- Si el usuario solicita datos de recojo externo, extráelos y devuélvelos en JSON.
""".strip()


def _llm_enabled() -> bool:
    return bool(settings.assistant_llm_enabled and settings.gemini_api_key)


def detectar_intencion(mensaje: str, contexto: dict | None = None) -> str:
    mensaje_lower = mensaje.lower()
    if any(word in mensaje_lower for word in ["cotiz", "precio", "costo", "cuánto", "cuanto", "tarif"]):
        return "cotizacion"
    if any(word in mensaje_lower for word in ["track", "seguimiento", "donde", "dónde", "estado", "paquete"]):
        return "tracking"
    if any(word in mensaje_lower for word in ["horario", "hora", "atiend", "abierto"]):
        return "horarios"
    if any(word in mensaje_lower for word in ["sede", "dirección", "direccion", "oficina", "agencia", "ubicación"]):
        return "sedes"
    if any(word in mensaje_lower for word in ["recojo", "recoge", "recoger", "pickup", "buscar paquete"]):
        return "recojo_externo"
    if any(word in mensaje_lower for word in ["pre-regist", "preregist", "registrar", "enviar", "quiero mandar"]):
        return "pre_registro"
    if any(word in mensaje_lower for word in ["enviar", "puedo enviar", "qué envío", "que envio", "contenido"]):
        return "contenido_permitido"
    if any(word in mensaje_lower for word in ["document", "requisito", "necesito"]):
        return "documentacion"
    return "consulta_general"


def generar_respuesta_controlada(
    mensaje: str,
    contexto: dict | None = None,
    datos_sistema: dict | None = None,
) -> str:
    """Genera respuesta usando Gemini si está habilitado; de lo contrario, usa fallback."""
    if not _llm_enabled():
        return _fallback_response(mensaje, contexto, datos_sistema)

    try:
        return _call_gemini(mensaje, contexto, datos_sistema)
    except Exception as exc:
        logger.warning("Gemini API error: %s — usando fallback", exc)
        return _fallback_response(mensaje, contexto, datos_sistema)


def extraer_datos_recojo_externo(mensaje: str) -> dict[str, Any]:
    """Extrae datos de una solicitud de recojo externo del mensaje del usuario."""
    if not _llm_enabled():
        return {}
    try:
        prompt = (
            f"Extrae del siguiente mensaje los datos de recojo externo en JSON con estas claves exactas: "
            f"ciudad_origen, empresa_transporte_origen, agencia_o_direccion_llegada, "
            f"codigo_guia_o_tracking, hora_aproximada_llegada, destino_final, "
            f"nombre_destinatario_final, telefono_destinatario, tipo_contenido, observaciones.\n"
            f"Devuelve SOLO el JSON sin explicaciones. Si algún campo no se menciona, pon null.\n\n"
            f"Mensaje: {mensaje}"
        )
        raw = _call_gemini_raw(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as exc:
        logger.warning("Error extrayendo datos de recojo: %s", exc)
    return {}


def extraer_datos_preregistro(mensaje: str) -> dict[str, Any]:
    """Extrae datos de un pre-registro del mensaje."""
    if not _llm_enabled():
        return {}
    try:
        prompt = (
            f"Extrae del siguiente mensaje los datos de pre-registro de encomienda en JSON con estas claves: "
            f"remitente_nombre, remitente_dni, remitente_telefono, destinatario_nombre, "
            f"destinatario_dni, destinatario_telefono, destino, descripcion, peso_kg, "
            f"largo_cm, ancho_cm, alto_cm, observaciones.\n"
            f"Devuelve SOLO el JSON sin explicaciones. Si no se menciona un campo, pon null.\n\n"
            f"Mensaje: {mensaje}"
        )
        raw = _call_gemini_raw(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as exc:
        logger.warning("Error extrayendo datos de pre-registro: %s", exc)
    return {}


def _call_gemini(mensaje: str, contexto: dict | None, datos_sistema: dict | None) -> str:
    contexto_texto = ""
    if datos_sistema:
        contexto_texto = f"\nContexto del sistema:\n{json.dumps(datos_sistema, ensure_ascii=False, indent=2)}"

    full_prompt = f"{_SYSTEM_PROMPT}{contexto_texto}\n\nUsuario: {mensaje}"
    return _call_gemini_raw(full_prompt)


def _call_gemini_raw(prompt: str) -> str:
    model = settings.gemini_model or "gemini-1.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 512, "temperature": 0.3},
    }
    with httpx.Client(timeout=20) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "").strip()
    return ""


def _fallback_response(mensaje: str, contexto: dict | None, datos_sistema: dict | None) -> str:
    intencion = detectar_intencion(mensaje, contexto)
    responses = {
        "cotizacion": (
            "Para conocer el precio de tu envío necesito: destino, peso y dimensiones del paquete. "
            "También puedes usar el cotizador en la página de inicio."
        ),
        "tracking": (
            "Para consultar el estado de tu paquete necesitas el código de encomienda. "
            "Ingrésalo en la sección de Tracking."
        ),
        "horarios": (
            "Atendemos de lunes a sábado de 8:00 am a 6:00 pm. "
            "Para más información puedes consultar con la secretaria."
        ),
        "sedes": (
            "Nuestra sede principal está en Trujillo. Para conocer la dirección exacta y sedes de destino, "
            "contacta con nosotros directamente."
        ),
        "recojo_externo": (
            "¡Claro! Carmencita Express puede recoger tu paquete en Trujillo que llegó de otra empresa. "
            "Necesito: ciudad de origen, empresa de transporte, dirección de llegada, "
            "código de guía, destino final y nombre del destinatario. ¿Me puedes dar esos datos?"
        ),
        "pre_registro": (
            "Te ayudo a pre-registrar tu envío. Necesito: nombre y DNI del remitente y destinatario, "
            "destino, descripción del contenido y dimensiones aproximadas del paquete."
        ),
        "contenido_permitido": (
            "Transportamos paquetes y documentos en general. Para contenidos especiales como alimentos "
            "perecibles, medicamentos o artículos frágiles, por favor consulta con la secretaria "
            "para confirmar los requisitos específicos."
        ),
        "documentacion": (
            "Para envíos estándar solo necesitas tu DNI. Para contenidos especiales puede requerirse "
            "documentación adicional. Consulta con la secretaria para tu caso específico."
        ),
        "consulta_general": (
            "Hola, soy CarmiBot, el asistente de Carmencita Express. "
            "Puedo ayudarte con cotizaciones, tracking, horarios, sedes y más. "
            "¿En qué te puedo ayudar?"
        ),
    }
    return responses.get(intencion, responses["consulta_general"])
