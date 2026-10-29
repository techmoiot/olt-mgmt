"""VPN WireGuard entre este servidor y un MikroTik (gateway).

Cuando el servidor no está conectado físicamente al MikroTik, llega a las OLTs por un túnel:

    servidor (10.99.0.2) <== WireGuard ==> MikroTik (10.99.0.1) --VLAN de gestión--> OLT

Flujo de alta (la clave privada del servidor nunca sale del sistema):
  1. POST /gateways               -> el sistema genera el par de claves del servidor.
  2. POST /gateways/{id}/vpn-script -> script de RouterOS: el MikroTik crea su interfaz WireGuard
                                      y IMPRIME su clave pública.
  3. PUT  /gateways/{id}/router-key -> pegas esa clave pública en el sistema.
  4. tools/wg_server_config.py {id} -> genera /etc/wireguard/onugwN.conf para el servidor.
"""
import ipaddress
import re
from base64 import b64encode
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .adapters.base import InvalidRequest
from .models import Gateway, Olt
from .vault import decrypt


def generate_keypair() -> tuple[str, str]:
    """(privada, pública) en el formato base64 de WireGuard."""
    priv = X25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64encode(raw_priv).decode(), b64encode(raw_pub).decode()


def tunnel_ips(net: ipaddress.IPv4Network) -> tuple[str, str]:
    """(IP del MikroTik, IP del servidor): las dos primeras direcciones usables."""
    hosts = list(net.hosts())
    if len(hosts) < 2:
        raise InvalidRequest(f"La red del túnel {net} es muy chica: necesita al menos 2 IPs usables (usa /30 o mayor)")
    return str(hosts[0]), str(hosts[1])


def next_free_tunnel_net(used: list[str]) -> str:
    """Siguiente /30 libre dentro de 10.99.0.0/16."""
    taken = [ipaddress.ip_network(u) for u in used]
    for candidate in ipaddress.ip_network("10.99.0.0/16").subnets(new_prefix=30):
        if not any(candidate.overlaps(t) for t in taken):
            return str(candidate)
    raise InvalidRequest("No quedan redes de túnel libres en 10.99.0.0/16")


def parse_tunnel_net(text: str, used: list[str]) -> ipaddress.IPv4Network:
    try:
        net = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise InvalidRequest(f"Red de túnel inválida {text!r}: {exc}")
    if net.version != 4 or not net.is_private or net.prefixlen > 30:
        raise InvalidRequest("La red del túnel debe ser IPv4 privada, de /30 o mayor")
    for u in used:
        if net.overlaps(ipaddress.ip_network(u)):
            raise InvalidRequest(f"La red {net} se solapa con la de otro gateway ({u})")
    return net


def _tag(gw: Gateway) -> str:
    return "onu-auth-vpn:" + re.sub(r"[^a-z0-9]+", "-", gw.name.lower()).strip("-")


def wg_interface_router(gw: Gateway) -> str:
    return f"wg-onuauth-{gw.id}"


