"""Lógica de negocio: escaneo, autorización y cambios de estado de ONUs."""
import socket
import threading
import time
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import get_adapter
from .adapters.base import AdapterError, AuthorizeRequest, InvalidRequest, OltAdapter, OltCredentials
from .mikrotik import MikrotikParams, generate_script
from .models import AuditLog, Olt, Onu, OnuStatus, SpeedPlan, utcnow

# Una sola operación a la vez por OLT: la mayoría no tolera sesiones CLI concurrentes.
_olt_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)


def adapter_for(olt: Olt) -> OltAdapter:
    return get_adapter(
        olt.vendor,
        OltCredentials(olt.host, olt.port, olt.protocol, olt.username, olt.password),
    )


def audit(db: Session, action: str, olt_id: int | None, serial: str = "", detail: str = "", actor: str = "system") -> None:
    db.add(AuditLog(action=action, olt_id=olt_id, onu_serial=serial, detail=detail, actor=actor))


def scan_olt(db: Session, olt: Olt) -> list[Onu]:
    """Consulta las ONUs sin autorizar de la OLT y las registra como PENDING."""
    with _olt_locks[olt.id]:
        found = adapter_for(olt).list_unauthorized()

    pending: list[Onu] = []
    now = utcnow()
    for d in found:
        onu = db.scalar(select(Onu).where(Onu.olt_id == olt.id, Onu.serial == d.serial))
        if onu is None:
            onu = Onu(olt_id=olt.id, serial=d.serial, pon_port=d.pon_port, status=OnuStatus.PENDING)
            db.add(onu)
            audit(db, "detected", olt.id, d.serial, f"puerto {d.pon_port}")
        elif onu.status == OnuStatus.DELETED:
            onu.status = OnuStatus.PENDING
            onu.onu_id = None
        onu.pon_port = d.pon_port
        onu.rx_power_dbm = d.rx_power_dbm
        onu.last_seen = now
        pending.append(onu)
    db.commit()
    return pending


def check_olt_reachable(olt: Olt, timeout: float = 3.0) -> dict:
    """Prueba TCP al puerto de gestión. No envía credenciales ni comandos."""
    if olt.vendor == "mock":
        return {"reachable": True, "latency_ms": 0.0, "detail": "OLT simulada"}
    if olt.protocol == "snmp":
        return {"reachable": None, "detail": "SNMP usa UDP: no se puede comprobar con una conexión TCP"}
    start = time.monotonic()
    try:
        with socket.create_connection((olt.host, olt.port), timeout=timeout):
            pass
    except OSError as exc:
        return {"reachable": False, "detail": f"No se pudo conectar a {olt.host}:{olt.port} ({exc})"}
    ms = round((time.monotonic() - start) * 1000, 1)
    return {"reachable": True, "latency_ms": ms, "detail": f"Puerto {olt.port} abierto en {olt.host}"}


def mikrotik_script(olt: Olt, body) -> tuple[str, list[str]]:
    return generate_script(
        MikrotikParams(
            olt_name=olt.name,
            olt_ip=olt.host,
            olt_protocol=olt.protocol,
            olt_port=olt.port,
            system_ip=str(body.system_ip),
            trunk_interface=body.trunk_interface,
            vlan_id=body.vlan_id,
            gateway_ip=str(body.gateway_ip),
            prefix=body.prefix,
            bridge=body.bridge,
            masquerade=body.masquerade,
        )
    )


def olt_vlans(olt: Olt) -> list[int]:
    with _olt_locks[olt.id]:
        return sorted(adapter_for(olt).list_vlans())


def authorize_onu(db: Session, onu: Onu, vlan: int, plan: SpeedPlan, customer_name: str, customer_ref: str, actor: str) -> Onu:
    if onu.status != OnuStatus.PENDING:
        raise InvalidRequest(f"La ONU está en estado {onu.status.value}, solo se autoriza una pendiente")
    adapter = adapter_for(onu.olt)
    with _olt_locks[onu.olt_id]:
        # Validar la VLAN contra las que existen en la OLT, si el adaptador sabe listarlas.
        try:
            known = adapter.list_vlans()
        except NotImplementedError:
            known = None
        if known is not None and vlan not in known:
            raise InvalidRequest(f"La VLAN {vlan} no existe en la OLT. Disponibles: {sorted(known)}")
        result = adapter.authorize(
            AuthorizeRequest(
                serial=onu.serial,
                pon_port=onu.pon_port,
                vlan=vlan,
                up_kbps=plan.up_kbps,
                down_kbps=plan.down_kbps,
                description=customer_name,
            )
        )

    onu.onu_id = result.onu_id
    onu.status = OnuStatus.AUTHORIZED
    onu.vlan = vlan
    onu.speed_plan_id = plan.id
    onu.customer_name = customer_name
    onu.customer_ref = customer_ref
    audit(
        db, "authorized", onu.olt_id, onu.serial,
        f"cliente={customer_name} vlan={vlan} plan={plan.name} onu_id={result.onu_id}", actor,
    )
    db.commit()
    return onu


def _require_authorized(onu: Onu) -> None:
    if onu.onu_id is None or onu.status not in (OnuStatus.AUTHORIZED, OnuStatus.SUSPENDED):
        raise InvalidRequest("La ONU no está autorizada en la OLT")


def suspend_onu(db: Session, onu: Onu, actor: str = "api") -> Onu:
    _require_authorized(onu)
    with _olt_locks[onu.olt_id]:
        adapter_for(onu.olt).suspend(onu.pon_port, onu.onu_id)
    onu.status = OnuStatus.SUSPENDED
    audit(db, "suspended", onu.olt_id, onu.serial, actor=actor)
    db.commit()
    return onu


def resume_onu(db: Session, onu: Onu, actor: str = "api") -> Onu:
    _require_authorized(onu)
    with _olt_locks[onu.olt_id]:
        adapter_for(onu.olt).resume(onu.pon_port, onu.onu_id)
    onu.status = OnuStatus.AUTHORIZED
    audit(db, "resumed", onu.olt_id, onu.serial, actor=actor)
    db.commit()
    return onu


def delete_onu(db: Session, onu: Onu, actor: str = "api") -> Onu:
    _require_authorized(onu)
    with _olt_locks[onu.olt_id]:
        adapter_for(onu.olt).delete(onu.pon_port, onu.onu_id)
    onu.status = OnuStatus.DELETED
    onu.onu_id = None
    audit(db, "deleted", onu.olt_id, onu.serial, actor=actor)
    db.commit()
    return onu
