from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
