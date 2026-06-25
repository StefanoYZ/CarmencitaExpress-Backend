from datetime import date, datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class LogIdentityPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    encomienda_id: int | None = None
    boleta_id: int | None = None
    pago_id: int | None = None
    cotizacion_id: int | None = None
    despacho_id: int | None = None
    usuario_id: int | None = None
    usuario_correo: str | None = Field(
        default=None,
        validation_alias=AliasChoices("usuario_correo", "usuario", "email"),
    )
    actor_origen: str | None = None
    canal: str | None = None
    timestamp: datetime | None = None

    @field_validator("usuario_correo")
    @classmethod
    def normalize_user(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class LogBoletaStartRequest(LogIdentityPayload):
    pass


class LogBoletaFinishRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    timestamp_fin: datetime | None = None


class LogBoletaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    numero_observacion: int | None
    usuario: str | None
    metodo: str
    actor_origen: str | None = None
    canal: str | None = None
    timestamp_inicio: datetime
    timestamp_fin: datetime | None
    tiempo_ms: int | None
    encomienda_id: int | None
    boleta_id: int | None
    pago_id: int | None
    created_at: datetime
    updated_at: datetime


class LogBoletaReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero_observacion: int | None
    usuario: str | None
    metodo: str
    actor_origen: str | None = None
    canal: str | None = None
    timestamp_inicio: datetime
    timestamp_fin: datetime | None
    tiempo_ms: int | None


class LogServicioStartRequest(LogIdentityPayload):
    pass


class LogServicioFinishRequest(LogIdentityPayload):
    timestamp_fin: datetime | None = None


class LogServicioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    numero_observacion: int | None
    fecha: date
    metodo: str
    timestamp_inicio_registro: datetime | None
    timestamp_fin_registro: datetime | None
    tiempo_registro_ms: int | None
    timestamp_inicio_carga: datetime | None
    timestamp_fin_carga: datetime | None
    tiempo_carga_ms: int | None
    timestamp_inicio_entrega: datetime | None
    timestamp_fin_entrega: datetime | None
    tiempo_entrega_ms: int | None
    tiempo_total_ms: int | None
    encomienda_id: int | None
    cotizacion_id: int | None
    pago_id: int | None
    despacho_id: int | None
    usuario_id: int | None
    usuario_correo: str | None
    created_at: datetime
    updated_at: datetime


class LogServicioReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero_observacion: int | None
    fecha: date
    metodo: str
    timestamp_inicio_registro: datetime | None
    timestamp_fin_registro: datetime | None
    tiempo_registro_ms: int | None
    timestamp_inicio_carga: datetime | None
    timestamp_fin_carga: datetime | None
    tiempo_carga_ms: int | None
    timestamp_inicio_entrega: datetime | None
    timestamp_fin_entrega: datetime | None
    tiempo_entrega_ms: int | None
    tiempo_total_ms: int | None


# ── LogCargaPaquete ───────────────────────────────────────────────────────────

class IniciarOrdenCargaRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    orden_carga_id: str | None = None
    encomienda_ids: list[int]
    usuario_correo: str | None = None
    actor_origen: str | None = "interno"
    canal: str | None = "interno"
    modo_prueba: bool = True
    timestamp: datetime | None = None


class FinalizarPaqueteCargaRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp_fin: datetime | None = None
    accion_fin: str = "siguiente_simulado"


class LogCargaPaqueteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_observacion: int | None
    fecha: date
    metodo: str
    orden_carga_id: str | None
    encomienda_id: int | None
    numero_paquete: int
    timestamp_inicio: datetime
    timestamp_fin: datetime | None
    tiempo_carga_ms: int | None
    accion_inicio: str | None
    accion_fin: str | None
    usuario_correo: str | None
    actor_origen: str | None
    canal: str | None
    modo_prueba: bool
    created_at: datetime
    updated_at: datetime


class LogCargaPaqueteReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero_observacion: int | None
    fecha: date
    metodo: str
    orden_carga_id: str | None
    encomienda_id: int | None
    numero_paquete: int
    timestamp_inicio: datetime
    timestamp_fin: datetime | None
    tiempo_carga_ms: int | None
    accion_inicio: str | None
    accion_fin: str | None
    usuario_correo: str | None
    actor_origen: str | None
    canal: str | None
    modo_prueba: bool


class OrdenCargaStatusResponse(BaseModel):
    orden_carga_id: str
    total_paquetes: int
    paquetes_cargados: int
    paquetes_pendientes: int
    tiempo_total_ms: int | None
    logs: list[LogCargaPaqueteResponse]
