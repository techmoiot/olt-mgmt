import ipaddress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas, services, vpn
from .adapters import ADAPTERS
from .adapters.base import AdapterError, InvalidRequest
from .config import settings
from .db import Base, engine, get_db
from .models import AuditLog, Gateway, Olt, Onu, OnuStatus, SpeedPlan
from .vault import VaultError, encrypt

Base.metadata.create_all(engine)

app = FastAPI(title="Ritsuko", version="0.1.0")


def _vendors() -> list[str]:
    return [v for v in ADAPTERS if v != "mock" or settings.allow_mock]


def _olt_or_404(db: Session, olt_id: int) -> Olt:
    olt = db.get(Olt, olt_id)
    if olt is None:
        raise HTTPException(404, "OLT no encontrada")
    return olt


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


def _onu_or_404(db: Session, onu_id: int) -> Onu:
    onu = db.get(Onu, onu_id)
    if onu is None:
        raise HTTPException(404, "ONU no encontrada")
    return onu


def _run(fn, *args, **kwargs):
    """Traduce errores de OLT a respuestas HTTP claras."""
    try:
        return fn(*args, **kwargs)
    except InvalidRequest as exc:
        raise HTTPException(400, str(exc))
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc))
    except AdapterError as exc:
        raise HTTPException(502, str(exc))
    except VaultError as exc:
        raise HTTPException(500, str(exc))


@app.get("/health")
def health():
    return {"ok": True}


# ---- OLTs -------------------------------------------------------------------
@app.post("/olts", response_model=schemas.OltOut, status_code=201)
def create_olt(body: schemas.OltCreate, db: Session = Depends(get_db)):
    if body.vendor not in ADAPTERS:
        raise HTTPException(400, f"Marca {body.vendor!r} sin adaptador. Disponibles: {', '.join(_vendors())}")
    if body.vendor == "mock" and not settings.allow_mock:
        raise HTTPException(400, "Las OLTs mock están deshabilitadas")
    if db.scalar(select(Olt).where(Olt.name == body.name)):
        raise HTTPException(409, f"Ya existe una OLT llamada {body.name!r}")
    if body.gateway_id is not None:
        if db.get(Gateway, body.gateway_id) is None:
            raise HTTPException(404, "Gateway (MikroTik/VPN) no encontrado")
        try:
            ipaddress.IPv4Address(body.host)
        except ValueError:
            raise HTTPException(400, "Con VPN la OLT debe registrarse con su IP (no con un nombre)")
    data = body.model_dump(exclude={"password", "snmp_read_community", "snmp_write_community"})
    olt = Olt(
        **data,
        password_enc=encrypt(body.password),
        snmp_read_enc=encrypt(body.snmp_read_community),
        snmp_write_enc=encrypt(body.snmp_write_community),
    )
    db.add(olt)
    db.add(AuditLog(action="olt_added", olt_id=None, detail=f"{olt.name} ({olt.vendor}) {olt.host}"))
    db.commit()
    return olt


@app.get("/vendors", response_model=list[str])
def vendors():
    """Marcas con adaptador disponible para el formulario de alta."""
    return _vendors()


@app.post("/olts/{olt_id}/test", response_model=schemas.ReachabilityOut)
def test_olt(olt_id: int, db: Session = Depends(get_db)):
    olt = _olt_or_404(db, olt_id)
    return services.check_olt_reachable(olt)


@app.delete("/olts/{olt_id}", status_code=204)
def delete_olt(olt_id: int, db: Session = Depends(get_db)):
    """Quita la OLT del sistema. No toca la OLT física."""
    olt = _olt_or_404(db, olt_id)
    active = db.scalars(
        select(Onu).where(Onu.olt_id == olt.id, Onu.status.in_([OnuStatus.AUTHORIZED, OnuStatus.SUSPENDED]))
    ).all()
    if active:
        raise HTTPException(409, f"La OLT tiene {len(active)} ONUs autorizadas registradas; elimínalas primero")
    db.add(AuditLog(action="olt_removed", olt_id=None, detail=f"{olt.name} {olt.host}"))
    db.delete(olt)
    db.commit()


@app.post("/olts/{olt_id}/mikrotik-script", response_model=schemas.ScriptOut)
def olt_mikrotik_script(olt_id: int, body: schemas.MikrotikScriptIn, db: Session = Depends(get_db)):
    """Genera (no ejecuta) el script de RouterOS (VLAN de gestión + firewall) para esta OLT."""
    olt = _olt_or_404(db, olt_id)
    script, notes = _run(services.mikrotik_script, olt, body)
    return {"script": script, "notes": notes}


# ---- Gateways: MikroTik + VPN WireGuard -------------------------------------
def _gateway_or_404(db: Session, gateway_id: int) -> Gateway:
    gw = db.get(Gateway, gateway_id)
    if gw is None:
        raise HTTPException(404, "Gateway no encontrado")
    return gw


@app.post("/gateways", response_model=schemas.GatewayOut, status_code=201)
def create_gateway(body: schemas.GatewayCreate, db: Session = Depends(get_db)):
    """Registra un MikroTik y genera el par de claves WireGuard del servidor (la privada queda cifrada)."""
    if db.scalar(select(Gateway).where(Gateway.name == body.name)):
        raise HTTPException(409, f"Ya existe un gateway llamado {body.name!r}")
    used = [g.tunnel_net for g in db.scalars(select(Gateway)).all()]

    def build():
        net = vpn.parse_tunnel_net(body.tunnel_net, used) if body.tunnel_net else ipaddress.ip_network(vpn.next_free_tunnel_net(used))
        router_ip, server_ip = vpn.tunnel_ips(net)
        priv, pub = vpn.generate_keypair()
        return Gateway(
            name=body.name, endpoint=body.endpoint, listen_port=body.listen_port, tunnel_net=str(net),
            router_ip=router_ip, server_ip=server_ip, server_private_enc=encrypt(priv), server_public_key=pub,
        )

    gw = _run(build)
    db.add(gw)
    db.add(AuditLog(action="gateway_added", detail=f"{gw.name} {gw.endpoint}:{gw.listen_port} túnel {gw.tunnel_net}"))
    db.commit()
    return gw


