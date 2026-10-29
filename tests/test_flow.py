import os
import tempfile

# Base de datos temporal, antes de importar la app
os.environ["ONU_DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.adapters.mock import mock_add_unauthorized, mock_reset  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def setup_function():
    mock_reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _setup_olt_and_profile():
    olt = client.post("/olts", json={"name": "olt-test", "vendor": "mock", "host": "10.0.0.1"}).json()
    prof = client.post(
        "/profiles", json={"name": "100M", "line_profile": "LINE_100M", "service_profile": "SRV", "vlan": 100}
    ).json()
    return olt, prof


def test_full_flow():
    olt, prof = _setup_olt_and_profile()
    mock_add_unauthorized("10.0.0.1", "TPLG12345678", "0/1")

    # escaneo detecta la ONU pendiente
    pending = client.post(f"/olts/{olt['id']}/scan").json()
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    onu_id = pending[0]["id"]

    # autorizar
    r = client.post(f"/onus/{onu_id}/authorize", json={"profile_id": prof["id"], "customer_name": "Juan Pérez"})
    assert r.status_code == 200
    assert r.json()["status"] == "authorized" and r.json()["onu_id"] == 1

    # no se puede autorizar dos veces
    r = client.post(f"/onus/{onu_id}/authorize", json={"profile_id": prof["id"], "customer_name": "X"})
    assert r.status_code == 502

    # suspender, reactivar, eliminar
    assert client.post(f"/onus/{onu_id}/suspend").json()["status"] == "suspended"
    assert client.post(f"/onus/{onu_id}/resume").json()["status"] == "authorized"
    assert client.delete(f"/onus/{onu_id}").json()["status"] == "deleted"

    # auditoría registró todo
    actions = [e["action"] for e in client.get("/audit").json()]
    assert {"detected", "authorized", "suspended", "resumed", "deleted"} <= set(actions)


def test_rescan_is_idempotent():
    olt, _ = _setup_olt_and_profile()
    mock_add_unauthorized("10.0.0.1", "TPLG0000AAAA", "0/2")
    client.post(f"/olts/{olt['id']}/scan")
    client.post(f"/olts/{olt['id']}/scan")
    onus = client.get("/onus", params={"olt_id": olt["id"]}).json()
    assert len([o for o in onus if o["serial"] == "TPLG0000AAAA"]) == 1


def test_tplink_returns_501_until_implemented():
    olt = client.post("/olts", json={"name": "tp1", "vendor": "tplink", "host": "10.0.0.9"}).json()
    r = client.post(f"/olts/{olt['id']}/scan")
    assert r.status_code == 501
