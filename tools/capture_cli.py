"""Captura la salida de comandos de la CLI de una OLT para que yo pueda escribir el adaptador real.

Solo ejecuta los comandos que TÚ le pases (se recomienda solo comandos de lectura: show/display).
No guarda la contraseña. Ejemplo:

    python tools/capture_cli.py --host 192.168.1.10 --user admin \\
        "show version" "show gpon onu uncfg" "show running-config"

La salida se guarda en capturas/<host>.txt. Pásame ese archivo (revisa antes que no
contenga datos sensibles que no quieras compartir).
"""
import argparse
import getpass
from pathlib import Path

from app.adapters.base import OltCredentials
from app.adapters.tplink import TplinkAdapter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", required=True)
    ap.add_argument("commands", nargs="+")
    args = ap.parse_args()

    password = getpass.getpass("Contraseña: ")
    creds = OltCredentials(args.host, args.port, "ssh", args.user, password)
    output = TplinkAdapter(creds).run(args.commands)

    out_dir = Path("capturas")
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{args.host}.txt"
    path.write_text(output)
    print(f"Guardado en {path}")


if __name__ == "__main__":
    main()