@app.get("/gateways", response_model=list[schemas.GatewayOut])
def list_gateways(db: Session = Depends(get_db)):
    return db.scalars(select(Gateway)).all()


@app.post("/gateways/{gateway_id}/vpn-script", response_model=schemas.ScriptOut)
def gateway_vpn_script(gateway_id: int, body: schemas.VpnScriptIn, db: Session = Depends(get_db)):
    """Genera (no ejecuta) el script de RouterOS que arma el lado MikroTik de la VPN WireGuard."""
    gw = _gateway_or_404(db, gateway_id)
    ip = str(body.server_public_ip) if body.server_public_ip else None
    script, notes = _run(vpn.generate_vpn_script, gw, ip)
    return {"script": script, "notes": notes}


@app.put("/gateways/{gateway_id}/router-key", response_model=schemas.GatewayOut)
def set_router_key(gateway_id: int, body: schemas.RouterKeyIn, db: Session = Depends(get_db)):
    """Guarda la clave pública que imprimió el script en el MikroTik."""
    gw = _gateway_or_404(db, gateway_id)
    gw.router_public_key = body.public_key
    db.add(AuditLog(action="gateway_key_set", detail=gw.name))
    db.commit()
    return gw


@app.delete("/gateways/{gateway_id}", status_code=204)
def delete_gateway(gateway_id: int, db: Session = Depends(get_db)):
    gw = _gateway_or_404(db, gateway_id)
    if gw.olts:
        raise HTTPException(409, f"El gateway tiene {len(gw.olts)} OLTs asociadas; cámbialas o elimínalas primero")
    db.add(AuditLog(action="gateway_removed", detail=gw.name))
    db.delete(gw)
    db.commit()


@app.get("/olts", response_model=list[schemas.OltOut])
def list_olts(db: Session = Depends(get_db)):
    return db.scalars(select(Olt)).all()


@app.post("/olts/{olt_id}/scan", response_model=list[schemas.OnuOut])
def scan(olt_id: int, db: Session = Depends(get_db)):
    olt = db.get(Olt, olt_id)
    if olt is None:
        raise HTTPException(404, "OLT no encontrada")
    return _run(services.scan_olt, db, olt)


@app.get("/olts/{olt_id}/vlans", response_model=list[int])
def olt_vlans(olt_id: int, db: Session = Depends(get_db)):
    """VLANs disponibles en la OLT, para el selector al autorizar."""
    olt = db.get(Olt, olt_id)
    if olt is None:
        raise HTTPException(404, "OLT no encontrada")
    return _run(services.olt_vlans, olt)


# ---- Planes de velocidad ----------------------------------------------------
@app.post("/speed-plans", response_model=schemas.SpeedPlanOut, status_code=201)
def create_speed_plan(body: schemas.SpeedPlanCreate, db: Session = Depends(get_db)):
    if db.scalar(select(SpeedPlan).where(SpeedPlan.name == body.name)):
        raise HTTPException(409, f"Ya existe un plan llamado {body.name!r}")
    plan = SpeedPlan(**body.model_dump())
    db.add(plan)
    db.commit()
    return plan


@app.get("/speed-plans", response_model=list[schemas.SpeedPlanOut])
def list_speed_plans(db: Session = Depends(get_db)):
    return db.scalars(select(SpeedPlan)).all()


# ---- ONUs -------------------------------------------------------------------
@app.get("/onus", response_model=list[schemas.OnuOut])
def list_onus(status: OnuStatus | None = None, olt_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Onu)
    if status:
        q = q.where(Onu.status == status)
    if olt_id:
        q = q.where(Onu.olt_id == olt_id)
    return db.scalars(q).all()


@app.post("/onus/{onu_id}/authorize", response_model=schemas.OnuOut)
def authorize(onu_id: int, body: schemas.AuthorizeIn, db: Session = Depends(get_db)):
    onu = _onu_or_404(db, onu_id)
    plan = db.get(SpeedPlan, body.speed_plan_id)
    if plan is None:
        raise HTTPException(404, "Plan de velocidad no encontrado")
    return _run(services.authorize_onu, db, onu, body.vlan, plan, body.customer_name, body.customer_ref, body.actor)


@app.post("/onus/{onu_id}/suspend", response_model=schemas.OnuOut)
def suspend(onu_id: int, db: Session = Depends(get_db)):
    return _run(services.suspend_onu, db, _onu_or_404(db, onu_id))


@app.post("/onus/{onu_id}/resume", response_model=schemas.OnuOut)
def resume(onu_id: int, db: Session = Depends(get_db)):
    return _run(services.resume_onu, db, _onu_or_404(db, onu_id))


@app.delete("/onus/{onu_id}", response_model=schemas.OnuOut)
def delete(onu_id: int, db: Session = Depends(get_db)):
    return _run(services.delete_onu, db, _onu_or_404(db, onu_id))


# ---- Auditoría --------------------------------------------------------------
@app.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [
        {"at": r.at, "actor": r.actor, "action": r.action, "olt_id": r.olt_id, "serial": r.onu_serial, "detail": r.detail}
        for r in rows
    ]
