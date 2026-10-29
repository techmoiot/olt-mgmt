from datetime import timedelta

from fastapi.testclient import TestClient

from app import auth
from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, User, UserSession, utcnow
from tests.helpers import ADMIN_PW, AuthedClient, make_user


def setup_function():
    auth.limiter.reset()


def anon():
    return TestClient(app)


def login(c, user="admin", pw=ADMIN_PW):
    return c.post("/auth/login", json={"username": user, "password": pw})


# ---- Denegar por defecto ----------------------------------------------------
def test_every_route_requires_login_except_public():
    public = {("GET", "/"), ("GET", "/health"), ("POST", "/auth/login")}
    c = anon()
    checked = 0
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods or route.path.startswith(("/static", "/docs", "/redoc", "/openapi")):
            continue
        for m in methods - {"HEAD", "OPTIONS"}:
            if (m, route.path) in public:
                continue
            path = route.path.replace("{olt_id}", "1").replace("{onu_id}", "1").replace("{gateway_id}", "1").replace("{user_id}", "1")
            r = c.request(m, path, json={})
            assert r.status_code == 401, f"{m} {route.path} respondió {r.status_code} sin sesión"
            checked += 1
    assert checked > 20


def test_docs_and_unknown_paths_are_closed():
    c = anon()
    for p in ("/docs", "/openapi.json", "/redoc", "/cosa-inexistente"):
        assert c.get(p).status_code == 401


def test_public_pages_and_security_headers():
    c = anon()
    assert c.get("/health").status_code == 200
    r = c.get("/")
    assert r.status_code == 200 and "Ritsuko" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert c.get("/static/app.js").status_code == 200
    assert "<script>" not in r.text and "style=" not in r.text  # compatible con la CSP (sin código en línea)


