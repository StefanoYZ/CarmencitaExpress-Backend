from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.business_time import business_now, business_today
from app.core.database import Base


class LogInteraccionAsistente(Base):
    __tablename__ = "logs_interaccion_asistente"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime(timezone=True), default=business_now, nullable=False, index=True)
    metodo = Column(String(50), default="Sistema", nullable=False)
    etapa = Column(String(50), nullable=True, index=True)
    tipo_interaccion = Column(String(80), nullable=True, index=True)
    descripcion_interaccion = Column(Text, nullable=True)
    existe_error = Column(Boolean, default=False, nullable=False)
    ayudo_corregir_prevenir_error = Column(Boolean, default=False, nullable=False)
    tipo_error = Column(String(80), nullable=True, index=True)
    accion_correctiva_aplicada = Column(Text, nullable=True)

    session_id = Column(String(100), nullable=True, index=True)
    cliente_id = Column(Integer, nullable=True, index=True)
    usuario_correo = Column(String(150), nullable=True, index=True)
    actor_origen = Column(String(50), nullable=True)
    canal = Column(String(20), nullable=True)
    pre_registro_id = Column(Integer, nullable=True)
    encomienda_id = Column(Integer, nullable=True, index=True)
    solicitud_recojo_externo_id = Column(Integer, nullable=True)
    campo_afectado = Column(String(100), nullable=True)
    valor_ingresado = Column(Text, nullable=True)
    valor_corregido = Column(Text, nullable=True)
    resultado = Column(String(100), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=business_now, nullable=False)

    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )


class SolicitudRecojoExterno(Base):
    __tablename__ = "solicitudes_recojo_externo"

    id = Column(Integer, primary_key=True, index=True)
    codigo_solicitud = Column(String(30), unique=True, nullable=False, index=True)
    cliente_id = Column(Integer, nullable=True, index=True)
    usuario_correo = Column(String(150), nullable=True, index=True)
    ciudad_origen = Column(String(100), nullable=False)
    empresa_transporte_origen = Column(String(150), nullable=False)
    agencia_o_direccion_llegada = Column(String(255), nullable=False)
    codigo_guia_o_tracking = Column(String(100), nullable=True)
    hora_aproximada_llegada = Column(String(50), nullable=True)
    destino_final = Column(String(100), nullable=False)
    nombre_destinatario_final = Column(String(150), nullable=False)
    telefono_destinatario = Column(String(20), nullable=True)
    tipo_contenido = Column(String(100), nullable=True)
    observaciones = Column(Text, nullable=True)
    estado = Column(String(30), default="pendiente", nullable=False, index=True)
    pre_registro_id = Column(Integer, nullable=True)
    encomienda_id = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )


class AsistenteBaseConocimiento(Base):
    __tablename__ = "asistente_base_conocimiento"

    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(80), nullable=False, index=True)
    pregunta_base = Column(Text, nullable=False)
    respuesta = Column(Text, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )


class TiposContenidoTransporte(Base):
    __tablename__ = "tipos_contenido_transporte"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    categoria = Column(String(80), nullable=True)
    permitido = Column(Boolean, default=True, nullable=False)
    requiere_documentacion = Column(Boolean, default=False, nullable=False)
    documentacion_requerida = Column(Text, nullable=True)
    requiere_revision_manual = Column(Boolean, default=False, nullable=False)
    mensaje_cliente = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )
