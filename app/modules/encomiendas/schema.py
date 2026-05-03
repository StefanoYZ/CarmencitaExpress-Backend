from pydantic import BaseModel, field_validator


FRAGILIDAD_VALORES = {"BAJA", "MEDIA", "ALTA"}


class EncomiendaCreate(BaseModel):
    remitente_tipo_documento: str
    remitente_numero_documento: str
    remitente_nombre: str
    remitente_direccion: str | None = None
    remitente_telefono: str | None = None

    destinatario_tipo_documento: str | None = None
    destinatario_numero_documento: str | None = None
    destinatario_nombre: str
    destinatario_direccion: str | None = None
    destinatario_telefono: str | None = None

    origen: str = "Trujillo"
    destino: str
    descripcion: str
    peso_kg: float
    largo_cm: float
    ancho_cm: float
    alto_cm: float
    fragilidad: str

    @field_validator("remitente_numero_documento", "remitente_nombre", "destinatario_nombre")
    @classmethod
    def texto_requerido(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("El campo no puede estar vacio")
        return value.strip()

    @field_validator("origen", "destino")
    @classmethod
    def normalizar_ruta(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("origen y destino no pueden estar vacios")
        return value.strip()

    @field_validator("peso_kg", "largo_cm", "ancho_cm", "alto_cm")
    @classmethod
    def medidas_mayores_a_cero(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("peso_kg, largo_cm, ancho_cm y alto_cm deben ser mayores a 0")
        return value

    @field_validator("fragilidad")
    @classmethod
    def normalizar_fragilidad(cls, value: str) -> str:
        fragilidad = value.strip().upper() if value else ""
        if fragilidad not in FRAGILIDAD_VALORES:
            raise ValueError("fragilidad debe ser BAJA, MEDIA o ALTA")
        return fragilidad


class EncomiendaResponse(BaseModel):
    id: int
    codigo_encomienda: str

    remitente_tipo_documento: str
    remitente_numero_documento: str
    remitente_nombre: str
    remitente_direccion: str | None = None
    remitente_telefono: str | None = None

    destinatario_tipo_documento: str | None = None
    destinatario_numero_documento: str | None = None
    destinatario_nombre: str
    destinatario_direccion: str | None = None
    destinatario_telefono: str | None = None

    origen: str
    destino: str
    descripcion: str
    peso_kg: float
    largo_cm: float
    ancho_cm: float
    alto_cm: float
    fragilidad: str
    estado: str
