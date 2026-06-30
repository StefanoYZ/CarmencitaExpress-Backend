"""Validación de coherencia del paquete (reglas + LLM)."""
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


_CONTENIDO_VOCAB: dict[str, set[str]] = {
    # Nota: "saco/sacos" se omite a propósito porque en la ruta rural casi siempre
    # significa un saco de producto (saco de papas/arroz), no una prenda.
    "ROPA": {
        "ropa", "ropas", "polo", "polos", "camisa", "camisas", "pantalon", "pantalones",
        "vestido", "vestidos", "casaca", "casacas", "chompa", "chompas", "zapato", "zapatos",
        "calzado", "zapatilla", "zapatillas", "medias", "prenda", "prendas", "abrigo", "abrigos",
        "jean", "jeans", "short", "shorts", "falda", "faldas", "blusa", "blusas", "tela", "telas",
        "buzo", "buzos", "casimir", "terno", "ternos", "gorro", "gorros",
    },
    "ALIMENTOS": {
        "papa", "papas", "arroz", "azucar", "harina", "fruta", "frutas", "verdura", "verduras",
        "comida", "alimento", "alimentos", "grano", "granos", "menestra", "menestras",
        "conserva", "conservas", "fideo", "fideos", "aceite", "cereal", "cereales", "cafe",
        "cacao", "quinua", "maiz", "trigo", "pan", "queso", "huevo", "huevos", "leche",
        "galleta", "galletas", "chocolate", "miel", "snack", "snacks",
    },
    "ELECTRONICOS": {
        "televisor", "tele", "tv", "laptop", "computadora", "pc", "celular", "telefono",
        "radio", "parlante", "parlantes", "equipo", "monitor", "tablet", "camara",
        "consola", "electronico", "electronicos", "audifono", "audifonos",
        "cargador", "impresora", "router", "mouse", "teclado",
    },
    "ELECTRODOMESTICOS": {
        "refrigeradora", "refrigerador", "refri", "congeladora", "congelador", "frigobar",
        "cocina", "cocinas", "horno", "hornos", "microondas", "licuadora", "licuadoras",
        "lavadora", "lavadoras", "secadora", "secadoras", "aspiradora", "plancha", "planchas",
        "ventilador", "ventiladores", "batidora", "tostadora", "hervidor", "extractor",
        "campana", "terma", "calentador", "freidora", "olla", "arrocera",
        "electrodomestico", "electrodomesticos",
    },
    "DOCUMENTOS": {
        "documento", "documentos", "papel", "papeles", "carta", "cartas", "sobre", "sobres",
        "contrato", "contratos", "expediente", "expedientes", "factura", "facturas",
        "libro", "libros", "cuaderno", "cuadernos", "folder", "folders", "boleta", "boletas",
    },
}

_TIPO_DISPLAY = {
    "ROPA": "Ropa",
    "ALIMENTOS": "Alimentos",
    "ELECTRONICOS": "Electrónicos",
    "ELECTRODOMESTICOS": "Electrodomésticos",
    "DOCUMENTOS": "Documentos",
    "OTROS": "Otros",
}

_CATEGORIAS_COMPATIBLES: list[set[str]] = [
    {"ELECTRONICOS", "ELECTRODOMESTICOS"},
]

def _categorias_compatibles(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in grupo and b in grupo for grupo in _CATEGORIAS_COMPATIBLES)

_VOCAB_TODO: set[str] = set().union(*_CONTENIDO_VOCAB.values())

# Vocales (el texto ya viene sin tildes desde _normalize).
_VOCALES = set("aeiou")

# Siglas/abreviaturas reales sin vocales que NO deben marcarse como sin sentido.
_SIGLAS_VALIDAS = {"dvd", "ssd", "gps", "sms", "pdf", "cctv", "hdmi", "kit"}

# Secuencias típicas de "teclazos" (filas del teclado QWERTY).
_SECUENCIAS_TECLADO = {
    "asd", "asdf", "asdfg", "asdfgh", "sdf", "dfg", "fgh", "ghj", "hjk", "jkl",
    "qwe", "qwer", "qwert", "qwerty", "wer", "ert", "rty", "tyu", "yui", "uio", "iop",
    "zxc", "zxcv", "zxcvb", "xcv", "cvb", "vbn", "bnm",
    "qaz", "wsx", "edc", "rfv", "tgb", "yhn", "ujm",
}

_CONSONANTES_SEGUIDAS_RE = re.compile(r"[bcdfghjklmnpqrstvwxyzñ]{5,}")

_PESO_MAX_KG = 2000.0

_DIMENSION_MAX_CM = 500.0

