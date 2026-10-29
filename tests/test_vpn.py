import os
import re
import subprocess
import sys
from base64 import b64decode, b64encode
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

from app import vpn
from app.adapters.base import InvalidRequest
from app.db import SessionLocal
from app.main import app
from app.models import Gateway
from app.vault import decrypt

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent


def _gw(name="Sede-Norte", **kw):
    r = client.post("/gateways", json={"name": name, "endpoint": "mk.ejemplo.net", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _server_private(gw_id: int) -> str:
    with SessionLocal() as db:
        return decrypt(db.get(Gateway, gw_id).server_private_enc)


def _router_key() -> str:
    return vpn.generate_keypair()[1]


# ---- Alta de gateways y claves ----------------------------------------------
def test_create_gateway_assigns_tunnel_and_keys():
    gw = _gw()
    assert (gw["tunnel_net"], gw["router_ip"], gw["server_ip"]) == ("10.99.0.0/30", "10.99.0.1", "10.99.0.2")
    assert gw["listen_port"] == 13231 and gw["router_public_key"] == "" and gw["vpn_ready"] is False
    assert len(b64decode(gw["server_public_key"])) == 32
    # el segundo gateway recibe el siguiente /30 libre
    assert _gw("Sede-Sur")["tunnel_net"] == "10.99.0.4/30"


def test_server_keypair_is_valid_and_private_key_never_in_api():
    gw = _gw()
    priv_b64 = _server_private(gw["id"])
    priv = X25519PrivateKey.from_private_bytes(b64decode(priv_b64))
    derived = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert b64encode(derived).decode() == gw["server_public_key"]
    for text in (client.get("/gateways").text, client.post(f"/gateways/{gw['id']}/vpn-script", json={}).text):
        assert priv_b64 not in text
    with SessionLocal() as db:
        assert priv_b64 not in db.get(Gateway, gw["id"]).server_private_enc  # cifrada en la base


def test_gateway_rejects_bad_tunnel_nets_and_duplicates():
    _gw("Con-Red-Fija", tunnel_net="10.50.0.0/30")
    assert client.post("/gateways", json={"name": "x", "endpoint": "a.b", "tunnel_net": "10.50.0.0/30"}).status_code == 400  # solapa
    assert client.post("/gateways", json={"name": "y", "endpoint": "a.b", "tunnel_net": "8.8.8.0/30"}).status_code == 400    # pública
    assert client.post("/gateways", json={"name": "z", "endpoint": "a.b", "tunnel_net": "10.60.0.0/31"}).status_code == 400   # muy chica
    assert client.post("/gateways", json={"name": "Sede-Norte", "endpoint": "a.b"}).status_code == 201
    assert client.post("/gateways", json={"name": "Sede-Norte", "endpoint": "a.b"}).status_code == 409   # duplicado
    assert client.post("/gateways", json={"name": "bad\nname", "endpoint": "a.b"}).status_code == 422


# ---- Script VPN del MikroTik ------------------------------------------------
def test_vpn_script_builds_mikrotik_side():
    gw = _gw()
    r = client.post(f"/gateways/{gw['id']}/vpn-script", json={})
    assert r.status_code == 200, r.text
    s = r.json()["script"]
    assert f'/interface wireguard add name="wg-onuauth-{gw["id"]}" listen-port=13231' in s
    assert "/ip address add address=10.99.0.1/30" in s
    assert f'public-key="{gw["server_public_key"]}"' in s and "allowed-address=10.99.0.2/32" in s
    assert "chain=input action=accept place-before=0 protocol=udp dst-port=13231" in s
    assert ':put ("CLAVE PUBLICA DEL MIKROTIK: "' in s
    assert "src-address=" not in s and any("cualquier origen" in n for n in r.json()["notes"])


def test_vpn_script_can_restrict_to_server_public_ip():
    gw = _gw()
    s = client.post(f"/gateways/{gw['id']}/vpn-script", json={"server_public_ip": "203.0.113.9"}).json()["script"]
    assert "dst-port=13231 src-address=203.0.113.9" in s


def test_vpn_script_only_adds_and_is_rerunnable():
    s = client.post(f"/gateways/{_gw()['id']}/vpn-script", json={}).json()["script"]
    assert s.count(":if ([:len") >= 4
    destructive = re.compile(r"/[a-z\- ]+ (remove|set|disable|enable|unset|reset-configuration)\b|/system\b|/export\b")
    for line in s.splitlines():
        if not line.lstrip().startswith("#"):
            assert not destructive.search(line), line


# ---- Clave del MikroTik y configuración del servidor -------------------------
def test_router_key_validation_and_ready_flag():
    gw = _gw()
    for bad in ("corta", "A" * 44, _router_key() + "\n/system reset"):
        assert client.put(f"/gateways/{gw['id']}/router-key", json={"public_key": bad}).status_code == 422
    r = client.put(f"/gateways/{gw['id']}/router-key", json={"public_key": _router_key()})
    assert r.status_code == 200 and r.json()["vpn_ready"] is True


def test_server_config_needs_router_key_then_has_everything():
    gw = _gw()
    olt = client.post("/olts", json={"name": "O1", "vendor": "tplink", "host": "172.20.5.2", "gateway_id": gw["id"]}).json()
    with SessionLocal() as db:
        g = db.get(Gateway, gw["id"])
        with pytest.raises(InvalidRequest, match="clave pública del MikroTik"):
            vpn.server_config(g, list(g.olts))

    rk = _router_key()
    client.put(f"/gateways/{gw['id']}/router-key", json={"public_key": rk})
    with SessionLocal() as db:
        g = db.get(Gateway, gw["id"])
        conf = vpn.server_config(g, list(g.olts))
    assert f"PrivateKey = {_server_private(gw['id'])}" in conf
    assert "Address = 10.99.0.2/30" in conf and f"PublicKey = {rk}" in conf
    assert "Endpoint = mk.ejemplo.net:13231" in conf
    assert "AllowedIPs = 10.99.0.1/32, 172.20.5.2/32" in conf and "PersistentKeepalive = 25" in conf
    assert olt["gateway_id"] == gw["id"]


def test_wg_server_config_tool_end_to_end():
    gw = _gw()
    env = {**os.environ}
    run = lambda gid: subprocess.run(  # noqa: E731
        [sys.executable, "-I", str(ROOT / "tools" / "wg_server_config.py"), str(gid)],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    # sin clave del MikroTik: falla con un mensaje claro
    r = run(gw["id"])
    assert r.returncode == 1 and "clave pública del MikroTik" in r.stderr
    client.put(f"/gateways/{gw['id']}/router-key", json={"public_key": _router_key()})
    r = run(gw["id"])
    assert r.returncode == 0, r.stderr
    assert "[Interface]" in r.stdout and f"PrivateKey = {_server_private(gw['id'])}" in r.stdout
    assert run(9999).returncode == 1


# ---- OLTs que llegan por VPN -------------------------------------------------
def test_olt_via_vpn_uses_tunnel_ip_and_needs_no_system_ip():
    gw = _gw()
    olt = client.post("/olts", json={
        "name": "O-vpn", "vendor": "tplink", "host": "172.20.5.2", "gateway_id": gw["id"],
    }).json()
    body = {"trunk_interface": "ether2", "vlan_id": 250, "gateway_ip": "172.20.5.1", "prefix": 28}
    r = client.post(f"/olts/{olt['id']}/mikrotik-script", json=body)
    assert r.status_code == 200, r.text
    s = r.json()["script"]
    assert "address=10.99.0.2" in s and "src-address=10.99.0.2" in s    # origen = el servidor dentro del túnel
    assert any("túnel" in n for n in r.json()["notes"])


def test_olt_via_vpn_requires_an_ip_not_a_hostname():
    gw = _gw()
    r = client.post("/olts", json={"name": "O", "vendor": "tplink", "host": "olt.local", "gateway_id": gw["id"]})
    assert r.status_code == 400


def test_gateway_delete_blocked_while_olts_attached():
    gw = _gw()
    olt = client.post("/olts", json={"name": "O", "vendor": "tplink", "host": "172.20.5.2", "gateway_id": gw["id"]}).json()
    assert client.delete(f"/gateways/{gw['id']}").status_code == 409
    assert client.delete(f"/olts/{olt['id']}").status_code == 204
    assert client.delete(f"/gateways/{gw['id']}").status_code == 204
