"""Rutas de autenticación y administración de usuarios."""
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth
from .auth import AuthUser, current_user, require_admin
from .config import settings
from .db import get_db
from .models import User, UserSession, utcnow

router = APIRouter()

USERNAME_RE = r"^[a-z0-9._-]{3,32}$"


# ---- Esquemas ---------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SessionOut(BaseModel):
    username: str
    role: str
    csrf_token: str          # el navegador lo manda en X-CSRF-Token en cada petición que modifica algo
    must_change_password: bool


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_RE)
    password: str = Field(max_length=256)
    role: Literal["admin", "operator"] = "operator"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    active: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None


class UserPatch(BaseModel):
    role: Literal["admin", "operator"] | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(max_length=256)


def _check_password(password: str, username: str) -> None:
    try:
        auth.validate_password(password, username)
    except auth.WeakPassword as exc:
        raise HTTPException(400, str(exc))


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        auth.COOKIE, token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure or request.url.scheme == "https",
        path="/",
    )


def _session_out(user: User | AuthUser, csrf: str) -> dict:
    must = user.must_change_password
    return {"username": user.username, "role": user.role, "csrf_token": csrf, "must_change_password": must}


# ---- Login / logout ---------------------------------------------------------
@router.post("/auth/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    ip = auth.client_ip(request)
    wait = auth.limiter.retry_after(username, ip)
    if wait:
        raise HTTPException(429, f"Demasiados intentos fallidos. Espera {wait} s e inténtalo de nuevo.",
                            headers={"Retry-After": str(wait)})

    user = db.scalar(select(User).where(User.username == username))
    # Se verifica SIEMPRE (contra un hash de relleno si el usuario no existe): mismo tiempo y mismo
    # mensaje para "usuario inexistente", "contraseña mala" y "usuario desactivado".
    valid = auth.verify_password(body.password, user.password_hash if user else auth.DUMMY_HASH)
    if user is None or not user.active or not valid:
        auth.limiter.fail(username, ip)
        safe_name = re.sub(r"[^a-z0-9._-]", "?", username)[:32]
        auth.audit(db, "login_failed", safe_name, f"ip={ip}")
        db.commit()
        raise HTTPException(401, "Usuario o contraseña incorrectos")

    auth.limiter.success(username, ip)
    token, sess = auth.create_session(db, user, ip, request.headers.get("user-agent", ""))
    user.last_login_at = utcnow()
    auth.audit(db, "login_ok", user.username, f"ip={ip}")
    db.commit()
    _set_cookie(request, response, token)
    return _session_out(user, sess.csrf_token)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, user: AuthUser = Depends(current_user), db: Session = Depends(get_db)):
    sess = db.get(UserSession, user.session_id)
    if sess:
        db.delete(sess)
    auth.audit(db, "logout", user.username)
    db.commit()
    response.delete_cookie(auth.COOKIE, path="/")


@router.get("/auth/me", response_model=SessionOut)
def me(user: AuthUser = Depends(current_user)):
    return _session_out(user, user.csrf_token)


@router.post("/auth/change-password", status_code=204)
def change_password(body: ChangePasswordIn, user: AuthUser = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(User, user.id)
    if not auth.verify_password(body.current_password, row.password_hash):
        auth.audit(db, "password_change_failed", user.username)
        db.commit()
        raise HTTPException(400, "La contraseña actual no es correcta")
    _check_password(body.new_password, user.username)
    if auth.verify_password(body.new_password, row.password_hash):
        raise HTTPException(400, "La contraseña nueva debe ser distinta de la actual")
    row.password_hash = auth.hash_password(body.new_password)
    row.must_change_password = False
    auth.revoke_user_sessions(db, row.id, keep_session_id=user.session_id)  # cierra las demás sesiones
    auth.audit(db, "password_changed", user.username)
    db.commit()


# ---- Administración de usuarios (solo admin) --------------------------------
def _other_active_admins(db: Session, exclude_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.active, User.id != exclude_id)
    )


def _user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.username)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, f"Ya existe el usuario {body.username!r}")
    _check_password(body.password, body.username)
    # La contraseña inicial la conoce quien crea la cuenta: el usuario debe cambiarla al entrar.
    user = User(username=body.username, password_hash=auth.hash_password(body.password),
                role=body.role, must_change_password=True)
    db.add(user)
    auth.audit(db, "user_created", admin.username, f"{body.username} ({body.role})")
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserPatch, admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    user = _user_or_404(db, user_id)
    new_role = body.role if body.role is not None else user.role
    new_active = body.active if body.active is not None else user.active
    if user.id == admin.id and (new_role != "admin" or not new_active):
        raise HTTPException(400, "No puedes quitarte a ti mismo el rol de administrador ni desactivarte")
    if user.role == "admin" and user.active and (new_role != "admin" or not new_active):
        if _other_active_admins(db, user.id) == 0:
            raise HTTPException(400, "Tiene que quedar al menos un administrador activo")
    changes = []
    if new_role != user.role:
        changes.append(f"rol {user.role}->{new_role}")
    if new_active != user.active:
        changes.append("activado" if new_active else "desactivado")
    user.role, user.active = new_role, new_active
    if not new_active or "rol" in " ".join(changes):
        auth.revoke_user_sessions(db, user.id)  # los cambios de permisos aplican de inmediato
    if changes:
        auth.audit(db, "user_updated", admin.username, f"{user.username}: {', '.join(changes)}")
    db.commit()
    return user


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, admin: AuthUser = Depends(require_admin),
                   db: Session = Depends(get_db)):
    user = _user_or_404(db, user_id)
    _check_password(body.new_password, user.username)
    user.password_hash = auth.hash_password(body.new_password)
    user.must_change_password = True
    auth.revoke_user_sessions(db, user.id)
    auth.audit(db, "password_reset", admin.username, user.username)
    db.commit()
