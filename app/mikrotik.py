"""Genera el script de RouterOS que conecta el sistema con la gestión de una OLT a través del MikroTik.

El script SOLO se genera: el sistema nunca se conecta al MikroTik ni lo ejecuta. Lo revisas y lo
pegas tú en el router. Está escrito para poder correrse varias veces sin duplicar nada.

Qué hace en el router:
  1. Crea (si no existe) la VLAN de gestión de la OLT sobre el puerto/bridge indicado.
  2. Le pone la IP de gateway de esa red.
  3. Permite en el firewall SOLO desde el sistema hacia la OLT (SSH/Telnet/SNMP/ping).
  4. Opcional: masquerade hacia la OLT, para que la OLT responda al gateway y no necesite ruta de vuelta.
  5. Hace un ping de prueba a la OLT.
"""
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .adapters.base import InvalidRequest

_UNSAFE = re.compile(r"[^A-Za-z0-9 _.\-]")


def _clean(text: str) -> str:
    """Todo lo que va a un comentario del router se limpia: nada de comillas, saltos de línea ni $."""
    return _UNSAFE.sub("", text)[:60]


@dataclass
class MikrotikParams:
    olt_name: str
    olt_ip: str
    olt_protocol: str       # ssh | telnet | snmp
    olt_port: int
    system_ip: str
    trunk_interface: str    # puerto del MikroTik que va hacia la OLT (o hacia el switch que la lleva)
    vlan_id: int
    gateway_ip: str         # IP que tendrá el MikroTik en la VLAN de gestión
    prefix: int
    bridge: str = ""        # si el puerto está en un bridge con vlan-filtering, nombre del bridge
    masquerade: bool = True


