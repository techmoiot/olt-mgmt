import re
import socket

from tests.helpers import AuthedClient

from app.adapters.mock import mock_add_unauthorized
from app.db import SessionLocal
from app.main import app
from app.models import Olt
from app.vault import decrypt

client = AuthedClient(app)

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


def test_add_olt_with_all_its_data():
    o = _olt(
        model="DS-P7001-08", cli_protocol="telnet", ssh_port=2222, telnet_port=2323, snmp_port=1161,
        snmp_read_community="lectura", snmp_write_community="escritura", username="admin", password="clave",
    )
    assert (o["ssh_port"], o["telnet_port"], o["snmp_port"], o["cli_protocol"]) == (2222, 2323, 1161, "telnet")
    assert o["username"] == "admin" and o["has_snmp_read"] and o["has_snmp_write"]


def test_default_ports():
    o = _olt("a", "10.0.0.1")
    assert (o["ssh_port"], o["telnet_port"], o["snmp_port"], o["cli_protocol"]) == (22, 23, 161, "ssh")
    assert not o["has_snmp_read"] and not o["has_snmp_write"]


def test_add_olt_rejects_bad_input():
    base = {"name": "x", "vendor": "tplink", "host": "10.0.0.1"}
    r = client.post("/olts", json={**base, "vendor": "inventada"})
    assert r.status_code == 400 and "tplink" in r.json()["detail"]
    _olt("dup")
    assert client.post("/olts", json={**base, "name": "dup"}).status_code == 409
    assert client.post("/olts", json={**base, "cli_protocol": "ftp"}).status_code == 422
    assert client.post("/olts", json={**base, "ssh_port": 0}).status_code == 422
    assert client.post("/olts", json={**base, "snmp_read_community": "a\nb"}).status_code == 422
    # nombre con salto de línea (se usa en comentarios del script): rechazado
    assert client.post("/olts", json={**base, "name": "a\n/system reset"}).status_code == 422
    assert client.post("/olts", json={**base, "gateway_id": 999}).status_code == 404


def test_secrets_are_encrypted_and_never_returned():
    # host local: la prueba de conexión falla al instante en vez de esperar un timeout de red
    o = _olt(host="127.0.0.1", password="Clave-Secreta-1", snmp_read_community="com-lectura",
             snmp_write_community="com-escritura")
    for secret in ("Clave-Secreta-1", "com-lectura", "com-escritura"):
        assert secret not in client.get("/olts").text
        assert secret not in client.post("/olts/%d/test" % o["id"]).text
    with SessionLocal() as db:
        row = db.get(Olt, o["id"])
        # en la base no están en claro...
        assert "Clave-Secreta-1" not in row.password_enc and "com-escritura" not in row.snmp_write_enc
        # ...pero se recuperan para usarlos con la OLT
        assert decrypt(row.password_enc) == "Clave-Secreta-1"
        assert decrypt(row.snmp_read_enc) == "com-lectura"
        assert decrypt(row.snmp_write_enc) == "com-escritura"


def test_connection_test_reports_each_service():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = srv.getsockname()[1]
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        olt = _olt("probe", "127.0.0.1", ssh_port=open_port, telnet_port=closed_port, snmp_port=1161)
        checks = {c["service"]: c for c in client.post(f"/olts/{olt['id']}/test").json()["checks"]}
        assert checks["ssh"]["reachable"] is True and checks["ssh"]["port"] == open_port
        assert checks["telnet"]["reachable"] is False
        assert checks["snmp"]["reachable"] is None and checks["snmp"]["port"] == 1161
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
    assert r.status_code == 200 and "Ritsuko" in r.text


# ---- Script MikroTik (VLAN + firewall) --------------------------------------
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
    assert "protocol=tcp dst-port=22" in s              # ssh por defecto
    assert "protocol=udp" not in s                       # sin comunidad SNMP no se abre SNMP
    assert "action=masquerade" in s and "dst-address=172.20.5.0/28" in s
    assert s.rstrip().endswith("/ping 172.20.5.2 count=3")
    assert "/interface bridge vlan add" not in s         # sin bridge
    assert r.json()["notes"]


def test_script_opens_only_the_ports_the_olt_uses():
    snmp = _script(_olt("s", "172.20.5.4", snmp_read_community="public", snmp_port=1161)).json()["script"]
    assert "protocol=udp dst-port=1161" in snmp
    telnet = _script(_olt("t", "172.20.5.3", cli_protocol="telnet", telnet_port=2323)).json()["script"]
    assert "protocol=tcp dst-port=2323" in telnet and "dst-port=22 " not in telnet


def test_script_bridge_and_masquerade_options():
    bridged = _script(_olt("b", "172.20.5.5"), bridge="bridge1").json()["script"]
    assert "/interface bridge vlan add" in bridged and 'tagged="bridge1,ether2"' in bridged
    plain = _script(_olt("n", "172.20.5.6"), masquerade=False)
    assert "masquerade" not in plain.json()["script"]
    assert any("ruta" in n for n in plain.json()["notes"])


def test_script_only_adds_never_modifies_or_deletes():
    s = _script(_olt()).json()["script"]
    assert s.count(":if ([:len") >= 5                    # cada cambio se guarda con una comprobación previa
    # ":set vlanRef ..." es una variable local del script, no un cambio en el router.
    destructive = re.compile(r"/[a-z\- ]+ (remove|set|disable|enable|unset|reset-configuration)\b|/system\b|/export\b")
    for line in s.splitlines():
        if not line.lstrip().startswith("#"):
            assert not destructive.search(line), line


def test_script_needs_system_ip_without_vpn():
    olt = _olt()
    assert _script(olt, system_ip=None).status_code == 400


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