_BASE_DIM_VERTICAL = {
    "LARGO_ANCHO": "alto",
    "LARGO_ALTO": "ancho",
    "ANCHO_ALTO": "largo",
}

def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None

def _fmt_num(n: float) -> str:
    """Formatea un número de forma legible, sin notación científica."""
    if n == int(n):
        return f"{int(n):,}".replace(",", " ")
    return f"{n:g}"

def _sugerir_typo(token: str) -> str | None:
    """Sugiere una palabra del vocabulario si el token parece un error de tipeo."""
    cercanas = difflib.get_close_matches(token, _VOCAB_TODO, n=1, cutoff=0.84)
    if cercanas and cercanas[0] != token:
        return cercanas[0]
    # Transposición/anagrama de la misma longitud (típico: "roap" → "ropa")
    token_ordenado = "".join(sorted(token))
    for palabra in _VOCAB_TODO:
        if len(palabra) == len(token) and palabra != token and "".join(sorted(palabra)) == token_ordenado:
            return palabra
    return None

def _categoria_de_descripcion(tokens: list[str]) -> str | None:
    """Devuelve la categoría con más coincidencias exactas en los tokens, o None."""
    puntajes: dict[str, int] = {}
    for cat, vocab in _CONTENIDO_VOCAB.items():
        hits = sum(1 for t in tokens if t in vocab)
        if hits:
            puntajes[cat] = hits
    if not puntajes:
        return None
    return max(puntajes, key=puntajes.get)

def _validar_orientacion_base(
    tipo: str,
    fragilidad: str | None,
    orientacion_base: str | None,
    largo_cm: Any,
    ancho_cm: Any,
    alto_cm: Any,
) -> dict | None:
    """Advierte si un objeto que debe ir parado quedaría acostado por la cara elegida."""
    orient = (orientacion_base or "").strip().upper()
    frag = (fragilidad or "").strip().upper()
    if orient not in _BASE_DIM_VERTICAL:
        return None

    # ¿Debe viajar parado? Electrodomésticos o contenido muy frágil.
    debe_ir_parado = tipo == "ELECTRODOMESTICOS" or frag == "ALTA"
    if not debe_ir_parado:
        return None

    dims = {
        "largo": _to_float(largo_cm),
        "ancho": _to_float(ancho_cm),
        "alto": _to_float(alto_cm),
    }
    if any(v is None or v <= 0 for v in dims.values()):
        return None

    altura_apoyado = dims[_BASE_DIM_VERTICAL[orient]]
    dimension_mas_larga = max(dims.values())
    # Si la dimensión más larga queda horizontal (>30% mayor que la altura al apoyar),
    # el paquete viajaría acostado.
    if dimension_mas_larga > altura_apoyado * 1.3:
        return {
            "campo": "orientacion_base",
            "mensaje": (
                "Con la cara seleccionada, el paquete viajaría **acostado**. "
                "Un electrodoméstico o un objeto muy frágil debería viajar **parado** "
                "(apoyado sobre su cara más pequeña). Revisa la cara elegida."
            ),
        }
    return None

