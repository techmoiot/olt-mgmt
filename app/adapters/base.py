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


class InvalidRequest(Exception):
    """La petición no es válida (VLAN inexistente, estado incorrecto, etc.)."""


@dataclass
class AuthorizeRequest:
    serial: str
    pon_port: str
    vlan: int
    up_kbps: int    # límite de subida (en la OLT: DBA profile)
    down_kbps: int  # límite de bajada
    description: str = ""  # nombre del cliente, se guarda en la OLT si el equipo lo permite
    # Opcionales: si vienen, el adaptador usa estos perfiles que ya existen en la OLT en lugar de
    # derivarlos de up_kbps/down_kbps (0 = sin límite).
    line_profile: str = ""
    up_profile: str = ""
    down_profile: str = ""
    svlan: int | None = None
    config_type: str = "routing"  # routing | bridge
    onu_model: str = ""
    # El adaptador resuelve (o crea) el line/service profile que corresponda a vlan + velocidad,
    # y elige el primer ONU ID libre del puerto.


@dataclass
class AuthorizeResult:
    onu_id: int  # ID que la OLT asignó a la ONU en ese puerto PON


@dataclass
class OltCredentials:
    host: str
    port: int        # puerto del protocolo CLI elegido (SSH o Telnet)
    protocol: str    # "ssh" | "telnet"
    username: str
    password: str
    snmp_port: int = 161
    snmp_read: str = ""   # comunidad de lectura
    snmp_write: str = ""  # comunidad de escritura (solo si hace falta cambiar algo por SNMP)


class OltAdapter(ABC):
    vendor: str = "base"

    def __init__(self, creds: OltCredentials):
        self.creds = creds

    @abstractmethod
    def list_unauthorized(self) -> list[DiscoveredOnu]:
        """ONUs detectadas en los puertos PON que aún no están autorizadas."""

    @abstractmethod
    def list_vlans(self) -> list[int]:
        """VLANs que existen en la OLT, para ofrecerlas al autorizar."""

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

    def list_line_profiles(self) -> list[str]:
        """Line profiles existentes en la OLT (para el selector). Opcional."""
        raise NotImplementedError

    def list_speed_profiles(self) -> tuple[list[str], list[str]]:
        """(perfiles de subida, perfiles de bajada) existentes en la OLT. Opcional."""
        raise NotImplementedError

    def get_rx_power(self, pon_port: str, onu_id: int) -> str:
        """Potencia óptica recibida (dBm). Opcional."""
        raise NotImplementedError
