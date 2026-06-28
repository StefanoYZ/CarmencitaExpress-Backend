"""Servicio de integración con LLM (Groq API) para el Asistente Virtual.

El backend es el único que conoce GROQ_API_KEY.
El frontend nunca recibe la clave.

Flujo:
  React Chat UI → FastAPI endpoint → este servicio → Groq API → respuesta controlada
"""
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

# Destinos válidos normalizados para validación
_DESTINOS_VALIDOS = {
    "trujillo", "shorey", "huaycatan", "santiago de chuco", "chacomas",
    "cachicadan", "santa cruz", "cochapamba", "ugallama", "villacruz",
    "las manzanas", "angasmarca", "tambo pampamarca alta", "psicochaca",
    "santa clara de tulpo", "la yeguada", "mollebamba", "cochamarca", "orocullay",
}

# Mapa para capitalizar correctamente cada destino
_DESTINO_DISPLAY = {
    "trujillo": "Trujillo", "shorey": "Shorey", "huaycatan": "Huaycatan",
    "santiago de chuco": "Santiago de Chuco", "chacomas": "Chacomas",
    "cachicadan": "Cachicadan", "santa cruz": "Santa Cruz",
    "cochapamba": "Cochapamba", "ugallama": "Ugallama", "villacruz": "Villacruz",
    "las manzanas": "Las Manzanas", "angasmarca": "Angasmarca",
    "tambo pampamarca alta": "Tambo Pampamarca Alta", "psicochaca": "Psicochaca",
    "santa clara de tulpo": "Santa Clara de Tulpo", "la yeguada": "La Yeguada",
    "mollebamba": "Mollebamba", "cochamarca": "Cochamarca", "orocullay": "Orocullay",
}


# ── Wizard de pre-registro ────────────────────────────────────────────────────

_INTRO_PREREGISTRO = (
    "Para pre-registrar tu envío necesitaré la siguiente información:\n\n"
    "• DNI del remitente\n"
    "• DNI del destinatario\n"
    "• Sede de destino\n"
    "• Descripción del contenido\n"
    "• Peso (kg)\n"
    "• Dimensiones del paquete (largo × ancho × alto en cm)\n"
    "• Nivel de fragilidad\n\n"
    "Comencemos. Por favor indícame el **DNI del remitente** (8 dígitos):"
)

_PREGUNTAS_CAMPO: dict[str, str] = {
    "remitente_dni": "Por favor indícame el **DNI del remitente** (8 dígitos):",
    "remitente_nombre": (
        "No encontré ese DNI en nuestros registros. "
        "¿Cuál es el **nombre completo del remitente**?"
    ),
    "destinatario_dni": (
        "Ahora el **DNI del destinatario** (8 dígitos).\n"
        "Si no lo tienes disponible, puedes indicar directamente su nombre completo."
    ),
    "destinatario_nombre": (
        "No encontré ese DNI en nuestros registros. "
        "¿Cuál es el **nombre completo del destinatario**?"
    ),
    "remitente_telefono": (
        "No tengo un número de contacto registrado para el remitente.\n"
        "¿Cuál es el **número de celular del remitente**? (9 dígitos, empieza con 9)"
    ),
    "destinatario_telefono": (
        "¿Cuál es el **número de celular del destinatario**? (9 dígitos, empieza con 9)\n"
        "Si no lo tienes, escribe *no tengo* para continuar."
    ),
    "destino": (
        "¿A cuál de nuestras **sedes** quieres enviar el paquete?\n\n"
        "Trujillo · Shorey · Huaycatan · Santiago de Chuco · Chacomas · Cachicadan · "
        "Santa Cruz · Cochapamba · Ugallama · Villacruz · Las Manzanas · Angasmarca · "
        "Tambo Pampamarca Alta · Psicochaca · Santa Clara de Tulpo · "
        "La Yeguada · Mollebamba · Cochamarca · Orocullay"
    ),
    "descripcion": "¿Cuál es el **contenido del paquete**? (Ej: ropa, zapatos, documentos)",
    "peso_kg": "¿Cuál es el **peso aproximado** en kilogramos? (Ej: 2.5)",
    "dimensiones": (
        "¿Cuáles son las **dimensiones** del paquete?\n"
        "Ingresa largo × ancho × alto en cm (Ej: 30x20x15)"
    ),
    "fragilidad": (
        "¿Qué nivel de **fragilidad** tiene el contenido?\n\n"
        "• **BAJA** — Resistente (ropa, calzado, libros)\n"
        "• **MEDIA** — Requiere cuidado (electrodomésticos, instrumentos)\n"
        "• **ALTA** — Muy frágil (vidrio, cerámica, pantallas)"
    ),
}


