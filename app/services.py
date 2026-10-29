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
from .vault import decrypt

# Una sola operación a la vez por OLT: la mayoría no tolera sesiones CLI concurrentes.
_olt_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)


def adapter_for(olt: Olt) -> OltAdapter:
    return get_adapter(
        olt.vendor,
        OltCredentials(
            host=olt.host,
            port=olt.cli_port,
            protocol=olt.cli_protocol,
            username=olt.username,
            password=decrypt(olt.password_enc),
            snmp_port=olt.snmp_port,
            snmp_read=decrypt(olt.snmp_read_enc),
            snmp_write=decrypt(olt.snmp_write_enc),
        ),
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


def _tcp_check(service: str, host: str, port: int, timeout: float) -> dict:
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return {"service": service, "port": port, "reachable": False,
                "detail": f"No se pudo conectar a {host}:{port} ({exc})"}
    ms = round((time.monotonic() - start) * 1000, 1)
    return {"service": service, "port": port, "reachable": True, "latency_ms": ms,
            "detail": f"Puerto {port} abierto"}


def check_olt_reachable(olt: Olt, timeout: float = 3.0) -> dict:
    """Prueba cada servicio de gestión. Solo abre el puerto TCP: no envía credenciales ni comandos."""
    if olt.vendor == "mock":
        return {"checks": [
            {"service": "ssh", "port": olt.ssh_port, "reachable": True, "latency_ms": 0.0, "detail": "OLT simulada"},
        ]}
    checks = [
        _tcp_check("ssh", olt.host, olt.ssh_port, timeout),
        _tcp_check("telnet", olt.host, olt.telnet_port, timeout),
        {"service": "snmp", "port": olt.snmp_port, "reachable": None,
         "detail": "SNMP usa UDP: aún no se comprueba (se verificará al implementar el adaptador)"},
    ]
    return {"checks": checks}


def mikrotik_script(olt: Olt, body) -> tuple[str, list[str]]:
    """Script de VLAN + firewall del MikroTik para esta OLT.

    Si la OLT llega por VPN, el origen permitido es la IP del servidor dentro del túnel;
    si llega directo, se usa la IP del sistema que indicó el usuario.
    """
    if olt.gateway is not None:
        system_ip, via_vpn = olt.gateway.server_ip, True
    elif body.system_ip is not None:
        system_ip, via_vpn = str(body.system_ip), False
    else:
        raise InvalidRequest("Indica la IP del sistema (esta OLT no está asociada a una VPN/gateway)")
    return generate_script(
        MikrotikParams(
            olt_name=olt.name,
            olt_ip=olt.host,
            cli_protocol=olt.cli_protocol,
            cli_port=olt.cli_port,
            snmp_port=olt.snmp_port if olt.has_snmp_read or olt.has_snmp_write else None,
            system_ip=system_ip,
            trunk_interface=body.trunk_interface,
            vlan_id=body.vlan_id,
            gateway_ip=str(body.gateway_ip),
            prefix=body.prefix,
            bridge=body.bridge,
            masquerade=body.masquerade,
            via_vpn=via_vpn,
        )
    )


def olt_vlans(olt: Olt) -> list[int]:
    with _olt_locks[olt.id]:
        return sorted(adapter_for(olt).list_vlans())


def authorize_onu(db: Session, onu: Onu, form, plan: SpeedPlan | None, actor: str) -> Onu:
    """`form` es un schemas.AuthorizeIn ya validado; `plan` es el plan propio (o None = sin límite / por perfiles)."""
    vlan = form.vlan
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
                up_kbps=plan.up_kbps if plan else 0,
                down_kbps=plan.down_kbps if plan else 0,
                description=form.customer_name,
                line_profile=form.line_profile,
                up_profile=form.up_profile,
                down_profile=form.down_profile,
                svlan=form.svlan,
                config_type=form.config_type,
                onu_model=form.onu_model,
            )
        )

    onu.onu_id = result.onu_id
    onu.status = OnuStatus.AUTHORIZED
    onu.vlan = vlan
    onu.speed_plan_id = plan.id if plan else None
    onu.svlan = form.svlan
    onu.line_profile, onu.up_profile, onu.down_profile = form.line_profile, form.up_profile, form.down_profile
    onu.config_type, onu.onu_model = form.config_type, form.onu_model
    onu.customer_name, onu.customer_ref = form.customer_name, form.customer_ref
    onu.customer_phone, onu.customer_address = form.customer_phone, form.customer_address
    onu.zone_id, onu.nap_id, onu.comments = form.zone_id, form.nap_id, form.comments
    limit = plan.name if plan else (f"{form.up_profile}/{form.down_profile}".strip("/") or "sin límite")
    audit(
        db, "authorized", onu.olt_id, onu.serial,
        f"cliente={form.customer_name} vlan={vlan} svlan={form.svlan} límite={limit} onu_id={result.onu_id}", actor,
    )
    db.commit()
    return onu


def olt_profiles(olt: Olt) -> dict:
    """Perfiles de línea y de velocidad que ya existen en la OLT, para los selectores."""
    adapter = adapter_for(olt)
    with _olt_locks[olt.id]:
        try:
            line = adapter.list_line_profiles()
            up, down = adapter.list_speed_profiles()
        except NotImplementedError:
            return {"line_profiles": [], "up_profiles": [], "down_profiles": [], "supported": False}
    return {"line_profiles": line, "up_profiles": up, "down_profiles": down, "supported": True}


LOW_SIGNAL_DBM = -27.0  # por debajo de esto se considera "baja señal"


def dashboard_stats(db: Session) -> dict:
    onus = db.scalars(select(Onu)).all()
    live = [o for o in onus if o.status != OnuStatus.DELETED]
    authorized = [o for o in live if o.status in (OnuStatus.AUTHORIZED, OnuStatus.SUSPENDED)]

    def low(o: Onu) -> bool:
        try:
            return float(o.rx_power_dbm) < LOW_SIGNAL_DBM
        except ValueError:
            return False

    today = utcnow().date()
    first_auth = [a for a in db.scalars(select(AuditLog).where(AuditLog.action == "authorized")).all()]
    return {
        "olts": len(db.scalars(select(Olt)).all()),
        "onus_total": len(live),
        "pending": sum(o.status == OnuStatus.PENDING for o in live),
        "authorized": len(authorized),
        "suspended": sum(o.status == OnuStatus.SUSPENDED for o in live),
        "online": sum(o.oper_state == "online" for o in authorized),
        "offline": sum(o.oper_state == "offline" for o in authorized),
        "low_signal": sum(low(o) for o in authorized),
        "authorized_today": sum(a.at.date() == today for a in first_auth),
        "authorized_month": sum((a.at.year, a.at.month) == (today.year, today.month) for a in first_auth),
    }


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
