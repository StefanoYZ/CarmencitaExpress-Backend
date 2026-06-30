"""Cliente LLM (Groq) y normalización base. La API key vive solo en el backend."""
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


_SYSTEM_PROMPT = """
Eres CarmiBot, asistente de Carmencita Express Cargo (ruta Trujillo–Angasmarca).

DESTINOS VÁLIDOS (sedes en la ruta — NO son direcciones, son puntos de la agencia):
Trujillo, Shorey, Huaycatan, Santiago de Chuco, Chacomas, Cachicadan, Santa Cruz,
Cochapamba, Ugallama, Villacruz, Las Manzanas, Angasmarca, Tambo Pampamarca Alta,
Psicochaca, Santa Clara de Tulpo, La Yeguada, Mollebamba, Cochamarca, Orocullay.

FLUJO DE PRE-REGISTRO POR CHAT:
El cliente proporciona los datos, se genera un código de pre-registro y se acerca a la
agencia para pagar y formalizar. Datos necesarios (pídelos uno por uno si faltan):
1. Destino (una sede de la lista)
2. Nombre completo del remitente
3. DNI del remitente (8 dígitos)
4. Nombre del destinatario
5. Descripción del contenido
6. Peso aproximado en kg

DATOS OPERATIVOS CONOCIDOS:
- Horario de atención: 7:30 a. m. a 6:00 p. m. en la sede principal de Trujillo.
- Sede principal: Av. América Sur 257, Trujillo 13006.
- Para tracking, pide primero el código de seguimiento. Ejemplo: V000000027.
- Si el cliente no tiene código de seguimiento, ofrece buscar sus últimos envíos por DNI.
- Para cotizar, pide: sede de destino, descripción, peso, dimensiones y fragilidad.
- Para recojo externo, primero pide agencia o dirección de recojo, contenido, peso,
  dimensiones y fragilidad. Luego de cotizar, si acepta, pide datos de recepción.

- Metodos de pago aceptados: Yape, tarjeta y efectivo/pago en agencia.

REGLAS DE RESPUESTA:
- Máximo 2-3 oraciones o lista corta de puntos. Sé directo y conciso.
- El destino es siempre una sede de la ruta, NUNCA una dirección exacta.
- No inventes precios ni tarifas. Si no tienes el dato, pide usar el cotizador o deriva a secretaría.
- No confirmes pagos ni entregas no registradas en el sistema.
- Responde siempre en español.
""".strip()

def _llm_enabled() -> bool:
    enabled = bool(settings.assistant_llm_enabled and settings.groq_api_key)
    logger.info("LLM enabled=%s groq=%s", enabled, bool(settings.groq_api_key))
    return enabled

def _normalize(text: str) -> str:
    """Pasa a minúsculas y elimina tildes para comparar de forma robusta."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def _call_llm(prompt: str) -> str:
    """Llama a Groq. Devuelve '' si falla."""
    if settings.groq_api_key:
        try:
            return _call_groq_raw(prompt)
        except Exception as exc:
            logger.error("Groq error (%s): %s — usando fallback", type(exc).__name__, exc)
    return ""

def _call_groq_raw(prompt: str) -> str:
    """Llama a la API de Groq (compatible con OpenAI chat completions)."""
    model = settings.groq_model or "llama-3.1-8b-instant"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.3,
    }
    with httpx.Client(timeout=25) as client:
        resp = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "").strip()
    return ""