# ---- Login ------------------------------------------------------------------
def test_login_ok_sets_secure_cookie_and_me_works():
    make_user()
    c = anon()
    r = login(c)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "admin" and body["role"] == "admin" and body["csrf_token"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/auth/me").json()["username"] == "admin"
    assert "password" not in r.text.lower().replace("must_change_password", "")


def test_login_errors_are_generic():
    make_user()
    make_user("viejo", role="operator")
    with SessionLocal() as db:
        db.query(User).filter_by(username="viejo").update({"active": False})
        db.commit()
    c = anon()
    msgs = set()
    for u, p in (("admin", "mala"), ("noexiste", "x"), ("viejo", ADMIN_PW)):
        r = login(c, u, p)
        assert r.status_code == 401
        msgs.add(r.json()["detail"])
    assert len(msgs) == 1  # no revela si el usuario existe o está desactivado


def test_username_is_case_insensitive():
    make_user()
    assert login(anon(), "  ADMIN ").status_code == 200


def test_lockout_after_repeated_failures():
    make_user()
    c = anon()
    for _ in range(5):
        assert login(c, pw="mala").status_code == 401
    r = login(c)  # aunque ahora sea la correcta
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_failed_logins_are_audited_without_password():
    make_user()
    login(anon(), pw="secretisima-1234")
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter_by(action="login_failed").all()
    assert rows and all("secretisima" not in (r.detail + r.actor) for r in rows)


def test_password_stored_hashed_and_token_stored_hashed():
    make_user()
    c = anon()
    login(c)
    token = c.cookies.get(auth.COOKIE)
    with SessionLocal() as db:
        u = db.query(User).one()
        s = db.query(UserSession).one()
    assert u.password_hash.startswith("scrypt$") and ADMIN_PW not in u.password_hash
    assert s.token_hash != token and len(s.token_hash) == 64


# ---- Sesiones ---------------------------------------------------------------
def test_logout_invalidates_session():
    c = AuthedClient(app)
    assert c.get("/olts").status_code == 200
    token = c.cookies.get(auth.COOKIE)
    assert c.post("/auth/logout").status_code == 204
    c2 = anon(); c2.cookies.set(auth.COOKIE, token)
    assert c2.get("/olts").status_code == 401


def test_session_expires_and_idle_timeout():
    make_user()
    c = anon(); login(c)
    with SessionLocal() as db:
        s = db.query(UserSession).one(); s.last_seen = utcnow() - timedelta(hours=5); db.commit()
    assert c.get("/auth/me").status_code == 401  # inactividad (límite 120 min)
    c = anon(); login(c)
    with SessionLocal() as db:
        s = db.query(UserSession).one(); s.expires_at = utcnow() - timedelta(seconds=1); db.commit()
    assert c.get("/auth/me").status_code == 401


def test_deactivated_user_loses_access_immediately():
    c = AuthedClient(app)
    assert c.get("/olts").status_code == 200
    with SessionLocal() as db:
        db.query(User).update({"active": False}); db.commit()
    c2 = anon(); c2.cookies.set(auth.COOKIE, c.cookies.get(auth.COOKIE))
    assert c2.get("/olts").status_code == 401


# ---- CSRF -------------------------------------------------------------------
def test_csrf_required_for_writes():
    make_user()
    c = anon(); login(c)
    r = c.post("/speed-plans", json={"name": "x", "up_kbps": 1000, "down_kbps": 1000})
    assert r.status_code == 403
    r = c.post("/speed-plans", json={"name": "x", "up_kbps": 1000, "down_kbps": 1000}, headers={"X-CSRF-Token": "falso"})
    assert r.status_code == 403
    assert c.get("/speed-plans").status_code == 200  # las lecturas no lo necesitan


# ---- Contraseña temporal ----------------------------------------------------
def test_must_change_password_blocks_everything_else():
    make_user("nuevo", "temporal-pass-1", "operator", must_change=True)
    c = anon()
    csrf = login(c, "nuevo", "temporal-pass-1").json()
    assert csrf["must_change_password"] is True
    h = {"X-CSRF-Token": csrf["csrf_token"]}
    r = c.get("/olts")
    assert r.status_code == 403 and r.json()["code"] == "password_change_required"
    assert c.get("/auth/me").status_code == 200
    r = c.post("/auth/change-password", json={"current_password": "temporal-pass-1", "new_password": "otra-clave-larga-9"}, headers=h)
    assert r.status_code == 204
    assert c.get("/olts").status_code == 200


def test_change_password_rules():
    c = AuthedClient(app)
    c.get("/olts")
    def change(cur, new):
        return c.post("/auth/change-password", json={"current_password": cur, "new_password": new})
    assert change("incorrecta", "una-clave-larga-1").status_code == 400
    assert change(ADMIN_PW, "corta").status_code == 400
    assert change(ADMIN_PW, "admin-admin-admin").status_code == 400  # contiene el usuario
    assert change(ADMIN_PW, ADMIN_PW).status_code == 400
    assert change(ADMIN_PW, "una-clave-larga-1").status_code == 204
    assert login(anon(), pw=ADMIN_PW).status_code == 401
    assert login(anon(), pw="una-clave-larga-1").status_code == 200


def test_change_password_closes_other_sessions():
    make_user()
    a, b = anon(), anon()
    login(a); csrf = login(b).json()["csrf_token"]
    r = b.post("/auth/change-password", json={"current_password": ADMIN_PW, "new_password": "una-clave-larga-1"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204
    assert a.get("/auth/me").status_code == 401
    assert b.get("/auth/me").status_code == 200


# ---- Roles y usuarios -------------------------------------------------------
def test_operator_can_authorize_but_not_admin_things():
    adm = AuthedClient(app)
    adm.post("/olts", json={"name": "o", "vendor": "mock", "host": "10.0.0.9"})
    op = AuthedClient(app, "operador1", "clave-operador-1", "operator")
    assert op.get("/olts").status_code == 200
    assert op.get("/onus").status_code == 200
    for m, p in (("post", "/olts"), ("delete", "/olts/1"), ("get", "/gateways"), ("post", "/gateways"),
                 ("post", "/speed-plans"), ("get", "/audit"), ("get", "/users"), ("post", "/users"),
                 ("delete", "/onus/1"), ("post", "/olts/1/mikrotik-script")):
        assert op.request(m.upper(), p, json={}).status_code == 403, f"{m} {p}"


def test_audit_actor_is_session_user_not_client_supplied():
    from app.adapters.mock import mock_add_unauthorized
    adm = AuthedClient(app)
    olt = adm.post("/olts", json={"name": "o", "vendor": "mock", "host": "10.0.0.1"}).json()
    plan = adm.post("/speed-plans", json={"name": "50M", "up_kbps": 51200, "down_kbps": 51200}).json()
    mock_add_unauthorized("10.0.0.1", "TPLG00000001", "0/1")
    onu = adm.post(f"/olts/{olt['id']}/scan").json()[0]
    r = adm.post(f"/onus/{onu['id']}/authorize",
                 json={"vlan": 254, "speed_plan_id": plan["id"], "customer_name": "c", "customer_ref": "r", "actor": "falso"})
    assert r.status_code == 200, r.text
    actors = {a["actor"] for a in adm.get("/audit").json() if a["action"] == "authorized"}
    assert actors == {"admin"}


def test_user_management_flow():
    c = AuthedClient(app)
    r = c.post("/users", json={"username": "Juan", "password": "x" * 12, "role": "operator"})
    assert r.status_code == 422  # el nombre debe ir en minúsculas y válido
    assert c.post("/users", json={"username": "juan", "password": "corta", "role": "operator"}).status_code == 400
    r = c.post("/users", json={"username": "juan", "password": "clave-temporal-1", "role": "operator"})
    assert r.status_code == 201 and r.json()["must_change_password"] is True and "password_hash" not in r.text
    assert c.post("/users", json={"username": "juan", "password": "clave-temporal-1"}).status_code == 409
    uid = r.json()["id"]
    assert len(c.get("/users").json()) == 2
    # restablecer cierra sus sesiones y exige cambio
    j = anon(); login(j, "juan", "clave-temporal-1")
    assert c.post(f"/users/{uid}/reset-password", json={"new_password": "otra-temporal-22"}).status_code == 204
    assert j.get("/auth/me").status_code == 401
    assert login(anon(), "juan", "otra-temporal-22").json()["must_change_password"] is True
    assert c.patch(f"/users/{uid}", json={"active": False}).json()["active"] is False
    assert login(anon(), "juan", "otra-temporal-22").status_code == 401
    assert c.patch("/users/999", json={"active": False}).status_code == 404


def test_cannot_lock_out_last_admin():
    c = AuthedClient(app)
    me = [u for u in c.get("/users").json() if u["username"] == "admin"][0]
    assert c.patch(f"/users/{me['id']}", json={"active": False}).status_code == 400
    assert c.patch(f"/users/{me['id']}", json={"role": "operator"}).status_code == 400
    # con otro admin, un admin puede degradar al otro pero siempre queda uno
    c.post("/users", json={"username": "otro", "password": "clave-temporal-1", "role": "admin"})
    otro = [u for u in c.get("/users").json() if u["username"] == "otro"][0]
    assert c.patch(f"/users/{otro['id']}", json={"role": "operator"}).status_code == 200


def test_role_change_applies_immediately():
    adm = AuthedClient(app)
    adm.post("/users", json={"username": "ana", "password": "clave-temporal-1", "role": "admin"})
    ana = anon(); csrf = login(ana, "ana", "clave-temporal-1").json()["csrf_token"]
    ana.post("/auth/change-password", json={"current_password": "clave-temporal-1", "new_password": "clave-definitiva-1"},
             headers={"X-CSRF-Token": csrf})
    ana2 = anon(); login(ana2, "ana", "clave-definitiva-1")
    uid = [u for u in adm.get("/users").json() if u["username"] == "ana"][0]["id"]
    adm.patch(f"/users/{uid}", json={"role": "operator"})
    assert ana2.get("/auth/me").status_code == 401  # sesión revocada: debe entrar de nuevo
    ana3 = anon(); login(ana3, "ana", "clave-definitiva-1")
    assert ana3.get("/gateways").status_code == 403
