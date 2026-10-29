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


class Gateway(Base):
    """MikroTik por el que el servidor llega a las OLTs cuando no está conectado físicamente a él.

    El servidor y el MikroTik se unen con un túnel WireGuard. Las claves privadas del servidor
    se guardan cifradas y nunca se devuelven por la API.
    """

    __tablename__ = "gateways"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    endpoint: Mapped[str] = mapped_column(String(253))  # IP pública o DDNS del MikroTik
    listen_port: Mapped[int] = mapped_column(Integer, default=13231)
    tunnel_net: Mapped[str] = mapped_column(String(18))  # ej. 10.99.0.0/30
    router_ip: Mapped[str] = mapped_column(String(15))   # IP del MikroTik dentro del túnel
    server_ip: Mapped[str] = mapped_column(String(15))   # IP de este servidor dentro del túnel
    server_private_enc: Mapped[str] = mapped_column(Text)  # cifrada
    server_public_key: Mapped[str] = mapped_column(String(64))
    router_public_key: Mapped[str] = mapped_column(String(64), default="")  # la imprime el script
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    olts: Mapped[list["Olt"]] = relationship(back_populates="gateway")


class Olt(Base):
    __tablename__ = "olts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    vendor: Mapped[str] = mapped_column(String(30))  # tplink | zte | vsol | btpon | mock
    model: Mapped[str] = mapped_column(String(60), default="")
    host: Mapped[str] = mapped_column(String(253))   # IP de gestión de la OLT
    cli_protocol: Mapped[str] = mapped_column(String(10), default="ssh")  # ssh | telnet
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    telnet_port: Mapped[int] = mapped_column(Integer, default=23)
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    username: Mapped[str] = mapped_column(String(80), default="")
    # Secretos: siempre cifrados (ver app/secrets.py)
    password_enc: Mapped[str] = mapped_column(Text, default="")
    snmp_read_enc: Mapped[str] = mapped_column(Text, default="")
    snmp_write_enc: Mapped[str] = mapped_column(Text, default="")
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("gateways.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    onus: Mapped[list["Onu"]] = relationship(back_populates="olt", cascade="all, delete-orphan")
    gateway: Mapped[Gateway | None] = relationship(back_populates="olts")

    @property
    def cli_port(self) -> int:
        return self.ssh_port if self.cli_protocol == "ssh" else self.telnet_port

    @property
    def has_snmp_read(self) -> bool:
        return bool(self.snmp_read_enc)

    @property
    def has_snmp_write(self) -> bool:
        return bool(self.snmp_write_enc)


class SpeedPlan(Base):
    """Plan de velocidad que se limita a nivel OLT. Valores en kbps (como el DBA de la OLT)."""

    __tablename__ = "speed_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)  # ej. "50 Mbps"
    up_kbps: Mapped[int] = mapped_column(Integer)
    down_kbps: Mapped[int] = mapped_column(Integer)
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
    vlan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_plan_id: Mapped[int | None] = mapped_column(ForeignKey("speed_plans.id"), nullable=True)
    rx_power_dbm: Mapped[str] = mapped_column(String(20), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    olt: Mapped[Olt] = relationship(back_populates="onus")
    speed_plan: Mapped[SpeedPlan | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(40))
    olt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onu_serial: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)  # siempre en minúsculas
    password_hash: Mapped[str] = mapped_column(String(255))          # scrypt, nunca la contraseña
    role: Mapped[str] = mapped_column(String(10), default="operator")  # admin | operator
    active: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    """Sesión de login. Solo se guarda el hash del token: si alguien leyera la base no podría usarlo."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(String(200), default="")
