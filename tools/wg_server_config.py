"""Imprime la configuración WireGuard del SERVIDOR para un gateway (MikroTik).

Contiene la clave privada del servidor, por eso NO se expone por la API: se lee directo de la base
de datos y se imprime por la salida estándar. Úsalo en el servidor (LXC), con permisos restrictivos:

    umask 077
    python tools/wg_server_config.py 1 > /etc/wireguard/onugw1.conf
    systemctl enable --now wg-quick@onugw1

Usa las mismas variables ONU_* que la aplicación (base de datos y clave de cifrado).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.base import InvalidRequest  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Gateway  # noqa: E402
from app.vpn import server_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gateway_id", type=int)
    args = ap.parse_args()

    with SessionLocal() as db:
        gw = db.get(Gateway, args.gateway_id)
        if gw is None:
            print(f"No existe el gateway {args.gateway_id}", file=sys.stderr)
            return 1
        try:
            print(server_config(gw, list(gw.olts)), end="")
        except InvalidRequest as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
