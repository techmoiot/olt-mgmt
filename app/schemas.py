from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import OnuStatus


class OltCreate(BaseModel):
    name: str
    vendor: str
    model: str = ""
    host: str
    port: int = 22
    protocol: str = "ssh"
    username: str = ""
    password: str = ""


class OltOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    vendor: str
    model: str
    host: str
    port: int
    protocol: str


class ProfileCreate(BaseModel):
    name: str
    line_profile: str
    service_profile: str = ""
    vlan: int
    description: str = ""


class ProfileOut(ProfileCreate):
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
    profile_id: int | None
    rx_power_dbm: str
    first_seen: datetime
    last_seen: datetime


class AuthorizeIn(BaseModel):
    profile_id: int
    customer_name: str
    customer_ref: str = ""
    actor: str = "api"