def generate_script(p: MikrotikParams) -> tuple[str, list[str]]:
    """Devuelve (script, notas). Lanza InvalidRequest si los datos no cuadran."""
    try:
        olt = ipaddress.IPv4Address(p.olt_ip)
    except ValueError:
        raise InvalidRequest(f"La OLT debe estar registrada con una IP (no con nombre): {p.olt_ip!r}")
    gateway = ipaddress.IPv4Address(p.gateway_ip)
    system = ipaddress.IPv4Address(p.system_ip)
    net = ipaddress.ip_interface(f"{gateway}/{p.prefix}").network

    if olt not in net:
        raise InvalidRequest(f"La OLT ({olt}) no está en la red {net}; revisa gateway y prefijo")
    if gateway == olt:
        raise InvalidRequest("El gateway no puede ser la misma IP que la OLT")
    if gateway in (net.network_address, net.broadcast_address):
        raise InvalidRequest(f"El gateway {gateway} no es una IP usable de {net}")
    if system in net:
        raise InvalidRequest(
            f"El sistema ({system}) está dentro de {net}, la misma red de la OLT: "
            "no necesita pasar por el MikroTik, solo que su puerto pertenezca a esa VLAN"
        )

    tag = "onu-auth:" + re.sub(r"[^a-z0-9]+", "-", p.olt_name.lower()).strip("-")
    label = _clean(p.olt_name)
    default_name = f"vlan{p.vlan_id}-olt-mgmt"
    vlan_parent = p.bridge or p.trunk_interface

    # Puertos que hay que abrir según cómo habla el sistema con esta OLT
    rules = [("icmp", None, "ping")]
    if p.olt_protocol in ("ssh", "telnet"):
        rules.append(("tcp", str(p.olt_port), p.olt_protocol))
    if p.olt_protocol == "snmp":
        rules.append(("udp", str(p.olt_port if p.olt_port else 161), "snmp"))

    L: list[str] = []
    add = L.append
    add(f"# ===== Conexión sistema <-> OLT {label} a través del MikroTik =====")
    add(f"# Generado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC por OLT Management.")
    add("# REVÍSALO antes de aplicarlo. Primero haz un respaldo:  /system backup save name=antes-olt")
    add(f"# Sistema: {system}   OLT: {olt}   Red de gestión: {net}   VLAN: {p.vlan_id}")
    add("")
    add("# 1) VLAN de gestión (se reutiliza si ya existe una con ese VLAN ID sobre ese puerto)")
    add(f':local vlanRef [/interface vlan find where vlan-id={p.vlan_id} and interface="{vlan_parent}"]')
    add(":if ([:len $vlanRef] = 0) do={")
    add(f'  /interface vlan add name="{default_name}" vlan-id={p.vlan_id} interface="{vlan_parent}" comment="{tag}"')
    add(f'  :set vlanRef [/interface vlan find where name="{default_name}"]')
    add("}")
    add(":local vlanName [/interface vlan get $vlanRef name]")
    add("")
    if p.bridge:
        add("# 1b) El puerto está en un bridge con vlan-filtering: la VLAN debe viajar etiquetada por él")
        add(f':if ([:len [/interface bridge vlan find where bridge="{p.bridge}" and vlan-ids={p.vlan_id}]] = 0) do={{')
        add(
            f'  /interface bridge vlan add bridge="{p.bridge}" tagged="{p.bridge},{p.trunk_interface}" '
            f'vlan-ids={p.vlan_id} comment="{tag}"'
        )
        add("} else={")
        add(f'  :put "AVISO: ya existe una entrada de bridge vlan para {p.vlan_id}; revisa que {p.trunk_interface} esté en tagged"')
        add("}")
        add("")
    add("# 2) IP del MikroTik en la red de gestión de la OLT")
    add(f':if ([:len [/ip address find where address="{gateway}/{p.prefix}"]] = 0) do={{')
    add(f'  /ip address add address={gateway}/{p.prefix} interface=$vlanName comment="{tag}"')
    add("} else={")
    add(f'  :put "AVISO: {gateway}/{p.prefix} ya existe en el router; no se duplicó"')
    add("}")
    add("")
    add("# 3) Firewall: solo el sistema puede llegar a la OLT, y solo a los puertos de gestión")
    add(f':if ([:len [/ip firewall address-list find where list="onu-auth-system" and address="{system}"]] = 0) do={{')
    add(f'  /ip firewall address-list add list=onu-auth-system address={system} comment="{tag}"')
    add("}")
    for proto, port, name in rules:
        port_part = f" dst-port={port}" if port else ""
        add(f':if ([:len [/ip firewall filter find where comment="{tag}:{name}"]] = 0) do={{')
        add(
            f"  /ip firewall filter add chain=forward action=accept place-before=0 protocol={proto}{port_part} "
            f'src-address-list=onu-auth-system dst-address={olt} comment="{tag}:{name}"'
        )
        add("}")
    add("")
    if p.masquerade:
        add("# 4) Masquerade hacia la OLT: la OLT ve al MikroTik como origen, no necesita ruta de vuelta")
        add(f':if ([:len [/ip firewall nat find where comment="{tag}:nat"]] = 0) do={{')
        add(
            f"  /ip firewall nat add chain=srcnat action=masquerade src-address={system} "
            f'dst-address={net} out-interface=$vlanName comment="{tag}:nat"'
        )
        add("}")
        add("")
    add("# 5) Prueba")
    add(f"/ping {olt} count=3")

    notes = [
        f"El sistema ({system}) debe tener al MikroTik como gateway para llegar a {net}.",
        f"La OLT debe tener la IP {olt} en la VLAN {p.vlan_id} y permitir {p.olt_protocol.upper()} desde el MikroTik.",
        "Las reglas del firewall se insertan al principio de la cadena forward. Se asume que ya tienes "
        "una regla que acepta el tráfico established/related (la configuración por defecto la trae).",
    ]
    if p.masquerade:
        notes.append("Con masquerade la OLT verá las conexiones como originadas en el gateway; no hace falta ruta de vuelta en la OLT.")
    else:
        notes.append(
            f"Sin masquerade, la OLT necesita una ruta hacia {system} vía {gateway}. "
            "En tu backup de la TP-Link no aparece ninguna ruta/gateway por defecto: revisa que exista."
        )
    if not p.bridge:
        notes.append(
            "Si el puerto indicado pertenece a un bridge con vlan-filtering, vuelve a generar el script indicando el bridge."
        )
    return "\n".join(L) + "\n", notes
