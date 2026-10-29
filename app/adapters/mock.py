"""Adaptador simulado en memoria. Sirve para probar el flujo completo sin tocar una OLT real."""
from .base import (
    AdapterError,
    AuthorizeRequest,
    AuthorizeResult,
    DiscoveredOnu,
    OltAdapter,
)

# Estado compartido por host para que varias llamadas vean lo mismo.
_STATE: dict[str, dict] = {}


def _state(host: str) -> dict:
    return _STATE.setdefault(
        host, {"unauthorized": [], "authorized": {}, "vlans": list(range(249, 259))}
    )


def mock_add_unauthorized(host: str, serial: str, pon_port: str, rx: str = "-20.5") -> None:
    """Helper de pruebas: simula que aparece una ONU nueva en la OLT."""
    _state(host)["unauthorized"].append(DiscoveredOnu(serial, pon_port, rx))


def mock_reset() -> None:
    _STATE.clear()


class MockAdapter(OltAdapter):
    vendor = "mock"

    def list_unauthorized(self) -> list[DiscoveredOnu]:
        return list(_state(self.creds.host)["unauthorized"])

    def list_vlans(self) -> list[int]:
        return list(_state(self.creds.host)["vlans"])

    def authorize(self, req: AuthorizeRequest) -> AuthorizeResult:
        st = _state(self.creds.host)
        found = [o for o in st["unauthorized"] if o.serial == req.serial]
        if not found:
            raise AdapterError(f"ONU {req.serial} no está en la lista de no autorizadas")
        st["unauthorized"] = [o for o in st["unauthorized"] if o.serial != req.serial]
        # Primer ID libre del puerto (igual que hará el adaptador real)
        used = {oid for (port, oid) in st["authorized"] if port == req.pon_port}
        onu_id = next(i for i in range(len(used) + 1) if i not in used)
        st["authorized"][(req.pon_port, onu_id)] = {
            "serial": req.serial,
            "suspended": False,
            "vlan": req.vlan,
            "up_kbps": req.up_kbps,
            "down_kbps": req.down_kbps,
        }
        return AuthorizeResult(onu_id=onu_id)

    def _get(self, pon_port: str, onu_id: int) -> dict:
        try:
            return _state(self.creds.host)["authorized"][(pon_port, onu_id)]
        except KeyError:
            raise AdapterError(f"ONU {onu_id} no existe en el puerto {pon_port}")

    def suspend(self, pon_port: str, onu_id: int) -> None:
        self._get(pon_port, onu_id)["suspended"] = True

    def resume(self, pon_port: str, onu_id: int) -> None:
        self._get(pon_port, onu_id)["suspended"] = False

    def delete(self, pon_port: str, onu_id: int) -> None:
        self._get(pon_port, onu_id)
        del _state(self.creds.host)["authorized"][(pon_port, onu_id)]

    def get_rx_power(self, pon_port: str, onu_id: int) -> str:
        self._get(pon_port, onu_id)
        return "-19.8"
