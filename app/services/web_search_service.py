"""Servicio de búsqueda web para el Asistente Virtual.

Se usa, por ejemplo, en el recojo externo para responder consultas como
"¿cuántas sedes tiene OLVA en Trujillo?". La API key vive SOLO en el backend
(nunca llega al navegador). Si no hay key configurada, las funciones devuelven
None de forma elegante y el asistente pide la dirección exacta al cliente.

Provider por defecto: Serper (https://serper.dev) — Google Search API simple.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def busqueda_web_disponible() -> bool:
    """Indica si hay una API key de búsqueda configurada."""
    return bool(settings.search_api_key)


def buscar_web(query: str, *, num: int = 5) -> list[dict] | None:
    """Ejecuta una búsqueda web y devuelve resultados [{titulo, snippet, link}].

    Devuelve None si no hay key configurada o si la búsqueda falla (degradado).
    """
    if not settings.search_api_key or not query.strip():
        return None

    provider = (settings.search_provider or "serper").strip().lower()
    try:
        if provider == "serper":
            return _buscar_serper(query, num=num)
        # Otros providers pueden agregarse aquí (bing, serpapi, etc.).
        logger.warning("Proveedor de búsqueda no soportado: %s", provider)
        return None
    except Exception as exc:
        logger.warning("Búsqueda web falló (%s): %s", type(exc).__name__, exc)
        return None


def _buscar_serper(query: str, *, num: int) -> list[dict]:
    headers = {
        "X-API-KEY": settings.search_api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "gl": "pe", "hl": "es", "num": num}
    with httpx.Client(timeout=12.0) as client:
        response = client.post(settings.search_api_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    resultados: list[dict] = []

    # "places" suele traer sucursales con dirección cuando es una consulta local.
    for place in (data.get("places") or [])[:num]:
        resultados.append({
            "titulo": place.get("title", ""),
            "snippet": place.get("address", ""),
            "link": place.get("website") or place.get("cid", ""),
        })

    # Resultados orgánicos como complemento/respaldo.
    for item in (data.get("organic") or [])[: max(0, num - len(resultados))]:
        resultados.append({
            "titulo": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "link": item.get("link", ""),
        })

    return resultados