def siguiente_campo_pendiente(datos: dict) -> str | None:
    """Devuelve el nombre del próximo campo que falta en el wizard. None si todo está completo."""
    if not datos.get("remitente_dni"):
        return "remitente_dni"
    if not datos.get("remitente_nombre"):
        return "remitente_nombre"
    # Celular del remitente: solo si no lo tenemos en la BD de clientes (flag puesto al enriquecer).
    if datos.get("_pedir_remitente_tel") and not datos.get("remitente_telefono"):
        return "remitente_telefono"
    # Destinatario: DNI es opcional; nombre es obligatorio.
    # Si no hay DNI ni nombre, preguntamos DNI (con nota de que es opcional).
    # Si hay DNI pero no nombre (RENIEC falló), preguntamos nombre.
    if not datos.get("destinatario_nombre"):
        if datos.get("destinatario_dni") and not datos.get("destinatario_nombre"):
            return "destinatario_nombre"
        if not datos.get("destinatario_dni"):
            return "destinatario_dni"
    # Celular del destinatario: solo si no lo tenemos registrado.
    if datos.get("_pedir_destinatario_tel") and not datos.get("destinatario_telefono"):
        return "destinatario_telefono"
    destino = datos.get("destino") or ""
    if not (destino and _normalize(destino) in _DESTINOS_VALIDOS):
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


_NOMBRE_PALABRA = re.compile(r"^[a-záéíóúüñA-ZÁÉÍÓÚÜÑ'\-]+$")


def _es_nombre_valido(texto: str) -> bool:
    """Valida que un texto parezca un nombre de persona real (no una frase ni un número).

    Evita que el LLM cuele respuestas como "No hay información sobre el número 1799"
    o que un destino/número se acepte como nombre.
    """
    t = (texto or "").strip().rstrip(".")
    if not t or len(t) >= 80:
        return False
    if any(ch.isdigit() for ch in t):
        return False
    palabras = t.split()
    if not (2 <= len(palabras) <= 6):
        return False
    if not all(_NOMBRE_PALABRA.match(w) for w in palabras):
        return False
    if _normalize(t) in _DESTINOS_VALIDOS:
        return False
    return True


