"""Interfaz común que toda OLT debe implementar.

El núcleo del sistema solo conoce estos métodos; cada marca (TP-Link, ZTE, VSOL,
BTPON) los traduce a sus propios comandos CLI/SNMP.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class AdapterError(Exception):
    """Error al hablar con la OLT (conexión, comando rechazado, salida inesperada)."""


@dataclass
class DiscoveredOnu:
    serial: str
    pon_port: str
    rx_power_dbm: str = ""


@dataclass
class AuthorizeRequest:
    serial: str
    pon_port: str
    line_profile: str
    service_profile: str
    vlan: int
    description: str = ""  # nombre del cliente, se guarda en la OLT si el equipo lo permite


@dataclass
class AuthorizeResult:
    onu_id: int  # ID que la OLT asignó a la ONU en ese puerto PON


@dataclass
class OltCredentials:
    host: str
    port: int
    protocol: str
    username: str
    password: str


class OltAdapter(ABC):
    vendor: str = "base"

    def __init__(self, creds: OltCredentials):
        self.creds = creds

    @abstractmethod
    def list_unauthorized(self) -> list[DiscoveredOnu]:
        """ONUs detectadas en los puertos PON que aún no están autorizadas."""

    @abstractmethod
    def authorize(self, req: AuthorizeRequest) -> AuthorizeResult:
        """Autoriza la ONU y le aplica el servicio."""

    @abstractmethod
    def suspend(self, pon_port: str, onu_id: int) -> None:
        """Suspende el servicio (por ejemplo, por falta de pago) sin eliminar la ONU."""

    @abstractmethod
    def resume(self, pon_port: str, onu_id: int) -> None:
        """Reactiva una ONU suspendida."""

    @abstractmethod
    def delete(self, pon_port: str, onu_id: int) -> None:
        """Elimina la ONU de la OLT."""

    def get_rx_power(self, pon_port: str, onu_id: int) -> str:
        """Potencia óptica recibida (dBm). Opcional."""
        raise NotImplementedError
