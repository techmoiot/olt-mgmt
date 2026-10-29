from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas, services
from .adapters.base import AdapterError
from .config import settings
from .db import Base, engine, get_db
from .models import AuditLog, Olt, Onu, OnuStatus, ServiceProfile

Base.metadata.create_all(engine)

app = FastAPI(title="OLT Management", version="0.1.0")


def _onu_or_404(db: Session, onu_id: int) -> Onu:
    onu = db.get(Onu, onu_id)
    if onu is None:
        raise HTTPException(404, "ONU no encontrada")
    return onu


def _run(fn, *args, **kwargs):
    """Traduce errores de OLT a respuestas HTTP claras."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc))
    except AdapterError as exc:
        raise HTTPException(502, str(exc))


@app.get("/health")
def health():
    return {"ok": True}


# ---- OLTs -------------------------------------------------------------------
@app.post("/olts", response_model=schemas.OltOut, status_code=201)
def create_olt(body: schemas.OltCreate, db: Session = Depends(get_db)):
    if body.vendor == "mock" and not settings.allow_mock:
        raise HTTPException(400, "Las OLTs mock están deshabilitadas")
    if db.scalar(select(Olt).where(Olt.name == body.name)):
        raise HTTPException(409, f"Ya existe una OLT llamada {body.name!r}")
    olt = Olt(**body.model_dump())
    db.add(olt)
    db.commit()
    return olt


@app.get("/olts", response_model=list[schemas.OltOut])
def list_olts(db: Session = Depends(get_db)):
    return db.scalars(select(Olt)).all()


@app.post("/olts/{olt_id}/scan", response_model=list[schemas.OnuOut])
def scan(olt_id: int, db: Session = Depends(get_db)):
    olt = db.get(Olt, olt_id)
    if olt is None:
        raise HTTPException(404, "OLT no encontrada")
    return _run(services.scan_olt, db, olt)


# ---- Perfiles ---------------------------------------------------------------
@app.post("/profiles", response_model=schemas.ProfileOut, status_code=201)
def create_profile(body: schemas.ProfileCreate, db: Session = Depends(get_db)):
    profile = ServiceProfile(**body.model_dump())
    db.add(profile)
    db.commit()
    return profile


@app.get("/profiles", response_model=list[schemas.ProfileOut])
def list_profiles(db: Session = Depends(get_db)):
    return db.scalars(select(ServiceProfile)).all()


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
    profile = db.get(ServiceProfile, body.profile_id)
    if profile is None:
        raise HTTPException(404, "Perfil no encontrado")
    return _run(services.authorize_onu, db, onu, profile, body.customer_name, body.customer_ref, body.actor)


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
