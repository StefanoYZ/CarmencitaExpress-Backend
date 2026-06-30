from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.business_time import business_now, business_today
from app.core.database import Base


class LogEmisionBoleta(Base):
    __tablename__ = "logs_emision_boleta"

    id = Column(Integer, primary_key=True, index=True)
    numero_observacion = Column(Integer, unique=True, index=True, nullable=True)
    usuario = Column(String(150), nullable=True)
    metodo = Column(String(20), default="Sistema", nullable=False)
    actor_origen = Column(String(50), nullable=True, index=True)
    canal = Column(String(20), nullable=True, index=True)
    timestamp_inicio = Column(DateTime(timezone=True), default=business_now, nullable=False)
    timestamp_fin = Column(DateTime(timezone=True), nullable=True)
    tiempo_ms = Column(BigInteger, nullable=True)
    encomienda_id = Column(Integer, ForeignKey("encomiendas.id"), nullable=True, index=True)
    boleta_id = Column(Integer, ForeignKey("boletas_electronicas.id"), nullable=True, index=True)
    pago_id = Column(BigInteger, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )

    encomienda = relationship("Shipment")
    boleta = relationship("ElectronicReceipt")


class LogServicioTransporte(Base):
    __tablename__ = "logs_servicio_transporte"

    id = Column(Integer, primary_key=True, index=True)
    numero_observacion = Column(Integer, unique=True, index=True, nullable=True)
    fecha = Column(Date, default=business_today, nullable=False, index=True)
    metodo = Column(String(20), default="sistema", nullable=False)

    timestamp_inicio_registro = Column(DateTime(timezone=True), nullable=True)
    timestamp_fin_registro = Column(DateTime(timezone=True), nullable=True)
    tiempo_registro_ms = Column(BigInteger, nullable=True)

    timestamp_inicio_carga = Column(DateTime(timezone=True), nullable=True)
    timestamp_fin_carga = Column(DateTime(timezone=True), nullable=True)
    tiempo_carga_ms = Column(BigInteger, nullable=True)

    timestamp_inicio_entrega = Column(DateTime(timezone=True), nullable=True)
    timestamp_fin_entrega = Column(DateTime(timezone=True), nullable=True)
    tiempo_entrega_ms = Column(BigInteger, nullable=True)

    tiempo_total_ms = Column(BigInteger, nullable=True)

    encomienda_id = Column(Integer, ForeignKey("encomiendas.id"), nullable=True, index=True)
    cotizacion_id = Column(Integer, nullable=True, index=True)
    pago_id = Column(BigInteger, nullable=True, index=True)
    despacho_id = Column(Integer, nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True, index=True)
    usuario_correo = Column(String(150), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )

    encomienda = relationship("Shipment")
    usuario = relationship("InternalUser")


class LogCargaPaquete(Base):
    __tablename__ = "logs_carga_paquete"

    id = Column(Integer, primary_key=True, index=True)
    numero_observacion = Column(Integer, nullable=True, index=True)
    fecha = Column(Date, default=business_today, nullable=False, index=True)
    metodo = Column(String(20), default="Sistema", nullable=False)
    orden_carga_id = Column(String(50), nullable=True, index=True)
    encomienda_id = Column(Integer, ForeignKey("encomiendas.id"), nullable=True, index=True)
    numero_paquete = Column(Integer, nullable=False, default=1)
    timestamp_inicio = Column(DateTime(timezone=True), nullable=False)
    timestamp_fin = Column(DateTime(timezone=True), nullable=True)
    tiempo_carga_ms = Column(BigInteger, nullable=True)
    accion_inicio = Column(String(50), default="ordenar", nullable=True)
    accion_fin = Column(String(50), nullable=True)
    usuario_correo = Column(String(150), nullable=True)
    actor_origen = Column(String(50), nullable=True)
    canal = Column(String(20), nullable=True)
    modo_prueba = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )

    encomienda = relationship("Shipment")
