import re
import socket

from fastapi.testclient import TestClient

from app.adapters.mock import mock_add_unauthorized
from app.main import app

client = TestClient(app)

MK = {
    "system_ip": "192.168.88.50",
    "trunk_interface": "ether2",
    "vlan_id": 250,
    "gateway_ip": "172.20.5.1",
    "prefix": 28,
}


def _olt(name="OLT-Centro", host="172.20.5.2", **kw):
    body = {"name": name, "vendor": "tplink", "host": host, **kw}
    r = client.post("/olts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---- Alta de OLTs -----------------------------------------------------------
def test_vendors_listed():
    assert {"tplink", "mock"} <= set(client.get("/vendors").json())


def test_add_olt_default_port_follows_protocol():
    assert _olt("a", "10.0.0.1")["port"] == 22
    assert _olt("b", "10.0.0.2", protocol="telnet")["port"] == 23
    assert _olt("c", "10.0.0.3", protocol="snmp")["port"] == 161
    assert _olt("d", "10.0.0.4", port=2222)["port"] == 2222


def test_add_olt_rejects_bad_input():
    r = client.post("/olts", json={"name": "x", "vendor": "inventada", "host": "10.0.0.1"})
    assert r.status_code == 400 and "tplink" in r.json()["detail"]
    _olt("dup")
    assert client.post("/olts", json={"name": "dup", "vendor": "tplink", "host": "10.0.0.9"}).status_code == 409
    assert client.post("/olts", json={"name": "ok", "vendor": "tplink", "host": "10.0.0.1", "protocol": "ftp"}).status_code == 422
    # nombre con salto de línea (se usa en comentarios del script): rechazado
    assert client.post("/olts", json={"name": "a\n/system reset", "vendor": "tplink", "host": "10.0.0.1"}).status_code == 422


def test_password_is_never_returned():
    _olt(password="secreta")
    assert "secreta" not in client.get("/olts").text


def test_connection_test_open_and_closed_port():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = srv.getsockname()[1]
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        up = _olt("up", "127.0.0.1", port=open_port)
        down = _olt("down", "127.0.0.1", port=closed_port)
        assert client.post(f"/olts/{up['id']}/test").json()["reachable"] is True
        assert client.post(f"/olts/{down['id']}/test").json()["reachable"] is False
        snmp = _olt("snmp", "127.0.0.1", protocol="snmp")
        assert client.post(f"/olts/{snmp['id']}/test").json()["reachable"] is None
    finally:
        srv.close()


def test_delete_olt_blocked_while_onus_authorized():
    olt = client.post("/olts", json={"name": "m", "vendor": "mock", "host": "10.9.9.9"}).json()
    plan = client.post("/speed-plans", json={"name": "p", "up_kbps": 1000, "down_kbps": 1000}).json()
    mock_add_unauthorized("10.9.9.9", "SN1", "0/1")
    onu = client.post(f"/olts/{olt['id']}/scan").json()[0]
    client.post(f"/onus/{onu['id']}/authorize", json={"vlan": 250, "speed_plan_id": plan["id"], "customer_name": "c"})
    assert client.delete(f"/olts/{olt['id']}").status_code == 409
    client.delete(f"/onus/{onu['id']}")
    assert client.delete(f"/olts/{olt['id']}").status_code == 204
    assert client.get("/olts").json() == []


def test_ui_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "OLT Management" in r.text


# ---- Script MikroTik --------------------------------------------------------
def _script(olt, **overrides):
    return client.post(f"/olts/{olt['id']}/mikrotik-script", json={**MK, **overrides})


def test_script_contains_expected_routeros():
    olt = _olt()
    r = _script(olt)
    assert r.status_code == 200, r.text
    s = r.json()["script"]
    assert "vlan-id=250" in s and 'interface="ether2"' in s
    assert "address=172.20.5.1/28" in s
    assert "src-address-list=onu-auth-system" in s and "dst-address=172.20.5.2" in s
    assert "protocol=tcp dst-port=22" in s            # ssh
    assert "action=masquerade" in s and "dst-address=172.20.0.0/16" not in s
    assert "dst-address=172.20.5.0/28" in s
    assert s.rstrip().endswith("/ping 172.20.5.2 count=3")
    assert "/interface bridge vlan add" not in s       # sin bridge
    assert r.json()["notes"]


def test_script_is_idempotent_style_and_never_deletes():
    s = _script(_olt()).json()["script"]
    assert s.count(":if ([:len") >= 5                  # cada cambio se guarda con una comprobación previa
    # Solo se permiten comandos "add"; nada que borre, modifique o desactive configuración existente.
    # (":set vlanRef ..." es una variable local del script, no un cambio en el router.)
    destructive = re.compile(r"/[a-z\- ]+ (remove|set|disable|enable|unset|reset-configuration)\b|/system\b|/export\b")
    for line in s.splitlines():
        if not line.lstrip().startswith("#"):
            assert not destructive.search(line), line


def test_script_protocols_and_options():
    telnet = _script(_olt("t", "172.20.5.3", protocol="telnet")).json()["script"]
    assert "protocol=tcp dst-port=23" in telnet
    snmp = _script(_olt("s", "172.20.5.4", protocol="snmp")).json()["script"]
    assert "protocol=udp dst-port=161" in snmp
    bridged = _script(_olt("b", "172.20.5.5"), bridge="bridge1").json()["script"]
    assert "/interface bridge vlan add" in bridged and 'tagged="bridge1,ether2"' in bridged
    plain = _script(_olt("n", "172.20.5.6"), masquerade=False)
    assert "masquerade" not in plain.json()["script"]
    assert any("ruta" in n for n in plain.json()["notes"])


def test_script_rejects_inconsistent_networks():
    olt = _olt()
    assert _script(olt, gateway_ip="172.20.9.1").status_code == 400            # OLT fuera de la red
    assert _script(olt, gateway_ip="172.20.5.2").status_code == 400            # gateway = OLT
    assert _script(olt, system_ip="172.20.5.10").status_code == 400            # sistema en la misma red
    assert _script(_olt("host", "olt.local")).status_code == 400               # OLT con nombre, no IP


def test_script_rejects_injection():
    olt = _olt()
    for bad in ('ether2"; /system reset-configuration; "', "ether2\n/system reset", "ether2 $x"):
        assert _script(olt, trunk_interface=bad).status_code == 422
    assert _script(olt, bridge='b"x').status_code == 422
