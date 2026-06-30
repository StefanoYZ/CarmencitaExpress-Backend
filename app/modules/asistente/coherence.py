"""Validación de coherencia de los datos del paquete.

Delega el juicio de coherencia al LLM (en integrations.llm) y registra
cada advertencia como un log independiente para el reporte de errores prevenidos.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.integrations import llm
from app.modules.asistente import repository

# Mapeo de campo del paquete → tipo de error registrado en la tabla de logs.
_TIPO_ERROR_POR_CAMPO = {
    "peso_kg": "valor_numerico_invalido",
    "largo_cm": "valor_numerico_invalido",
    "ancho_cm": "valor_numerico_invalido",
    "alto_cm": "valor_numerico_invalido",
    "descripcion": "descripcion_inconsistente",
    "tipo_contenido": "incoherencia_tipo_contenido",
    "orientacion_base": "orientacion_incorrecta",
}


def validar_coherencia_paquete(db: Session, payload, *, session_id: str | None = None) -> dict:
    """Valida la coherencia de los datos del paquete y registra cada error detectado.

    Cada advertencia se guarda como un log independiente, mapeado a la estructura de
    la tabla de errores (campo_afectado, valor_ingresado, tipo_error, etc.) para que
    el reporte del asistente pueda analizar los errores prevenidos por campo y tipo.
    """
    advertencias = llm.validar_coherencia_paquete(
        tipo_contenido=payload.tipo_contenido,
        descripcion=payload.descripcion,
        peso_kg=payload.peso_kg,
        largo_cm=payload.largo_cm,
        ancho_cm=payload.ancho_cm,
        alto_cm=payload.alto_cm,
        fragilidad=payload.fragilidad,
        orientacion_base=payload.orientacion_base,
    )

    valores_por_campo = {
        "peso_kg": payload.peso_kg,
        "largo_cm": payload.largo_cm,
        "ancho_cm": payload.ancho_cm,
        "alto_cm": payload.alto_cm,
        "descripcion": payload.descripcion,
        "tipo_contenido": payload.tipo_contenido,
        "orientacion_base": payload.orientacion_base,
    }

    for adv in advertencias:
        campo = adv.get("campo")
        valor = valores_por_campo.get(campo)
        repository.add_log(
            db,
            etapa="validacion_coherencia",
            tipo_interaccion="prevencion_error",
            descripcion_interaccion=str(adv.get("mensaje", ""))[:480],
            session_id=session_id,
            canal="externo",
            existe_error=True,
            ayudo_corregir_prevenir_error=True,
            tipo_error=_TIPO_ERROR_POR_CAMPO.get(campo, "incoherencia_datos_paquete"),
            accion_correctiva_aplicada="Se advirtió al cliente sobre un posible error antes de enviar.",
            campo_afectado=campo,
            valor_ingresado=None if valor is None else str(valor)[:255],
            resultado="advertencia_mostrada",
        )

    return {"tiene_advertencias": bool(advertencias), "advertencias": advertencias}
