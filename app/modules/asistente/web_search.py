"""Recojo externo: ubicar sedes de agencias con caché en BD + búsqueda web.

La primera consulta por agencia se busca en internet y se guarda; las siguientes
con la misma clave se responden al instante desde la caché.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.business_time import business_now
from app.integrations import llm
from app.integrations import web_search_service
from app.modules.asistente import repository
from app.modules.asistente.text_utils import norm_simple

logger = logging.getLogger(__name__)

# Agencias de transporte/courier conocidas (para agrupar la caché por agencia,
# de modo que "sedes de shalom" y "en shalom recógelo" reusen el mismo resultado).
AGENCIAS_CONOCIDAS = (
    "shalom", "olva", "marvisur", "cruz del sur", "oltursa", "civa",
    "emtrafesa", "ittsa", "flores", "tepsa", "cromotex", "beltran",
    "movil tours", "moderno", "ave fenix", "sullana",
)

# Días que se considera vigente un resultado de búsqueda guardado en caché.
CACHE_SEDES_DIAS = 30


def respuesta_inicio_recojo_externo() -> str:
    return (
        "Para solicitar un **recojo externo** primero necesito cotizar la encomienda.\n\n"
        "Indícame estos datos:\n"
        "• **Agencia** donde debemos recogerla (por ejemplo, **Shalom** u **OLVA**)\n"
        "• **Contenido** (qué se va a recoger)\n"
        "• **Peso** aproximado en kg\n"
        "• **Dimensiones** del paquete (largo × ancho × alto en cm)\n"
        "• **Nivel de fragilidad**\n\n"
        "Con eso te doy una cotización. Si la aceptas, luego te pediré los datos de recepción.\n\n"
        "Comencemos: **¿en qué agencia debemos recoger tu paquete?** "
        "Dime el nombre (por ejemplo, **Shalom** u **OLVA**) y te muestro sus sedes disponibles en Trujillo."
    )


def es_consulta_sedes_agencia(mensaje: str) -> bool:
    """Detecta si el cliente menciona una agencia o pregunta por sus sedes."""
    msg = norm_simple(mensaje)
    if any(a in msg for a in AGENCIAS_CONOCIDAS):
        return True
    marcadores = (
        "sede", "sedes", "sucursal", "sucursales", "agencias",
        "cuantas", "cuantos", "donde queda", "donde esta", "donde estan",
        "ubicacion", "ubicada", "direccion de", "que agencias", "en trujillo",
    )
    return any(m in msg for m in marcadores)


def _clave_busqueda_sedes(mensaje: str) -> str:
    """Clave de caché: por agencia si se reconoce, si no por el mensaje normalizado."""
    msg = norm_simple(mensaje)
    agencia = next((a for a in AGENCIAS_CONOCIDAS if a in msg), None)
    base = agencia if agencia else " ".join(msg.split())
    return ("sedes:" + base)[:120]


def _cache_vigente(entry) -> bool:
    if not entry or not entry.respuesta:
        return False
    referencia = entry.updated_at or entry.created_at
    if referencia is None:
        return True
    try:
        return (business_now() - referencia).days < CACHE_SEDES_DIAS
    except (TypeError, ValueError):
        return True


def _guardar_cache(db: Session, clave: str, consulta_original: str, respuesta: str, resultados: list[dict]) -> None:
    try:
        repository.upsert_cache_web(
            db,
            clave=clave,
            consulta_original=(consulta_original or "")[:500],
            respuesta=respuesta,
            resultados_json=json.dumps(resultados, ensure_ascii=False)[:8000],
        )
    except Exception as exc:
        db.rollback()
        logger.warning("No se pudo guardar la caché de búsqueda web: %s", exc)


def _resumir_resultados(mensaje: str, resultados: list[dict]) -> str | None:
    """Resume los resultados con el LLM (solo con lo encontrado) o los lista."""
    contexto = "\n".join(
        f"- {r.get('titulo', '')}: {r.get('snippet', '')} ({r.get('link', '')})"
        for r in resultados if r.get("titulo")
    )
    if not contexto.strip():
        return None

    cierre = "\n\nCuando tengas la **sede o dirección exacta** del recojo, indícamela para continuar."

    if llm._llm_enabled():
        prompt = (
            "El cliente pregunta por las sedes/sucursales de una agencia de transporte en Trujillo (Perú). "
            "Resume de forma breve y clara, EN ESPAÑOL, usando ÚNICAMENTE los resultados de búsqueda dados. "
            "No inventes direcciones ni datos que no estén en los resultados. Si no hay suficiente información, "
            "dilo y pide la dirección exacta. Máximo 5 líneas.\n\n"
            f"Consulta del cliente: {mensaje}\n\n"
            f"Resultados de búsqueda:\n{contexto}"
        )
        try:
            resumen = llm._call_llm(prompt).strip()
            if resumen:
                return f"{resumen}{cierre}"
        except Exception as exc:
            logger.warning("No se pudo resumir la búsqueda de sedes: %s", exc)

    lineas = [
        f"• {r['titulo']}" + (f" — {r['snippet']}" if r.get("snippet") else "")
        for r in resultados if r.get("titulo")
    ][:5]
    if not lineas:
        return None
    return "Esto encontré sobre las sedes:\n\n" + "\n".join(lineas) + cierre


def _responder_consulta_sedes(db: Session, mensaje: str, session_id: str | None = None) -> str | None:
    """Responde sobre sedes de una agencia usando caché en BD o búsqueda web."""
    if not mensaje or not mensaje.strip() or not web_search_service.busqueda_web_disponible():
        return None

    clave = _clave_busqueda_sedes(mensaje)

    entry = repository.get_cache_web(db, clave)
    if _cache_vigente(entry):
        try:
            repository.increment_cache_web(db, entry)
        except Exception:
            db.rollback()
        repository.add_log(
            db,
            etapa="recojo_externo",
            tipo_interaccion="busqueda_web_cache",
            descripcion_interaccion=f"Resultado reusado de caché ({clave})",
            session_id=session_id,
            canal="externo",
            resultado="cache_hit",
        )
        return entry.respuesta

    query = f"{mensaje.strip()} agencias sedes en Trujillo Perú dirección"
    resultados = web_search_service.buscar_web(query, num=6)
    if not resultados:
        return None

    respuesta = _resumir_resultados(mensaje, resultados)
    if not respuesta:
        return None

    _guardar_cache(db, clave, mensaje, respuesta, resultados)
    repository.add_log(
        db,
        etapa="recojo_externo",
        tipo_interaccion="busqueda_web",
        descripcion_interaccion=f"Búsqueda web guardada en caché ({clave})",
        session_id=session_id,
        canal="externo",
        resultado="busqueda_web_guardada",
    )
    return respuesta


def handle_recojo_externo(db: Session, mensaje: str, session_id: str | None = None) -> str:
    """Maneja el recojo externo: consulta de sedes (con caché) o el flujo inicial."""
    if es_consulta_sedes_agencia(mensaje):
        respuesta = _responder_consulta_sedes(db, mensaje, session_id)
        if respuesta:
            return respuesta
        return (
            "Para coordinar el recojo necesito la **dirección exacta** o el nombre de la sede "
            "donde debemos recoger tu paquete. ¿Me la indicas?"
        )
    return respuesta_inicio_recojo_externo()