def validar_coherencia_paquete(
    *,
    tipo_contenido: str | None,
    descripcion: str | None,
    peso_kg: Any = None,
    largo_cm: Any = None,
    ancho_cm: Any = None,
    alto_cm: Any = None,
    fragilidad: str | None = None,
    orientacion_base: str | None = None,
) -> list[dict]:
    """Revisa que los datos del paquete sean coherentes y advierte posibles errores.

    - Valores numéricos (peso/dimensiones) y orientación: chequeo determinista (objetivo).
    - Ortografía de la descripción: chequeo determinista conservador (nunca marca
      mayúsculas ni tildes, para no molestar al cliente).
    - Coherencia tipo↔descripción: la evalúa el LLM (más flexible); si no está
      disponible, cae a una verificación determinista por vocabulario.

    Devuelve una lista de advertencias con la forma
    ``{"campo": <nombre_campo>, "mensaje": <texto>}`` (vacía si todo está bien).
    El ``campo`` permite al frontend ubicar la campanita junto al dato sospechoso.
    """
    advertencias: list[dict] = []
    desc = (descripcion or "").strip()
    tipo = (tipo_contenido or "").strip().upper()

    # 1. Valores numéricos inválidos o fuera de rango (0, negativos, o un cero de más)
    peso = _to_float(peso_kg)
    if peso is not None and peso <= 0:
        advertencias.append({
            "campo": "peso_kg",
            "mensaje": "El peso debe ser mayor a 0 kg. Ingresa el peso real del paquete.",
        })
    elif peso is not None and peso > _PESO_MAX_KG:
        advertencias.append({
            "campo": "peso_kg",
            "mensaje": (
                f"El peso ingresado ({_fmt_num(peso)} kg) parece demasiado alto para una encomienda. "
                "Revisa que no haya un cero de más."
            ),
        })
    for nombre, valor, campo in (
        ("largo", largo_cm, "largo_cm"),
        ("ancho", ancho_cm, "ancho_cm"),
        ("alto", alto_cm, "alto_cm"),
    ):
        d = _to_float(valor)
        if d is None:
            continue
        if d <= 0:
            advertencias.append({
                "campo": campo,
                "mensaje": f"La medida de {nombre} debe ser mayor a 0 cm.",
            })
        elif d > _DIMENSION_MAX_CM:
            advertencias.append({
                "campo": campo,
                "mensaje": (
                    f"La medida de {nombre} ({_fmt_num(d)} cm) supera los 5 metros, lo cual es inusual. "
                    "Verifica que esté en centímetros y sin un cero de más."
                ),
            })

    # 1b. Cara/base elegida: objetos que deben ir parados (electrodomésticos o muy
    #     frágiles) no deberían quedar acostados según la cara seleccionada.
    advertencia_base = _validar_orientacion_base(
        tipo, fragilidad, orientacion_base, largo_cm, ancho_cm, alto_cm
    )
    if advertencia_base:
        advertencias.append(advertencia_base)

    # 2. Descripción (requiere texto):
    #    - Ortografía SIEMPRE determinista (no marca mayúsculas/tildes).
    #    - Coherencia tipo↔descripción por LLM (flexible) o determinista de respaldo.
    if desc:
        sin_sentido = _descripcion_sin_sentido(desc)
        if sin_sentido:
            # Si la descripción es galimatías/solo números, no tiene sentido revisar
            # ortografía ni coherencia tipo↔descripción: basta con pedir una real.
            advertencias.append(sin_sentido)
        else:
            advertencias.extend(_typo_deterministico(desc))
            advertencias_tipo = _coherencia_tipo_deterministica(tipo, desc)
            if advertencias_tipo:
                advertencias.extend(advertencias_tipo)
            elif _llm_enabled():
                advertencias.extend(_coherencia_tipo_llm(tipo, desc))
            else:
                advertencias.extend(advertencias_tipo)

    return advertencias[:6]

