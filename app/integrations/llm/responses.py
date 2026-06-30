"""Generación de respuestas controladas y fallback por reglas."""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
import unicodedata
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

from app.integrations.llm.client import _SYSTEM_PROMPT, _normalize, _llm_enabled, _call_llm, _call_groq_raw
from app.integrations.llm.nlp import detectar_intencion


def generar_respuesta_controlada(
    mensaje: str,
    contexto: dict | None = None,
    datos_sistema: dict | None = None,
) -> str:
    """Genera respuesta: Groq → fallback por reglas."""
    if not _llm_enabled():
        return _fallback_response(mensaje, contexto, datos_sistema)

    contexto_texto = ""
    if datos_sistema:
        contexto_texto = f"\nContexto del sistema:\n{json.dumps(datos_sistema, ensure_ascii=False, indent=2)}"

    historial_texto = ""
    historial = (contexto or {}).get("historial") or []
    if historial:
        lineas = [
            f"{'Usuario' if h.get('rol') == 'usuario' else 'CarmiBot'}: {h.get('texto', '')}"
            for h in historial[-8:]
        ]
        historial_texto = "\n\nHistorial de conversación:\n" + "\n".join(lineas)

    full_prompt = f"{_SYSTEM_PROMPT}{contexto_texto}{historial_texto}\n\nUsuario: {mensaje}"

    respuesta = _call_llm(full_prompt)
    if respuesta:
        return respuesta
    return _fallback_response(mensaje, contexto, datos_sistema)

def _fallback_response(mensaje: str, contexto: dict | None, datos_sistema: dict | None) -> str:
    intencion = detectar_intencion(mensaje, contexto)

    # Si hay datos reales en la base de conocimiento, se priorizan sobre las
    # respuestas genéricas para no inventar información (precios, horarios, sedes).
    respuesta_kb = _respuesta_desde_base_conocimiento(datos_sistema)
    if respuesta_kb:
        return respuesta_kb

    # Respuestas genéricas de respaldo. NO afirman precios, horarios, sedes ni
    # tarifas concretas: piden los datos o derivan a la secretaría.
    responses = {
        "cotizacion": (
            "Para cotizar tu envío necesito: sede de destino, descripción del contenido, peso, "
            "dimensiones del paquete y nivel de fragilidad. Comencemos con la **sede de destino**."
        ),
        "tracking": (
            "¿Me podrías brindar tu **código de seguimiento**? Por ejemplo: **V000000027**. "
            "Si no lo tienes, puedo buscar tus últimos envíos con tu **DNI**."
        ),
        "horarios": (
            "Atendemos de 7:30 a. m. a 6:00 p. m. en la sede principal de Trujillo."
        ),
        "sedes": (
            "Nuestra sede principal está en Av. América Sur 257, Trujillo 13006. "
            "También operamos sedes de destino en la ruta Trujillo–Angasmarca."
        ),
        "metodos_pago": (
            "Si, aceptamos **Yape**, **tarjeta** y **efectivo/pago en agencia**."
        ),
        "recojo_externo": (
            "Para solicitar un recojo externo primero necesito cotizar la encomienda. "
            "Indícame la **agencia o dirección de recojo**, contenido, peso, dimensiones y fragilidad."
        ),
        "pre_registro": (
            "Te ayudo a pre-registrar tu envío. Necesito: nombre y DNI del remitente y destinatario, "
            "destino, descripción del contenido y dimensiones aproximadas del paquete."
        ),
        "contenido_permitido": (
            "Transportamos paquetes y documentos en general. Para contenidos especiales como alimentos "
            "perecibles, medicamentos o artículos frágiles, por favor consulta con la secretaría "
            "para confirmar los requisitos específicos."
        ),
        "documentacion": (
            "Para envíos estándar normalmente solo necesitas tu DNI. Para contenidos especiales puede "
            "requerirse documentación adicional. Consulta con la secretaría para tu caso específico."
        ),
        "consulta_general": (
            "Hola, soy CarmiBot, el asistente de Carmencita Express. "
            "Puedo ayudarte con cotizaciones, tracking, horarios, sedes y más. "
            "¿En qué te puedo ayudar?"
        ),
    }
    return responses.get(intencion, responses["consulta_general"])

def _respuesta_desde_base_conocimiento(datos_sistema: dict | None) -> str | None:
    """Devuelve la respuesta más relevante de la base de conocimiento, si existe."""
    if not datos_sistema:
        return None
    entradas = datos_sistema.get("base_conocimiento") or []
    if not entradas:
        return None
    # _build_system_context ya filtró por categoría relevante a la intención;
    # se usa la primera entrada disponible como respuesta basada en datos reales.
    respuesta = entradas[0].get("respuesta")
    return respuesta or None