def extraer_campo_wizard(campo: str, mensaje: str) -> Any:
    """Extrae UN campo específico del mensaje del usuario.

    Usa regex/lógica determinista para campos estructurados (DNI, peso, dimensiones,
    destino, fragilidad) y LLM solo para texto libre (nombres, descripción).
    """
    msg_norm = _normalize(mensaje)

    if campo in ("remitente_dni", "destinatario_dni"):
        matches = re.findall(r"\b(\d{8})\b", mensaje)
        return matches[0] if matches else None

    if campo in ("remitente_telefono", "destinatario_telefono"):
        # Celular peruano: 9 dígitos, empieza con 9, no todos iguales.
        for m in re.findall(r"\b(\d{9})\b", mensaje):
            if m.startswith("9") and len(set(m)) > 1:
                return m
        return None

    if campo in ("remitente_nombre", "destinatario_nombre"):
        # Si el mensaje es puramente numérico (ej. un intento de DNI mal escrito),
        # NO es un nombre. Evita que el LLM devuelva basura como nombre.
        if re.fullmatch(r"[\d\s.,-]+", mensaje.strip()):
            return None
        # Intenta con LLM; si no disponible o devuelve null/algo que no parece nombre, usa heurística.
        if _llm_enabled():
            tipo = "remitente" if campo == "remitente_nombre" else "destinatario"
            prompt = (
                f"Del siguiente mensaje, extrae el nombre completo de la persona que es el {tipo}. "
                "Si no se menciona un nombre de persona, responde null. "
                "Responde SOLO el nombre completo o la palabra null, sin explicaciones.\n"
                f"Mensaje: {mensaje}"
            )
            try:
                raw_llm = _call_llm(prompt).strip().rstrip(".")
                if raw_llm.lower() not in ("null", "none", "", "no", "n/a") and _es_nombre_valido(raw_llm):
                    return raw_llm.title()
            except Exception:
                pass
        # Fallback heurístico: quitar prefijos comunes y validar que parezca nombre
        _PREFIJOS_NOMBRE = re.compile(
            r"^(?:me llamo|soy|mi nombre es|el (?:remitente|destinatario) es|"
            r"se llama|el nombre es|nombre)\s*",
            re.IGNORECASE,
        )
        msg_clean = _PREFIJOS_NOMBRE.sub("", mensaje.strip()).strip().rstrip(".")
        if _es_nombre_valido(msg_clean):
            return msg_clean.title()
        return None

    if campo == "descripcion":
        # Intenta con LLM; si no disponible o devuelve null, usa heurística
        if _llm_enabled():
            prompt = (
                "Del siguiente mensaje, extrae la descripción del contenido del paquete. "
                "Si no se menciona contenido, responde null. "
                "Responde SOLO la descripción o la palabra null, sin explicaciones.\n"
                f"Mensaje: {mensaje}"
            )
            try:
                raw = _call_llm(prompt).strip()
                if raw.lower() not in ("null", "none", "", "no"):
                    return raw
            except Exception:
                pass
        # Fallback heurístico: si el mensaje no parece número/dims/destino/fragilidad, usarlo
        _PREFIJOS_DESC = re.compile(
            r"^(?:el (?:contenido|paquete) (?:es|contiene)|contiene|envio|son|es)\s*",
            re.IGNORECASE,
        )
        msg_clean = _PREFIJOS_DESC.sub("", mensaje.strip()).strip().rstrip(".")
        if (
            msg_clean
            and not re.match(r"^\d", msg_clean)
            and not re.match(r"^\d+\s*[xX×]\s*\d+", msg_clean)
            and msg_clean.upper() not in ("BAJA", "MEDIA", "ALTA")
            and _normalize(msg_clean) not in _DESTINOS_VALIDOS
            and 2 < len(msg_clean) < 200
        ):
            return msg_clean
        return None

    if campo == "destino":
        for clave, display in _DESTINO_DISPLAY.items():
            if clave in msg_norm:
                return display
        return None

    if campo == "peso_kg":
        nums = re.findall(r"\b(\d+(?:[.,]\d+)?)\s*(?:kg|kilo|kilogramo)?\b", mensaje, re.IGNORECASE)
        for n in nums:
            try:
                v = float(n.replace(",", "."))
                if 0 < v < 1000:
                    return v
            except ValueError:
                pass
        return None

    if campo == "dimensiones":
        # \b no funciona entre dígitos y 'x' — buscar cualquier secuencia numérica
        nums = re.findall(r"(\d+(?:[.,]\d+)?)", mensaje)
        if len(nums) >= 3:
            try:
                dims = [float(n.replace(",", ".")) for n in nums[:3]]
                if all(0 < d < 500 for d in dims):
                    return {"largo_cm": dims[0], "ancho_cm": dims[1], "alto_cm": dims[2]}
            except ValueError:
                pass
        return None

    if campo == "fragilidad":
        msg_up = mensaje.upper()
        if "ALTA" in msg_up:
            return "ALTA"
        if "MEDIA" in msg_up:
            return "MEDIA"
        if "BAJA" in msg_up:
            return "BAJA"
        if any(w in msg_norm for w in ["vidrio", "ceramica", "pantalla", "fragil", "delicado", "cristal"]):
            return "ALTA"
        if any(w in msg_norm for w in ["electrodomestico", "instrumento", "electronico"]):
            return "MEDIA"
        if any(w in msg_norm for w in ["ropa", "calzado", "zapato", "libro", "papel", "tela"]):
            return "BAJA"
        return None

    return None


def _llm_enabled() -> bool:
    enabled = bool(settings.assistant_llm_enabled and settings.groq_api_key)
    logger.info("LLM enabled=%s groq=%s", enabled, bool(settings.groq_api_key))
    return enabled


