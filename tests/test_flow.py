

from tests.helpers import AuthedClient

from app.adapters.mock import mock_add_unauthorized, mock_reset  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

client = AuthedClient(app)


def setup_function():
    mock_reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _setup_olt_and_plan():
    olt = client.post("/olts", json={"name": "olt-test", "vendor": "mock", "host": "10.0.0.1"}).json()
    plan = client.post("/speed-plans", json={"name": "50M", "up_kbps": 51200, "down_kbps": 51200}).json()
    return olt, plan


def test_full_flow():
    olt, plan = _setup_olt_and_plan()
    mock_add_unauthorized("10.0.0.1", "TPLG12345678", "0/1")

    # el selector de VLAN muestra las VLANs de la OLT
    assert 254 in client.get(f"/olts/{olt['id']}/vlans").json()

    # escaneo detecta la ONU pendiente
    pending = client.post(f"/olts/{olt['id']}/scan").json()
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    onu_id = pending[0]["id"]

    # autorizar eligiendo VLAN y plan de velocidad
    body = {"vlan": 254, "speed_plan_id": plan["id"], "customer_name": "Juan Pérez"}
    r = client.post(f"/onus/{onu_id}/authorize", json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "authorized" and r.json()["onu_id"] == 0
    assert r.json()["vlan"] == 254 and r.json()["speed_plan_id"] == plan["id"]

    # no se puede autorizar dos veces
    r = client.post(f"/onus/{onu_id}/authorize", json=body)
    assert r.status_code == 400

    # suspender, reactivar, eliminar
    assert client.post(f"/onus/{onu_id}/suspend").json()["status"] == "suspended"
    assert client.post(f"/onus/{onu_id}/resume").json()["status"] == "authorized"
    assert client.delete(f"/onus/{onu_id}").json()["status"] == "deleted"

    # auditoría registró todo
    actions = [e["action"] for e in client.get("/audit").json()]
    assert {"detected", "authorized", "suspended", "resumed", "deleted"} <= set(actions)


def test_rejects_vlan_not_in_olt():
    olt, plan = _setup_olt_and_plan()
    mock_add_unauthorized("10.0.0.1", "TPLG0000BBBB", "0/1")
    onu = client.post(f"/olts/{olt['id']}/scan").json()[0]
    r = client.post(
        f"/onus/{onu['id']}/authorize",
        json={"vlan": 999, "speed_plan_id": plan["id"], "customer_name": "X"},
    )
    assert r.status_code == 400 and "999" in r.json()["detail"]
    # la ONU sigue pendiente
    assert client.get("/onus", params={"status": "pending"}).json()[0]["id"] == onu["id"]


def test_onu_id_uses_first_free_slot():
    olt, plan = _setup_olt_and_plan()
    for sn in ("A1", "A2"):
        mock_add_unauthorized("10.0.0.1", sn, "0/1")
    onus = client.post(f"/olts/{olt['id']}/scan").json()
    ids = []
    for o in onus:
        r = client.post(f"/onus/{o['id']}/authorize", json={"vlan": 251, "speed_plan_id": plan["id"], "customer_name": "c"})
        ids.append(r.json()["onu_id"])
    assert ids == [0, 1]
    # al borrar la 0, la siguiente reutiliza el hueco
    client.delete(f"/onus/{onus[0]['id']}")
    mock_add_unauthorized("10.0.0.1", "A3", "0/1")
    new = [o for o in client.post(f"/olts/{olt['id']}/scan").json() if o["serial"] == "A3"][0]
    r = client.post(f"/onus/{new['id']}/authorize", json={"vlan": 251, "speed_plan_id": plan["id"], "customer_name": "c"})
    assert r.json()["onu_id"] == 0


def test_rescan_is_idempotent():
    olt, _ = _setup_olt_and_plan()
    mock_add_unauthorized("10.0.0.1", "TPLG0000AAAA", "0/2")
    client.post(f"/olts/{olt['id']}/scan")
    client.post(f"/olts/{olt['id']}/scan")
    onus = client.get("/onus", params={"olt_id": olt["id"]}).json()
    assert len([o for o in onus if o["serial"] == "TPLG0000AAAA"]) == 1


def test_tplink_returns_501_until_implemented():
    olt = client.post("/olts", json={"name": "tp1", "vendor": "tplink", "host": "10.0.0.9"}).json()
    r = client.post(f"/olts/{olt['id']}/scan")
    assert r.status_code == 501
