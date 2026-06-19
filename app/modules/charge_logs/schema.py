from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChargeLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    observation_number: int = Field(serialization_alias="numero_observacion")
    started_at: datetime = Field(serialization_alias="timestamp_inicio")
    finished_at: datetime = Field(serialization_alias="timestamp_fin")
    user: str | None = Field(default=None, serialization_alias="usuario")
    response_time_ms: int = Field(serialization_alias="tiempo_respuesta_ms")
    result: str = Field(serialization_alias="resultado")
    modality: str = Field(serialization_alias="modalidad")
    created_at: datetime = Field(serialization_alias="fecha_creacion")