# Patrones por intención. Cada patrón tiene un peso: las frases específicas valen
# más (3) que las palabras sueltas/genéricas (2), para evitar que keywords
# ambiguas ("donde", "enviar", "paquete") capturen frases de otra intención.
# Las keywords se escriben SIN tildes porque el mensaje se normaliza antes.
_INTENT_PATTERNS: dict[str, list[tuple[int, list[str]]]] = {
    "recojo_externo": [
        (4, ["recojo externo", "recoja mi paquete", "recojan mi paquete"]),
        (3, ["recojo de", "otra empresa", "otra agencia",
              "llego de", "llego a trujillo", "recoja mi", "recojan", "recogan",
              "que recojan", "que recoja", "llego desde", "viene de otra"]),
        (2, ["recoj", "recog", "pickup"]),
    ],
    "cotizacion": [
        (3, ["cuanto cuesta", "cuanto sale", "cuanto seria", "cuanto me costaria",
              "cuanto cobran", "precio del envio", "precio de envio", "costo del envio",
              "precio de", "costo de", "cuanto es el precio", "me pueden cotizar"]),
        (2, ["cotiz", "precio", "costo", "cuanto", "tarif", "cuesta", "cobran"]),
    ],
    "metodos_pago": [
        (4, ["aceptan yape", "aceptan tarjeta", "aceptan efectivo",
              "pago en efectivo", "pago con tarjeta", "pagar con tarjeta",
              "pagar con yape", "se puede pagar con", "puedo pagar con",
              "formas de pago", "forma de pago", "metodos de pago",
              "metodo de pago", "medios de pago", "medio de pago"]),
        (3, ["yape", "tarjeta", "efectivo", "pago en agencia", "pagar en agencia"]),
    ],
    "tracking": [
        (3, ["estado de mi", "mi paquete", "mi encomienda",
              "donde esta mi", "donde va mi", "rastrear", "rastreo",
              "codigo de encomienda", "codigo de seguimiento", "ya llego mi",
              "cuando llega mi", "llego mi paquete", "llego mi encomienda"]),
        (2, ["track", "seguimiento", "numero de guia"]),
    ],
    "contenido_permitido": [
        (4, ["puedo enviar", "puedo mandar", "puedo llevar", "que puedo enviar",
              "se puede enviar", "esta permitido", "contenido permitido",
              "que contenido", "tipo de contenido", "que tipo de contenido",
              "puedo meter", "puedo incluir"]),
        (3, ["que envio", "que se puede", "que no se puede", "que aceptan",
              "que reciben", "aceptan", "esta prohibido"]),
        (2, ["permitido", "prohibido"]),
    ],
    "documentacion": [
        (3, ["que documento", "que documentos", "que requisito", "que requisitos",
              "documentacion necesaria", "documentos necesito", "que necesito para enviar",
              "que piden", "que me piden"]),
        (2, ["document", "requisito", "dni", "identificacion"]),
    ],
    "horarios": [
        (3, ["a que hora", "que hora", "hora de atencion", "horario de atencion",
              "a que hora abren", "a que hora cierran", "hasta que hora",
              "cuando atienden", "estan abiertos"]),
        (2, ["horario", "atiend", "abren", "cierran", "abierto"]),
    ],
    "sedes": [
        (3, ["donde estan", "donde queda", "donde se ubica", "donde quedan",
              "donde los encuentro", "sus oficinas", "sus sedes", "sus agencias",
              "ubicacion de", "donde estan ubicados", "cual es la direccion",
              "donde puedo ir"]),
        (2, ["sede", "oficina", "agencia", "ubicacion", "sucursal", "direccion de"]),
    ],
    "orientacion_base": [
        (4, ["cara que va abajo", "cara apoyada", "seleccionar la cara", "eleccion de la cara",
              "como elijo la cara", "que cara selecciono", "orientacion del paquete",
              "orientacion de la base", "base del paquete", "geometria del paquete",
              "cara hacia abajo", "como funciona la base"]),
        (3, ["orientacion", "cara abajo", "que cara"]),
    ],
    "pre_registro": [
        # Señal inequívoca: domina sobre cualquier otra intención.
        (5, ["pre-registro", "pre registro", "preregistro", "pre-regist", "preregist"]),
        (4, ["quiero enviar un paquete", "quisiera enviar un paquete",
              "quiero mandar un paquete", "quisiera mandar un paquete",
              "necesito enviar un paquete", "me gustaria enviar",
              "quiero hacer un envio", "quisiera hacer un envio",
              "quiero registrar un envio", "como envio un paquete",
              "quiero enviar algo", "quisiera enviar algo"]),
        (3, ["quiero registrar", "quiero enviar", "quiero mandar", "deseo enviar",
              "necesito enviar", "voy a enviar", "hacer un registro", "registrar mi",
              "registrar una encomienda", "quisiera enviar", "quisiera mandar",
              "me gustaria enviar", "me gustaria mandar", "como hago para enviar",
              "como puedo enviar", "quiero hacer un pre"]),
        (2, ["registrar", "enviar paquete", "mandar paquete"]),
    ],
}