def generate_vpn_script(gw: Gateway, server_public_ip: str | None = None) -> tuple[str, list[str]]:
    """Script de RouterOS 7.x que deja listo el lado MikroTik del túnel. Solo agrega, es re-ejecutable."""
    ifname = wg_interface_router(gw)
    tag = _tag(gw)
    prefix = ipaddress.ip_network(gw.tunnel_net).prefixlen
    src = f" src-address={server_public_ip}" if server_public_ip else ""

    L = [
        f"# ===== VPN WireGuard: MikroTik <-> servidor OLT Management (gateway {gw.name}) =====",
        f"# Generado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. REQUIERE RouterOS 7.x (v6 no trae WireGuard).",
        "# REVÍSALO antes de aplicarlo. Primero haz un respaldo:  /system backup save name=antes-vpn",
        "",
        "# 1) Interfaz WireGuard (el MikroTik genera su propia clave privada, que nunca sale de él)",
        f':if ([:len [/interface wireguard find where name="{ifname}"]] = 0) do={{',
        f'  /interface wireguard add name="{ifname}" listen-port={gw.listen_port} comment="{tag}"',
        "}",
        "",
        "# 2) IP del MikroTik dentro del túnel",
        f':if ([:len [/ip address find where address="{gw.router_ip}/{prefix}"]] = 0) do={{',
        f'  /ip address add address={gw.router_ip}/{prefix} interface="{ifname}" comment="{tag}"',
        "} else={",
        f'  :put "AVISO: {gw.router_ip}/{prefix} ya existe en el router; no se duplicó"',
        "}",
        "",
        "# 3) El servidor como único par permitido",
        f':if ([:len [/interface wireguard peers find where interface="{ifname}" and public-key="{gw.server_public_key}"]] = 0) do={{',
        f'  /interface wireguard peers add interface="{ifname}" public-key="{gw.server_public_key}" '
        f'allowed-address={gw.server_ip}/32 comment="{tag}"',
        "}",
        "",
        "# 4) Firewall: aceptar el túnel WireGuard entrante (WireGuard ignora paquetes sin clave válida)",
        f':if ([:len [/ip firewall filter find where comment="{tag}:wg-in"]] = 0) do={{',
        f'  /ip firewall filter add chain=input action=accept place-before=0 protocol=udp '
        f'dst-port={gw.listen_port}{src} comment="{tag}:wg-in"',
        "}",
        "",
        "# 5) COPIA ESTA LÍNEA: es la clave pública del MikroTik que hay que pegar en el sistema",
        f':put ("CLAVE PUBLICA DEL MIKROTIK: " . [/interface wireguard get [find where name="{ifname}"] public-key])',
    ]
    notes = [
        f"El MikroTik tiene que ser alcanzable desde el servidor en {gw.endpoint}:{gw.listen_port}/UDP "
        "(IP pública o DDNS, o redirigir ese puerto si está detrás de otro router).",
        "Después de correrlo, pega la clave pública que imprime en el sistema (PUT /gateways/{id}/router-key).",
        "Falta aún enlazar cada OLT con este MikroTik: el script de la OLT (botón 'Script MikroTik' de cada OLT) "
        "crea la VLAN de gestión y las reglas de firewall para el servidor.",
    ]
    if not server_public_ip:
        notes.append(
            "El puerto UDP queda abierto a cualquier origen. Es lo normal en WireGuard, pero si el servidor "
            "tiene IP pública fija, genera el script indicándola y el MikroTik solo aceptará esa."
        )
    return "\n".join(L) + "\n", notes


def server_config(gw: Gateway, olts: list[Olt]) -> str:
    """Contenido de /etc/wireguard/onugwN.conf. CONTIENE LA CLAVE PRIVADA: no se expone por la API."""
    if not gw.router_public_key:
        raise InvalidRequest("Falta la clave pública del MikroTik: corre el script VPN y pégala con /gateways/{id}/router-key")
    prefix = ipaddress.ip_network(gw.tunnel_net).prefixlen
    allowed = [f"{gw.router_ip}/32"]
    for o in olts:
        try:
            ipaddress.IPv4Address(o.host)
        except ValueError:
            raise InvalidRequest(f"La OLT {o.name!r} debe tener una IP (no un nombre) para enrutarla por la VPN")
        allowed.append(f"{o.host}/32")
    return (
        f"# OLT Management -> gateway {gw.name}. Guarda como /etc/wireguard/onugw{gw.id}.conf con permisos 600.\n"
        "[Interface]\n"
        f"PrivateKey = {decrypt(gw.server_private_enc)}\n"
        f"Address = {gw.server_ip}/{prefix}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {gw.router_public_key}\n"
        f"Endpoint = {gw.endpoint}:{gw.listen_port}\n"
        f"AllowedIPs = {', '.join(allowed)}\n"
        "PersistentKeepalive = 25\n"
    )
