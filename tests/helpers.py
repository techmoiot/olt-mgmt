from fastapi.testclient import TestClient
from sqlalchemy import select

ADMIN_PW = "correct-horse-battery"


def make_user(username="admin", password=ADMIN_PW, role="admin", must_change=False):
    from app import auth
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == username))
        if u is None:
            db.add(User(username=username, password_hash=auth.hash_password(password), role=role,
                        must_change_password=must_change))
            db.commit()


class AuthedClient(TestClient):
    """Cliente que inicia sesión solo (y de nuevo si la base se reinicia entre pruebas) y manda el CSRF."""

    def __init__(self, app, username="admin", password=ADMIN_PW, role="admin", **kw):
        super().__init__(app, **kw)
        self._cred = (username, password, role)
        self.csrf = None

    def login(self):
        u, p, role = self._cred
        make_user(u, p, role)
        self.cookies.clear()
        r = super().request("POST", "/auth/login", json={"username": u, "password": p})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]

    def request(self, method, url, **kw):
        if self.csrf is None:
            self.login()
        headers = dict(kw.pop("headers", None) or {})
        headers.setdefault("X-CSRF-Token", self.csrf)
        r = super().request(method, url, headers=headers, **kw)
        if r.status_code == 401:  # sesión perdida (p. ej. se reinició la base): reintenta una vez
            self.login()
            headers["X-CSRF-Token"] = self.csrf
            r = super().request(method, url, headers=headers, **kw)
        return r
