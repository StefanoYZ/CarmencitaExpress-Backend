from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── LogInteraccionAsistente ───────────────────────────────────────────────────

class LogAsistenteCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metodo: str = "Sistema"
    etapa: str | None = None
    tipo_interaccion: str | None = None
    descripcion_interaccion: str | None = None
    existe_error: bool = False
    ayudo_corregir_prevenir_error: bool = False
    tipo_error: str | None = None
    accion_correctiva_aplicada: str | None = None
    session_id: str | None = None
    cliente_id: int | None = None
    usuario_correo: str | None = None
    actor_origen: str | None = None
    canal: str | None = None
    pre_registro_id: int | None = None
    encomienda_id: int | None = None
    solicitud_recojo_externo_id: int | None = None
    campo_afectado: str | None = None
    valor_ingresado: str | None = None
    valor_corregido: str | None = None
    resultado: str | None = None


class LogAsistenteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: datetime
    metodo: str
    etapa: str | None
    tipo_interaccion: str | None
    descripcion_interaccion: str | None
    existe_error: bool
    ayudo_corregir_prevenir_error: bool
    tipo_error: str | None
    accion_correctiva_aplicada: str | None
    session_id: str | None
    cliente_id: int | None
    usuario_correo: str | None
    actor_origen: str | None
    canal: str | None
    encomienda_id: int | None
    created_at: datetime


class LogAsistenteReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: datetime
    metodo: str
    etapa: str | None
    tipo_interaccion: str | None
    descripcion_interaccion: str | None
    existe_error: bool
    ayudo_corregir_prevenir_error: bool
    tipo_error: str | None
    accion_correctiva_aplicada: str | None


# ── SolicitudRecojoExterno ────────────────────────────────────────────────────

class SolicitudRecojoCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ciudad_origen: str
    empresa_transporte_origen: str
    agencia_o_direccion_llegada: str
    codigo_guia_o_tracking: str | None = None
    hora_aproximada_llegada: str | None = None
    destino_final: str
    nombre_destinatario_final: str
    telefono_destinatario: str | None = None
    tipo_contenido: str | None = None
    observaciones: str | None = None
    usuario_correo: str | None = None
    cliente_id: int | None = None
    session_id: str | None = None


class SolicitudRecojoEstadoUpdate(BaseModel):
    estado: str


class SolicitudRecojoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo_solicitud: str
    cliente_id: int | None
    usuario_correo: str | None
    ciudad_origen: str
    empresa_transporte_origen: str
    agencia_o_direccion_llegada: str
    codigo_guia_o_tracking: str | None
    hora_aproximada_llegada: str | None
    destino_final: str
    nombre_destinatario_final: str
    telefono_destinatario: str | None
    tipo_contenido: str | None
    observaciones: str | None
    estado: str
    pre_registro_id: int | None
    encomienda_id: int | None
    created_at: datetime
    updated_at: datetime


# ── AsistenteBaseConocimiento ─────────────────────────────────────────────────

class BaseConocimientoCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    categoria: str
    pregunta_base: str
    respuesta: str
    activo: bool = True


class BaseConocimientoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categoria: str
    pregunta_base: str
    respuesta: str
    activo: bool
    created_at: datetime
    updated_at: datetime


# ── TiposContenidoTransporte ──────────────────────────────────────────────────

class TipoContenidoCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nombre: str
    categoria: str | None = None
    permitido: bool = True
    requiere_documentacion: bool = False
    documentacion_requerida: str | None = None
    requiere_revision_manual: bool = False
    mensaje_cliente: str | None = None
    activo: bool = True


class TipoContenidoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    categoria: str | None
    permitido: bool
    requiere_documentacion: bool
    documentacion_requerida: str | None
    requiere_revision_manual: bool
    mensaje_cliente: str | None
    activo: bool
    created_at: datetime
    updated_at: datetime


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str | None = None
    mensaje: str
    contexto_actual: dict[str, Any] | None = None
    cliente_id: int | None = None
    usuario_correo: str | None = None
    canal: str = "externo"
    etapa: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    respuesta: str
    intencion_detectada: str | None = None
    requiere_accion: bool = False
    accion_sugerida: str | None = None
    datos_extraidos: dict[str, Any] | None = None
    log_id: int | None = None