def _token_sin_sentido(token: str) -> bool:
    """Heurística conservadora: ¿este token parece un "teclazo"/galimatías y no una palabra?"""
    if token in _VOCAB_TODO or token in _SIGLAS_VALIDAS:
        return False
    n = len(token)
    vocales = sum(1 for c in token if c in _VOCALES)
    # 1. Sin ninguna vocal (p. ej. "hjkl", "sdf").
    if vocales == 0:
        return True
    # 2. Secuencia de teclado conocida ("asd", "qwerty").
    if token in _SECUENCIAS_TECLADO:
        return True
    # 3. Bloque repetido: una misma letra ("aaaa") o un patrón repetido en tokens
    #    largos ("asdasd", "asdasdasd", "lalala").
    for p in range(1, n // 2 + 1):
        if n % p == 0:
            reps = n // p
            if token[:p] * reps == token and (p == 1 or n >= 6):
                return True
    # 4. Demasiadas consonantes seguidas para una palabra real.
    if _CONSONANTES_SEGUIDAS_RE.search(token):
        return True
    # 5. Proporción de vocales demasiado baja.
    if vocales / n < 0.22:
        return True
    return False


def _descripcion_sin_sentido(desc: str) -> dict | None:
    """Advierte si la descripción no describe un contenido real (solo números/símbolos
    o puros teclazos/galimatías). Determinista: funciona sin LLM."""
    norm = _normalize(desc)
    if not re.search(r"[a-zñ]", norm):
        return {
            "campo": "descripcion",
            "mensaje": (
                "La descripción no puede ser solo números o símbolos. Describe brevemente "
                "el contenido del paquete (por ejemplo: «ropa», «documentos», «repuestos»)."
            ),
        }
    tokens = [t for t in re.findall(r"[a-zñ]+", norm) if len(t) >= 3]
    if not tokens:
        return {
            "campo": "descripcion",
            "mensaje": (
                "La descripción es muy corta o poco clara. Escribe en palabras qué contiene "
                "el paquete (por ejemplo: «ropa», «documentos»)."
            ),
        }
    if all(_token_sin_sentido(t) for t in tokens):
        return {
            "campo": "descripcion",
            "mensaje": (
                "La descripción no parece describir un contenido real. Escribe en palabras "
                "qué contiene el paquete (por ejemplo: «ropa», «documentos», «artículos de cocina»)."
            ),
        }
    return None


def _typo_deterministico(desc: str) -> list[dict]:
    """Detecta un error de tipeo claro en la descripción (conservador, sin mayúsculas/tildes).

    Solo busca tipeos cuando NO se reconoce ningún artículo del vocabulario, para no
    marcar falsos positivos en palabras comunes ("litros", "nuevo") ni en mayúsculas.
    """
    tokens = [t for t in re.findall(r"[a-záéíóúüñ]+", _normalize(desc)) if len(t) >= 3]
    if _categoria_de_descripcion(tokens) is not None:
        return []
    for token in tokens:
        if token in _VOCAB_TODO or len(token) < 4:
            continue
        sugerencia = _sugerir_typo(token)
        if sugerencia:
            return [{
                "campo": "descripcion",
                "mensaje": (
                    f"Escribiste «{token}» en la descripción. "
                    f"¿Quisiste decir «{sugerencia}»? Revisa la ortografía."
                ),
            }]
    return []

def _coherencia_tipo_deterministica(tipo: str, desc: str) -> list[dict]:
    """Fallback sin LLM: incoherencia tipo↔descripción por vocabulario."""
    tokens = [t for t in re.findall(r"[a-záéíóúüñ]+", _normalize(desc)) if len(t) >= 3]
    categoria_desc = _categoria_de_descripcion(tokens)
    if categoria_desc and tipo in _CONTENIDO_VOCAB and not _categorias_compatibles(categoria_desc, tipo):
        return [{
            "campo": "tipo_contenido",
            "mensaje": (
                f"Seleccionaste tipo de contenido **{_TIPO_DISPLAY.get(tipo, tipo)}**, "
                f"pero la descripción («{desc}») parece corresponder a "
                f"**{_TIPO_DISPLAY.get(categoria_desc, categoria_desc)}**. "
                "Verifica que el tipo de contenido sea el correcto."
            ),
        }]
    return []

def _coherencia_tipo_llm(tipo: str, descripcion: str) -> list[dict]:
    """El LLM evalúa SOLO la coherencia tipo↔descripción (la ortografía es determinista).

    Devuelve ``[{"campo": "tipo_contenido", "mensaje"}]`` o lista vacía.
    """
    tipo_legible = _TIPO_DISPLAY.get(tipo, tipo or "(no seleccionado)")
    prompt = (
        "Eres un validador de un formulario de encomiendas (ruta Trujillo–Angasmarca). "
        "Revisa ÚNICAMENTE si la DESCRIPCIÓN del paquete NO corresponde para nada al "
        "TIPO DE CONTENIDO seleccionado (incoherencia evidente).\n\n"
        "Tipos posibles: Documentos, Ropa, Electrónicos, Electrodomésticos, Alimentos, Otros.\n"
        "Ejemplo de incoherencia: tipo «Ropa» pero la descripción es «saco de papas».\n\n"
        "Reglas (muy importante, para NO molestar al cliente):\n"
        "- Sé MUY conservador: ante cualquier duda razonable, NO generes advertencia.\n"
        "- NO revises ortografía, gramática, artículos, tildes, mayúsculas ni redacción.\n"
        "- Electrónicos y Electrodomésticos son intercambiables (refrigeradora, cocina, "
        "licuadora, televisor, laptop, etc. valen en cualquiera de los dos).\n"
        "- El tipo «Otros» acepta cualquier descripción: NUNCA marques incoherencia con «Otros».\n"
        "- Descripciones genéricas o breves («varios», «encomienda», «regalo», «cosas») están BIEN.\n"
        "- No exijas que la descripción mencione el tipo. No comentes peso/tamaño/precio.\n\n"
        "Responde EXCLUSIVAMENTE un JSON válido:\n"
        '{"incoherente": true|false, "mensaje": "texto breve en español o vacío"}\n'
        "Si corresponde o hay duda, incoherente=false.\n\n"
        f"TIPO DE CONTENIDO: {tipo_legible}\n"
        f"DESCRIPCIÓN: {descripcion}"
    )
    try:
        raw = _call_llm(prompt).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            # LLM no disponible o respuesta no parseable → fallback determinista.
            return _coherencia_tipo_deterministica(tipo, descripcion)
        data = json.loads(match.group(0))
        if data.get("incoherente") is True:
            mensaje = str(data.get("mensaje") or "").strip()
            return [{"campo": "tipo_contenido", "mensaje": mensaje or (
                "La descripción no corresponde al tipo de contenido seleccionado. "
                "Verifica que el tipo sea el correcto."
            )}]
        return []
    except Exception as exc:
        logger.warning("Validación de coherencia con LLM falló: %s", exc)
        return _coherencia_tipo_deterministica(tipo, descripcion)
