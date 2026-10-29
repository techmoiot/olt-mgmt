import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OnuStatus(str, enum.Enum):
    PENDING = "pending"        # detectada, sin autorizar
    AUTHORIZED = "authorized"  # autorizada y activa
    SUSPENDED = "suspended"    # autorizada pero con servicio suspendido
    DELETED = "deleted"        # eliminada de la OLT


class Olt(Base):
    __tablename__ = "olts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    vendor: Mapped[str] = mapped_column(String(30))  # tplink | zte | vsol | btpon | mock
    model: Mapped[str] = mapped_column(String(60), default="")
    host: Mapped[str] = mapped_column(String(120))
    port: Mapped[int] = mapped_column(Integer, default=22)
    protocol: Mapped[str] = mapped_column(String(10), default="ssh")  # ssh | telnet | snmp
    username: Mapped[str] = mapped_column(String(80), default="")
    # TODO producción: cifrar este campo o moverlo a un gestor de secretos.
    password: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    onus: Mapped[list["Onu"]] = relationship(back_populates="olt", cascade="all, delete-orphan")


class ServiceProfile(Base):
    __tablename__ = "service_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    # Nombres de los perfiles tal como existen configurados en la OLT.
    line_profile: Mapped[str] = mapped_column(String(60))
    service_profile: Mapped[str] = mapped_column(String(60), default="")
    vlan: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200), default="")


class Onu(Base):
    __tablename__ = "onus"
    __table_args__ = (UniqueConstraint("olt_id", "serial", name="uq_olt_serial"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    olt_id: Mapped[int] = mapped_column(ForeignKey("olts.id"))
    serial: Mapped[str] = mapped_column(String(40))  # SN GPON o MAC
    pon_port: Mapped[str] = mapped_column(String(20))  # ej. "0/1" o "1/1/3"
    onu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ID asignado en la OLT
    status: Mapped[OnuStatus] = mapped_column(Enum(OnuStatus), default=OnuStatus.PENDING)
    customer_name: Mapped[str] = mapped_column(String(120), default="")
    customer_ref: Mapped[str] = mapped_column(String(60), default="")  # ID en tu facturación
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("service_profiles.id"), nullable=True)
    rx_power_dbm: Mapped[str] = mapped_column(String(20), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    olt: Mapped[Olt] = relationship(back_populates="onus")
    profile: Mapped[ServiceProfile | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(40))
    olt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onu_serial: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
