"""Autenticación de Ritsuko: contraseñas, sesiones, CSRF y límite de intentos.

Reglas de diseño:
  * Todo está protegido por defecto: el middleware exige sesión en CUALQUIER ruta que no esté en la
    lista pública. Una ruta nueva queda cerrada aunque se olviden de ponerle nada.
  * Las contraseñas se guardan con scrypt (salt aleatorio). Nunca se guardan ni se registran en claro.
  * La sesión es una cookie HttpOnly + SameSite=Strict con un token aleatorio; en la base solo se guarda
    su hash SHA-256. Caduca por tiempo máximo y por inactividad.
  * Toda petición que modifica algo (POST/PUT/PATCH/DELETE) exige además el encabezado X-CSRF-Token.
  * Cinco intentos fallidos seguidos bloquean al usuario desde esa IP unos minutos.
"""
import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import AuditLog, User, UserSession, utcnow

COOKIE = "ritsuko_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Únicas rutas que se pueden usar sin sesión. Todo lo demás exige login.
PUBLIC_PATHS = {"/", "/health", "/auth/login"}
PUBLIC_PREFIXES = ("/static/",)
# Con una contraseña temporal solo se puede cambiarla, ver quién eres o salir.
ALLOWED_WHEN_MUST_CHANGE = {"/auth/me", "/auth/change-password", "/auth/logout"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # Sin scripts ni estilos en línea: cualquier XSS quedaría sin poder ejecutarse.
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


# ---- Contraseñas ------------------------------------------------------------
_N, _R, _P = 2**14, 8, 1  # scrypt: ~16 MiB y ~50 ms por verificación


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        calc = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(calc, expected)
    except Exception:  # noqa: BLE001  (formato inválido = no coincide)
        return False


# Hash de relleno: verificar contra él cuando el usuario no existe hace que tardar lo mismo que con un
# usuario real, así no se puede averiguar qué usuarios existen midiendo tiempos.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class WeakPassword(ValueError):
    pass


_COMMON = {
    "password", "password1", "contrasena", "contraseña", "1234567890", "12345678910", "qwertyuiop",
    "ritsuko123", "administrador", "admin12345", "0123456789", "abcdefghij", "passw0rd123",
}


def validate_password(password: str, username: str = "") -> None:
    if len(password) < 10:
        raise WeakPassword("La contraseña debe tener al menos 10 caracteres")
    if len(password) > 128:
        raise WeakPassword("La contraseña no puede pasar de 128 caracteres")
    if password.lower() in _COMMON or len(set(password)) < 5:
        raise WeakPassword("La contraseña es demasiado fácil de adivinar")
    if username and username.lower() in password.lower():
        raise WeakPassword("La contraseña no puede contener el nombre de usuario")


def generate_password() -> str:
    """Contraseña aleatoria de ~24 caracteres para usuarios iniciales o restablecimientos."""
    return secrets.token_urlsafe(18)


# ---- Límite de intentos -----------------------------------------------------
class LoginLimiter:
    def __init__(self, max_fails: int = 5, window: int = 900, lock: int = 300, ip_max_fails: int = 30):
        self.max_fails, self.window, self.lock, self.ip_max_fails = max_fails, window, lock, ip_max_fails
        self._mutex = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        self._fails[key] = recent
        return recent

    def retry_after(self, username: str, ip: str) -> int:
        """Segundos que faltan para poder intentar de nuevo (0 = puede intentar)."""
        now = time.time()
        with self._mutex:
            wait = 0
            for key, limit in ((f"u:{username}|{ip}", self.max_fails), (f"ip:{ip}", self.ip_max_fails)):
                recent = self._recent(key, now)
                if len(recent) >= limit:
                    wait = max(wait, int(recent[-1] + self.lock - now) + 1)
            return max(wait, 0)

    def fail(self, username: str, ip: str) -> None:
        now = time.time()
        with self._mutex:
            for key in (f"u:{username}|{ip}", f"ip:{ip}"):
                self._recent(key, now).append(now)

    def success(self, username: str, ip: str) -> None:
        with self._mutex:
            self._fails.pop(f"u:{username}|{ip}", None)

    def reset(self) -> None:
        with self._mutex:
            self._fails.clear()


limiter = LoginLimiter()


# ---- Sesiones ---------------------------------------------------------------
@dataclass
class AuthUser:
    id: int
    username: str
    role: str
    must_change_password: bool
    session_id: int
    csrf_token: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    """SQLite devuelve fechas sin zona horaria: se interpretan como UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User, ip: str, user_agent: str) -> tuple[str, UserSession]:
    now = utcnow()
    db.execute(delete(UserSession).where(UserSession.expires_at < now))  # limpieza de sesiones vencidas
    token = secrets.token_urlsafe(32)
    sess = UserSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(hours=settings.session_hours),
        last_seen=now,
        ip=ip[:45],
        user_agent=user_agent[:200],
    )
    db.add(sess)
    db.commit()
    return token, sess


def revoke_user_sessions(db: Session, user_id: int, keep_session_id: int | None = None) -> None:
    q = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_session_id is not None:
        q = q.where(UserSession.id != keep_session_id)
    db.execute(q)


def load_session(token: str | None) -> AuthUser | None:
    """Devuelve el usuario de una cookie válida, o None si no existe, venció o el usuario está inactivo."""
    if not token:
        return None
    with SessionLocal() as db:
        sess = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
        if sess is None:
            return None
        now = utcnow()
        idle = timedelta(minutes=settings.session_idle_minutes)
        user = db.get(User, sess.user_id)
        if _aware(sess.expires_at) <= now or _aware(sess.last_seen) + idle <= now or user is None or not user.active:
            db.delete(sess)
            db.commit()
            return None
        if now - _aware(sess.last_seen) > timedelta(seconds=60):  # no escribir en cada petición
            sess.last_seen = now
            db.commit()
        return AuthUser(user.id, user.username, user.role, user.must_change_password, sess.id, sess.csrf_token)


def audit(db: Session, action: str, actor: str, detail: str = "") -> None:
    db.add(AuditLog(action=action, actor=actor, detail=detail))


# ---- Middleware y dependencias ----------------------------------------------
def _with_headers(response):
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if _is_public(path):
        return _with_headers(await call_next(request))

    user = await run_in_threadpool(load_session, request.cookies.get(COOKIE))
    if user is None:
        return _with_headers(JSONResponse({"detail": "No autenticado"}, status_code=401))

    if request.method not in SAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent.encode(), user.csrf_token.encode()):
            return _with_headers(JSONResponse({"detail": "Falta o es inválido el token CSRF"}, status_code=403))

    if user.must_change_password and path not in ALLOWED_WHEN_MUST_CHANGE:
        return _with_headers(JSONResponse(
            {"detail": "Debes cambiar tu contraseña antes de continuar", "code": "password_change_required"},
            status_code=403,
        ))

    request.state.user = user
    return _with_headers(await call_next(request))


def current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if user is None:  # no debería pasar: el middleware ya lo exigió
        raise HTTPException(401, "No autenticado")
    return user


def require_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(403, "Esta acción requiere rol de administrador")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"