# Orden de desempate cuando dos intenciones obtienen el mismo puntaje
# (de más específica a más genérica).
_INTENT_PRIORITY = [
    "recojo_externo",
    "cotizacion",
    "metodos_pago",
    "tracking",
    "contenido_permitido",
    "documentacion",
    "horarios",
    "sedes",
    "orientacion_base",
    "pre_registro",
]

_INTENTOS_VALIDOS = {
    "recojo_externo",
    "cotizacion",
    "metodos_pago",
    "tracking",
    "contenido_permitido",
    "documentacion",
    "horarios",
    "sedes",
    "orientacion_base",
    "pre_registro",
    "consulta_general",
}


def _normalize(text: str) -> str:
    """Pasa a minúsculas y elimina tildes para comparar de forma robusta."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def detectar_intencion(mensaje: str, contexto: dict | None = None) -> str:
    texto = _normalize(mensaje)

    scores: dict[str, int] = {}
    for intencion, grupos in _INTENT_PATTERNS.items():
        score = 0
        for peso, keywords in grupos:
            if any(kw in texto for kw in keywords):
                score += peso
        if score:
            scores[intencion] = score

    if not scores:
        return "consulta_general"

    mejor = max(scores.values())
    candidatos = [i for i, s in scores.items() if s == mejor]
    if len(candidatos) == 1:
        return candidatos[0]
    # Empate: resolver por prioridad (más específica primero).
    for intencion in _INTENT_PRIORITY:
        if intencion in candidatos:
            return intencion
    return candidatos[0]


def detectar_intencion_llm(mensaje: str, contexto: dict | None = None) -> str | None:
    """Usa el LLM solo como apoyo cuando las reglas no detectan intención clara."""
    if not _llm_enabled():
        return None

    historial = (contexto or {}).get("historial") or []
    historial_texto = ""
    if historial:
        lineas = [
            f"{'Usuario' if h.get('rol') == 'usuario' else 'CarmiBot'}: {h.get('texto', '')}"
            for h in historial[-6:]
        ]
        historial_texto = "\n".join(lineas)

    prompt = (
        "Clasifica la intención del mensaje del cliente de Carmencita Express.\n"
        "Responde SOLO una de estas etiquetas exactas:\n"
        "recojo_externo, cotizacion, metodos_pago, tracking, contenido_permitido, documentacion, "
        "horarios, sedes, pre_registro, consulta_general.\n\n"
        "Criterios:\n"
        "- Si pregunta hora de atención, usa horarios.\n"
        "- Si pregunta ubicación, dirección o agencia, usa sedes.\n"
        "- Si quiere enviar, registrar o mandar algo, usa pre_registro.\n"
        "- Si pregunta precio, costo o tarifa, usa cotizacion.\n"
        "- Si pregunta si aceptan Yape, tarjeta, efectivo o formas de pago, usa metodos_pago.\n"
        "- Si pregunta estado de paquete o seguimiento, usa tracking.\n"
        "- Si no está claro, usa consulta_general.\n\n"
        f"Historial reciente:\n{historial_texto}\n\n"
        f"Mensaje: {mensaje}"
    )
    try:
        raw = _call_llm(prompt).strip().lower()
    except Exception as exc:
        logger.warning("No se pudo clasificar intención con LLM: %s", exc)
        return None
    raw = raw.split()[0].strip("`'\".,:;")
    return raw if raw in _INTENTOS_VALIDOS else None


# ── Validación de coherencia del paquete ──────────────────────────────────────
# Vocabulario por tipo de contenido para detectar incoherencias y errores de
# tipeo en la descripción. NO inventa reglas de negocio: solo advierte al cliente
# cuando lo que escribe no guarda relación con el tipo seleccionado.

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

# Categorías que se consideran intercambiables: no se advierte incoherencia entre
# ellas (p. ej. una refrigeradora puede declararse como electrónico o electrodoméstico).
_CATEGORIAS_COMPATIBLES: list[set[str]] = [
    {"ELECTRONICOS", "ELECTRODOMESTICOS"},
]


def _categorias_compatibles(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in grupo and b in grupo for grupo in _CATEGORIAS_COMPATIBLES)


# Conjunto plano de todas las palabras de vocabulario (para detección de tipeo)
_VOCAB_TODO: set[str] = set().union(*_CONTENIDO_VOCAB.values())

# Límites razonables para una encomienda regional (evita ceros de más)
_PESO_MAX_KG = 2000.0
_DIMENSION_MAX_CM = 500.0

# La "base" (cara apoyada hacia abajo) deja vertical la dimensión que NO aparece
# en su nombre. Sirve para detectar si un objeto que debe ir parado quedaría acostado.
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
        advertencias.extend(_typo_deterministico(desc))
        advertencias_tipo = _coherencia_tipo_deterministica(tipo, desc)
        if advertencias_tipo:
            advertencias.extend(advertencias_tipo)
        elif _llm_enabled():
            advertencias.extend(_coherencia_tipo_llm(tipo, desc))
        else:
            advertencias.extend(advertencias_tipo)

    return advertencias[:6]


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


def extraer_datos_recojo_externo(mensaje: str) -> dict[str, Any]:
    """Extrae datos de una solicitud de recojo externo del mensaje del usuario."""
    if not _llm_enabled():
        return {}
    try:
        prompt = (
            "Extrae del siguiente mensaje los datos de recojo externo en JSON con estas claves exactas: "
            "ciudad_origen, empresa_transporte_origen, agencia_o_direccion_llegada, "
            "codigo_guia_o_tracking, hora_aproximada_llegada, destino_final, "
            "nombre_destinatario_final, telefono_destinatario, tipo_contenido, observaciones.\n"
            "Devuelve SOLO el JSON sin explicaciones. Si algún campo no se menciona, pon null.\n\n"
            f"Mensaje: {mensaje}"
        )
        raw = _call_llm(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as exc:
        logger.warning("Error extrayendo datos de recojo: %s", exc)
    return {}


def extraer_datos_preregistro(mensaje: str, historial: list[dict] | None = None) -> dict[str, Any]:
    """Extrae datos de pre-registro del mensaje actual y del historial de conversación."""
    if not _llm_enabled():
        return {}
    try:
        contexto_historial = ""
        if historial:
            lineas = [
                f"{'Usuario' if h.get('rol') == 'usuario' else 'CarmiBot'}: {h.get('texto', '')}"
                for h in historial[-12:]
            ]
            contexto_historial = "Conversación previa:\n" + "\n".join(lineas) + "\n\n"

        destinos_str = ", ".join(_DESTINO_DISPLAY.values())
        prompt = (
            f"Destinos válidos de Carmencita Express: {destinos_str}.\n"
            "El campo 'destino' debe ser EXACTAMENTE uno de esos destinos (no una dirección).\n"
            "El campo 'fragilidad' debe ser exactamente BAJA, MEDIA o ALTA según el contenido:\n"
            "  BAJA: ropa, calzado, libros, papeles; MEDIA: electrodomésticos, instrumentos;\n"
            "  ALTA: vidrio, cerámica, pantallas, flores.\n\n"
            f"{contexto_historial}"
            "Mensaje actual del usuario:\n"
            f"{mensaje}\n\n"
            "Extrae TODOS los datos de pre-registro acumulados en la conversación. "
            "Devuelve SOLO un JSON con estas claves exactas "
            "(pon null si el dato no aparece en ninguna parte de la conversación):\n"
            "remitente_nombre, remitente_dni, remitente_telefono, "
            "destinatario_nombre, destinatario_dni, destinatario_telefono, "
            "destino, descripcion, peso_kg, "
            "largo_cm, ancho_cm, alto_cm, fragilidad, observaciones.\n"
            "No incluyas explicaciones, solo el JSON."
        )
        raw = _call_llm(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            datos = json.loads(raw[start:end])
            # Normalizar destino
            destino_raw = _normalize((datos.get("destino") or "").strip())
            if destino_raw in _DESTINOS_VALIDOS:
                datos["destino"] = _DESTINO_DISPLAY[destino_raw]
            elif destino_raw:
                datos["destino"] = None
            # Normalizar fragilidad
            frag = (datos.get("fragilidad") or "").strip().upper()
            datos["fragilidad"] = frag if frag in ("BAJA", "MEDIA", "ALTA") else None
            return datos
    except Exception as exc:
        logger.warning("Error extrayendo datos de pre-registro: %s", exc)
    return {}


def datos_preregistro_completos(datos: dict) -> bool:
    """Verifica si hay suficientes datos para crear un pre-registro."""
    return siguiente_campo_pendiente(datos) is None


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
