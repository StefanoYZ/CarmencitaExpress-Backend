"""Detección de intención y extracción de campos del wizard."""
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


_DESTINOS_VALIDOS = {
    "trujillo", "shorey", "huaycatan", "santiago de chuco", "chacomas",
    "cachicadan", "santa cruz", "cochapamba", "ugallama", "villacruz",
    "las manzanas", "angasmarca", "tambo pampamarca alta", "psicochaca",
    "santa clara de tulpo", "la yeguada", "mollebamba", "cochamarca", "orocullay",
}

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

_INTENT_PATTERNS: dict[str, list[tuple[int, list[str]]]] = {
    "recojo_externo": [
        (4, ["recojo externo", "recoja mi paquete", "recojan mi paquete"]),
        (3, ["recojo de", "otra empresa", "otra agencia",
              "llego de", "llego a trujillo", "recoja mi", "recojan", "recogan",
              "que recojan", "que recoja", "llego desde", "viene de otra",
              # Nombres de agencias/couriers: si el cliente menciona una, suele ser
              # para coordinar un recojo externo desde esa agencia.
              "shalom", "olva", "marvisur", "cruz del sur", "oltursa", "civa",
              "emtrafesa", "ittsa", "tepsa", "cromotex", "ave fenix"]),
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
