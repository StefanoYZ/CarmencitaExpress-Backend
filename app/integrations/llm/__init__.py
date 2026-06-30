"""Paquete LLM/NLP del asistente (antes llm_service.py monolítico)."""
from app.integrations.llm.client import (
    _SYSTEM_PROMPT, _llm_enabled, _normalize, _call_llm, _call_groq_raw,
)
from app.integrations.llm.nlp import (
    _DESTINOS_VALIDOS, _DESTINO_DISPLAY, _INTRO_PREREGISTRO, _PREGUNTAS_CAMPO, siguiente_campo_pendiente, _NOMBRE_PALABRA, _es_nombre_valido, extraer_campo_wizard, _INTENT_PATTERNS, _INTENT_PRIORITY, _INTENTOS_VALIDOS, detectar_intencion, detectar_intencion_llm, extraer_datos_recojo_externo, extraer_datos_preregistro, datos_preregistro_completos,
)
from app.integrations.llm.coherence_rules import (
    _CONTENIDO_VOCAB, _TIPO_DISPLAY, _CATEGORIAS_COMPATIBLES, _categorias_compatibles, _VOCAB_TODO, _PESO_MAX_KG, _DIMENSION_MAX_CM, _BASE_DIM_VERTICAL, _to_float, _fmt_num, _sugerir_typo, _categoria_de_descripcion, _validar_orientacion_base, validar_coherencia_paquete, _typo_deterministico, _coherencia_tipo_deterministica, _coherencia_tipo_llm,
)
from app.integrations.llm.responses import (
    generar_respuesta_controlada, _fallback_response, _respuesta_desde_base_conocimiento,
)
