from datetime import datetime
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import OnuStatus


DEFAULT_PORTS = {"ssh": 22, "telnet": 23, "snmp": 161}


class OltCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9 _.\-]{1,80}$")
    vendor: str
    model: str = Field("", max_length=60)
    host: str = Field(pattern=r"^[A-Za-z0-9.\-]{1,253}$")  # IP o nombre de host
    port: int | None = Field(None, ge=1, le=65535)  # si se omite, el estándar del protocolo
    protocol: Literal["ssh", "telnet", "snmp"] = "ssh"
    username: str = Field("", max_length=80)
    password: str = Field("", max_length=200)


class MikrotikScriptIn(BaseModel):
    system_ip: IPv4Address                # IP del servidor donde corre este sistema (el LXC)
    trunk_interface: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,32}$")  # puerto del MikroTik hacia la OLT
    vlan_id: int = Field(ge=1, le=4094)   # VLAN de gestión de la OLT
    gateway_ip: IPv4Address               # IP que tendrá el MikroTik en esa VLAN
    prefix: int = Field(ge=8, le=30)
    bridge: str = Field("", pattern=r"^[A-Za-z0-9_.\-]{0,32}$")  # solo si hay bridge con vlan-filtering
    masquerade: bool = True


class MikrotikScriptOut(BaseModel):
    script: str
    notes: list[str]


class ReachabilityOut(BaseModel):
    reachable: bool | None  # None = no se puede comprobar (SNMP/UDP)
    latency_ms: float | None = None
    detail: str


class OltOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    vendor: str
    model: str
    host: str
    port: int
    protocol: str


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
