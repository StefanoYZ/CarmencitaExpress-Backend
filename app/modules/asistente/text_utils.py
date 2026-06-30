"""Utilidades de texto puras del asistente (sin estado ni acceso a datos)."""
from __future__ import annotations

import re
import unicodedata


def norm_simple(texto: str) -> str:
    """Minúsculas sin tildes para comparar de forma robusta."""
    return unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode("ascii")


def extract_dni(mensaje: str) -> str | None:
    match = re.search(r"\b(\d{8})\b", mensaje or "")
    return match.group(1) if match else None


def contiene_numero(mensaje: str) -> bool:
    return bool(re.search(r"\d", mensaje or ""))


def contiene_numero_no_dni(mensaje: str) -> bool:
    """True si el mensaje trae dígitos pero ningún DNI válido de 8 dígitos.

    Sirve para detectar intentos de DNI mal escritos (ej. "1799") y dar una
    validación clara en vez de interpretarlos como nombre.
    """
    texto = mensaje or ""
    if re.search(r"\b\d{8}\b", texto):
        return False
    return bool(re.search(r"\d", texto))


def es_solo_numero(mensaje: str) -> bool:
    """True si el mensaje es esencialmente un número (dígitos y separadores)."""
    texto = (mensaje or "").strip()
    return bool(texto) and re.fullmatch(r"[\d\s.,-]+", texto) is not None
