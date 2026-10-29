from datetime import datetime
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .models import OnuStatus

# Texto imprimible sin comillas ni caracteres de control (se guarda cifrado, pero se valida igual)
_PRINTABLE = r"^[\x20-\x7e]*$"


class OltCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9 _.\-]{1,80}$")
    vendor: str
    model: str = Field("", max_length=60)
    host: str = Field(pattern=r"^[A-Za-z0-9.\-]{1,253}$")  # IP de gestión de la OLT
    cli_protocol: Literal["ssh", "telnet"] = "ssh"          # con cuál se administra por CLI
    ssh_port: int = Field(22, ge=1, le=65535)
    telnet_port: int = Field(23, ge=1, le=65535)
    snmp_port: int = Field(161, ge=1, le=65535)
    snmp_read_community: str = Field("", max_length=64, pattern=_PRINTABLE)
    snmp_write_community: str = Field("", max_length=64, pattern=_PRINTABLE)
    username: str = Field("", max_length=80)
    password: str = Field("", max_length=200)
    # None = el servidor llega directo a la OLT; con un id, llega por la VPN de ese MikroTik
    gateway_id: int | None = None


class OltOut(BaseModel):
    """Nunca incluye contraseñas ni comunidades: solo si están configuradas."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    vendor: str
    model: str
    host: str
    cli_protocol: str
    ssh_port: int
    telnet_port: int
    snmp_port: int
    username: str
    has_snmp_read: bool
    has_snmp_write: bool
    gateway_id: int | None


class ServiceCheck(BaseModel):
    service: Literal["ssh", "telnet", "snmp"]
    port: int
    reachable: bool | None  # None = no se puede comprobar
    latency_ms: float | None = None
    detail: str


class ReachabilityOut(BaseModel):
    checks: list[ServiceCheck]


class MikrotikScriptIn(BaseModel):
    # Solo hace falta si la OLT se alcanza directo; con VPN se usa la IP del túnel del servidor.
    system_ip: IPv4Address | None = None
    trunk_interface: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,32}$")  # puerto del MikroTik hacia la OLT
    vlan_id: int = Field(ge=1, le=4094)   # VLAN de gestión de la OLT
    gateway_ip: IPv4Address               # IP que tendrá el MikroTik en esa VLAN
    prefix: int = Field(ge=8, le=30)
    bridge: str = Field("", pattern=r"^[A-Za-z0-9_.\-]{0,32}$")  # solo si hay bridge con vlan-filtering
    masquerade: bool = True


class ScriptOut(BaseModel):
    script: str
    notes: list[str]


# ---- Gateways (MikroTik + VPN) ---------------------------------------------
class GatewayCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9 _.\-]{1,80}$")
    endpoint: str = Field(pattern=r"^[A-Za-z0-9.\-]{1,253}$")  # IP pública o DDNS del MikroTik
    listen_port: int = Field(13231, ge=1024, le=65535)
    tunnel_net: str | None = Field(None, pattern=r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")  # opcional; si no, se asigna


class GatewayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    endpoint: str
    listen_port: int
    tunnel_net: str
    router_ip: str
    server_ip: str
    server_public_key: str
    router_public_key: str
    created_at: datetime

    @computed_field
    @property
    def vpn_ready(self) -> bool:
        """True cuando ya se pegó la clave pública del MikroTik y se puede armar el túnel."""
        return bool(self.router_public_key)


class RouterKeyIn(BaseModel):
    public_key: str = Field(pattern=r"^[A-Za-z0-9+/]{43}=$")  # clave pública WireGuard (32 bytes en base64)


class VpnScriptIn(BaseModel):
    # Si el servidor tiene IP pública fija, el MikroTik solo aceptará el túnel desde ella.
    server_public_ip: IPv4Address | None = None


# ---- Planes y ONUs ----------------------------------------------------------
class SpeedPlanCreate(BaseModel):
    name: str
    up_kbps: int = Field(gt=0)
    down_kbps: int = Field(gt=0)
    description: str = ""


class SpeedPlanOut(SpeedPlanCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class OnuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    olt_id: int
    serial: str
    pon_port: str
    onu_id: int | None
    status: OnuStatus
    customer_name: str
    customer_ref: str
    vlan: int | None
    speed_plan_id: int | None
    rx_power_dbm: str
    first_seen: datetime
    last_seen: datetime


class AuthorizeIn(BaseModel):
    vlan: int = Field(ge=1, le=4094)  # elegida por el usuario entre las VLANs de la OLT
    speed_plan_id: int                # plan de velocidad (límite en la OLT)
    customer_name: str
    customer_ref: str = ""
    actor: str = "api"
