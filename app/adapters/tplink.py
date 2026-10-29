"""Adaptador TP-Link (DS-P7001-08, firmware 1.0.9 Build 20240425).

ESTADO: esqueleto. La conexión CLI funciona, pero los comandos de cada operación
están sin implementar a propósito: no conozco la sintaxis exacta de este firmware
y un comando equivocado en una OLT en producción puede afectar a clientes.

Para completarlo necesito salidas reales de la CLI (ver tools/capture_cli.py).
Cada método marcado con TODO se rellena con esas salidas.
"""
import time

import paramiko

from .base import (
    AdapterError,
    AuthorizeRequest,
    AuthorizeResult,
    DiscoveredOnu,
    OltAdapter,
)


class TplinkAdapter(OltAdapter):
    vendor = "tplink"

    # ---- Sesión CLI --------------------------------------------------------
    def run(self, commands: list[str], timeout: float = 15.0) -> str:
        """Ejecuta comandos en una sesión interactiva y devuelve toda la salida.

        Solo SSH por ahora. Telnet se agrega cuando confirmemos cómo accedes.
        """
        if self.creds.protocol != "ssh":
            raise AdapterError(f"Protocolo {self.creds.protocol!r} aún no soportado en TP-Link")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.creds.host,
                port=self.creds.port,
                username=self.creds.username,
                password=self.creds.password,
                timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            shell = client.invoke_shell()
            out = ""
            for cmd in commands:
                shell.send(cmd + "\n")
                time.sleep(1.0)
                while shell.recv_ready():
                    out += shell.recv(65535).decode(errors="replace")
            return out
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"Error de conexión a {self.creds.host}: {exc}") from exc
        finally:
            client.close()

    # ---- Operaciones (pendientes de las salidas reales) -------------------
    def list_unauthorized(self) -> list[DiscoveredOnu]:
        # TODO: ejecutar el comando que lista ONUs sin autorizar y parsear la salida.
        raise NotImplementedError("TP-Link: falta el comando para listar ONUs sin autorizar")

    def authorize(self, req: AuthorizeRequest) -> AuthorizeResult:
        # TODO: secuencia de comandos para autorizar y aplicar perfil/VLAN.
        raise NotImplementedError("TP-Link: falta la secuencia de comandos para autorizar")

    def suspend(self, pon_port: str, onu_id: int) -> None:
        raise NotImplementedError("TP-Link: falta el comando para suspender")

    def resume(self, pon_port: str, onu_id: int) -> None:
        raise NotImplementedError("TP-Link: falta el comando para reactivar")

    def delete(self, pon_port: str, onu_id: int) -> None:
        raise NotImplementedError("TP-Link: falta el comando para eliminar")
