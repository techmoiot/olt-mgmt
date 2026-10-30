import re
from pathlib import Path

from app.adapters.mock import mock_add_unauthorized
from tests.helpers import AuthedClient
from app.main import app

client = AuthedClient(app)
STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


# ---- Páginas ----------------------------------------------------------------
def test_every_page_is_csp_safe_and_references_existing_files():
    pages = list(STATIC.glob("*.html"))
    assert len(pages) >= 12
    for page in pages:
        html = page.read_text()
        assert "style=" not in html and not re.search(r"\son\w+=", html), page.name
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), f"{page.name}: script en línea"
        for ref in re.findall(r'(?:src|href)="/static/([^"?#]+)', html):
            assert (STATIC / ref).exists(), f"{page.name} referencia {ref} que no existe"


def test_page_scripts_match_page_names():
    for page in STATIC.glob("*.html"):
        m = re.search(r'data-page="([^"]+)"', page.read_text())
        if m:
            assert m.group(1) == page.stem and (STATIC / "js" / f"{page.stem}.js").exists()


# ---- Zonas y NAP ------------------------------------------------------------
def test_zones_and_naps():
    z = client.post("/zones", json={"name": "Canajal"})
    assert z.status_code == 201
    assert client.post("/zones", json={"name": "Canajal"}).status_code == 409
    assert client.post("/zones", json={"name": 'x"; rm'}).status_code == 422
    n = client.post("/naps", json={"name": "NAP-01", "zone_id": z.json()["id"]})
    assert n.status_code == 201
    assert client.post("/naps", json={"name": "NAP-02", "zone_id": 999}).status_code == 404
    assert client.delete(f"/zones/{z.json()['id']}").status_code == 409  # tiene un NAP
    assert client.delete(f"/naps/{n.json()['id']}").status_code == 204
    assert client.delete(f"/zones/{z.json()['id']}").status_code == 204


# ---- Autorización con el formulario completo --------------------------------
def _pending(serial="TPLG00000009"):
    olt = client.post("/olts", json={"name": "olt-x", "vendor": "mock", "host": "10.0.0.7", "model": "H675",
                                     "software_version": "1.0.9", "pon_type": "gpon"}).json()
    mock_add_unauthorized("10.0.0.7", serial, "0/0/4")
    return olt, client.post(f"/olts/{olt['id']}/scan").json()[0]


def test_olt_has_model_version_and_pon_type():
    olt, _ = _pending()
    assert (olt["model"], olt["software_version"], olt["pon_type"]) == ("H675", "1.0.9", "gpon")
    assert client.post("/olts", json={"name": "o2", "vendor": "mock", "host": "10.0.0.8", "pon_type": "xgs"}).status_code == 422


def test_profiles_endpoint():
    olt, _ = _pending()
    r = client.get(f"/olts/{olt['id']}/profiles").json()
    assert r["supported"] and r["line_profiles"] and r["up_profiles"] and r["down_profiles"]


def test_authorize_with_profiles_and_customer_data():
    olt, onu = _pending()
    z = client.post("/zones", json={"name": "Centro"}).json()
    nap = client.post("/naps", json={"name": "NAP-9", "zone_id": z["id"]}).json()
    r = client.post(f"/onus/{onu['id']}/authorize", json={
        "customer_name": "Juan Pérez", "customer_ref": "C-100", "customer_phone": "5555-1234",
        "customer_address": "Zona 1", "onu_model": "HUAWEI-ONU-WIFI6", "config_type": "bridge",
        "vlan": 251, "svlan": 1084, "line_profile": "P4-V1084 - MAPPING MODE vlan",
        "up_profile": "ADMINOLT_100M_U - SUBIDA", "down_profile": "ADMINOLT_100M_D - DESCARGA",
        "zone_id": z["id"], "nap_id": nap["id"], "comments": "instalado hoy",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "authorized" and j["speed_plan_id"] is None and j["olt_name"] == "olt-x"
    assert (j["svlan"], j["config_type"], j["zone_id"], j["nap_id"]) == (1084, "bridge", z["id"], nap["id"])
    assert j["down_profile"].startswith("ADMINOLT_100M_D") and j["customer_phone"] == "5555-1234"
    assert client.get(f"/onus/{onu['id']}").json()["customer_name"] == "Juan Pérez"


def test_authorize_without_speed_limit_is_allowed():
    _, onu = _pending()
    r = client.post(f"/onus/{onu['id']}/authorize", json={"customer_name": "Sin límite", "vlan": 251})
    assert r.status_code == 200 and r.json()["speed_plan_id"] is None


def test_authorize_rejects_injection_and_bad_refs():
    _, onu = _pending()
    base = {"customer_name": "Ana", "vlan": 251}
    for bad in ({"customer_name": 'Ana"\nreboot'}, {"line_profile": "x'; y"}, {"comments": "a\x00b"}, {"vlan": 5000}, {"config_type": "otro"}):
        assert client.post(f"/onus/{onu['id']}/authorize", json={**base, **bad}).status_code == 422, bad
    assert client.post(f"/onus/{onu['id']}/authorize", json={**base, "zone_id": 99}).status_code == 404
    assert client.post(f"/onus/{onu['id']}/authorize", json={**base, "speed_plan_id": 99}).status_code == 404
    assert client.get(f"/onus/{onu['id']}").json()["status"] == "pending"  # nada se aplicó


# ---- Dashboard --------------------------------------------------------------
def test_dashboard_counts():
    _, onu = _pending()
    d = client.get("/dashboard").json()
    assert d["pending"] == 1 and d["authorized"] == 0 and d["olts"] == 1
    client.post(f"/onus/{onu['id']}/authorize", json={"customer_name": "Z", "vlan": 251})
    d = client.get("/dashboard").json()
    assert d["pending"] == 0 and d["authorized"] == 1 and d["authorized_today"] == 1 and d["authorized_month"] == 1
    client.post(f"/onus/{onu['id']}/suspend")
    assert client.get("/dashboard").json()["suspended"] == 1


# ---- Catálogo de marcas y modelos ------------------------------------------
def test_catalog_lists_brands_with_models_and_implementation_state():
    cat = {c["vendor"]: c for c in client.get("/catalog").json()}
    assert {"tplink", "zte", "vsol", "btpon", "huawei"} <= set(cat)
    assert "DS-P7001-08" in cat["tplink"]["models"] and cat["tplink"]["implemented"] is True
    assert cat["huawei"]["implemented"] is False and cat["btpon"]["models"] == []


def test_every_catalog_brand_can_be_registered_and_unimplemented_ones_answer_501():
    for i, v in enumerate(("zte", "vsol", "btpon", "huawei")):
        r = client.post("/olts", json={"name": f"o-{v}", "vendor": v, "model": "X", "host": f"10.1.0.{i + 1}"})
        assert r.status_code == 201, (v, r.text)
        scan = client.post(f"/olts/{r.json()['id']}/scan")
        assert scan.status_code == 501 and "aún no está implementado" in scan.json()["detail"]
    assert client.post("/olts", json={"name": "raro", "vendor": "marcax", "host": "10.1.0.9"}).status_code == 400
