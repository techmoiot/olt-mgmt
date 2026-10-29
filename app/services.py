"""Lógica de negocio: escaneo, autorización y cambios de estado de ONUs."""
import threading
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import get_adapter
from .adapters.base import AdapterError, AuthorizeRequest, OltAdapter, OltCredentials
from .models import AuditLog, Olt, Onu, OnuStatus, ServiceProfile, utcnow

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


def authorize_onu(db: Session, onu: Onu, profile: ServiceProfile, customer_name: str, customer_ref: str, actor: str) -> Onu:
    if onu.status != OnuStatus.PENDING:
        raise AdapterError(f"La ONU está en estado {onu.status.value}, solo se autoriza una pendiente")
    req = AuthorizeRequest(
        serial=onu.serial,
        pon_port=onu.pon_port,
        line_profile=profile.line_profile,
        service_profile=profile.service_profile,
        vlan=profile.vlan,
        description=customer_name,
    )
    with _olt_locks[onu.olt_id]:
        result = adapter_for(onu.olt).authorize(req)

    onu.onu_id = result.onu_id
    onu.status = OnuStatus.AUTHORIZED
    onu.profile_id = profile.id
    onu.customer_name = customer_name
    onu.customer_ref = customer_ref
    audit(db, "authorized", onu.olt_id, onu.serial, f"cliente={customer_name} perfil={profile.name} onu_id={result.onu_id}", actor)
    db.commit()
    return onu


def _require_authorized(onu: Onu) -> None:
    if onu.onu_id is None or onu.status not in (OnuStatus.AUTHORIZED, OnuStatus.SUSPENDED):
        raise AdapterError("La ONU no está autorizada en la OLT")


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
