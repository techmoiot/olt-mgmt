#!/usr/bin/env python3
"""Administra usuarios de Ritsuko desde el servidor (sirve para crear el primer admin o recuperar acceso).

  python tools/manage_users.py create admin --role admin      # pide la contraseña (o la genera con --generate)
  python tools/manage_users.py reset  admin                   # nueva contraseña temporal; cierra sus sesiones
  python tools/manage_users.py list
  python tools/manage_users.py deactivate juan | activate juan

La contraseña nunca se pasa como argumento (quedaría en el historial del shell).
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app import auth  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import AuditLog, User  # noqa: E402

import re  # noqa: E402

USERNAME = re.compile(r"^[a-z0-9._-]{3,32}$")


def ask_password(username: str, generate: bool) -> tuple[str, bool]:
    if generate:
        return auth.generate_password(), True
    while True:
        p1 = getpass.getpass("Contraseña: ")
        if getpass.getpass("Repítela: ") != p1:
            print("No coinciden."); continue
        try:
            auth.validate_password(p1, username)
        except auth.WeakPassword as exc:
            print(exc); continue
        return p1, False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("username"); c.add_argument("--role", choices=["admin", "operator"], default="operator")
    c.add_argument("--generate", action="store_true", help="genera una contraseña aleatoria y la muestra una vez")
    r = sub.add_parser("reset"); r.add_argument("username"); r.add_argument("--generate", action="store_true")
    sub.add_parser("list")
    sub.add_parser("bootstrap", help="si no hay ningún usuario, crea 'admin' con contraseña aleatoria (lo usa el instalador)")
    for name in ("activate", "deactivate"):
        sub.add_parser(name).add_argument("username")
    args = ap.parse_args()

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if args.cmd == "bootstrap":
            if db.scalar(select(User.id).limit(1)) is not None:
                return 0
            pw = auth.generate_password()
            db.add(User(username="admin", password_hash=auth.hash_password(pw), role="admin", must_change_password=True))
            db.add(AuditLog(action="user_created", actor="cli", detail="admin (admin) [inicial]"))
            db.commit()
            print(f"Usuario: admin\nContraseña temporal: {pw}\n(Se muestra una sola vez; deberá cambiarla al entrar.)")
            return 0
        if args.cmd == "list":
            for u in db.scalars(select(User).order_by(User.username)):
                print(f"{u.username:20} {u.role:9} {'activo' if u.active else 'DESACTIVADO'}"
                      f"{'  (contraseña temporal)' if u.must_change_password else ''}")
            return 0
        name = args.username.strip().lower()
        user = db.scalar(select(User).where(User.username == name))
        if args.cmd == "create":
            if not USERNAME.match(name):
                print("Usuario inválido: 3-32 caracteres a-z 0-9 . _ -"); return 1
            if user:
                print(f"Ya existe {name!r}. Usa 'reset' para cambiarle la contraseña."); return 1
            pw, shown = ask_password(name, args.generate)
            db.add(User(username=name, password_hash=auth.hash_password(pw), role=args.role, must_change_password=True))
            db.add(AuditLog(action="user_created", actor="cli", detail=f"{name} ({args.role})"))
        else:
            if not user:
                print(f"No existe el usuario {name!r}"); return 1
            if args.cmd == "reset":
                pw, shown = ask_password(name, args.generate)
                user.password_hash = auth.hash_password(pw); user.must_change_password = True
                auth.revoke_user_sessions(db, user.id)
                db.add(AuditLog(action="password_reset", actor="cli", detail=name))
            else:
                user.active = args.cmd == "activate"
                if not user.active:
                    auth.revoke_user_sessions(db, user.id)
                db.add(AuditLog(action="user_updated", actor="cli", detail=f"{name}: {args.cmd}"))
                db.commit(); print(f"{name}: {args.cmd} ok"); return 0
        db.commit()
    if shown:
        print(f"Usuario: {name}\nContraseña temporal: {pw}\n(Se muestra una sola vez; deberá cambiarla al entrar.)")
    else:
        print(f"{name}: listo. Deberá cambiar la contraseña al entrar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
