"""Marcas ya registrables en el sistema pero sin adaptador real todavía.

Permiten dar de alta la OLT (datos, acceso, VPN, scripts de MikroTik) y fallan con un mensaje claro
(501) al intentar operarla, en vez de impedir registrarla. Se reemplazan por el adaptador real cuando
se tengan las salidas de la CLI de esa marca.
"""
from .base import AuthorizeRequest, AuthorizeResult, DiscoveredOnu, OltAdapter


def pending_adapter(vendor: str, label: str) -> type[OltAdapter]:
    msg = f"{label}: el adaptador de esta marca aún no está implementado"

    class _Pending(OltAdapter):
        def list_unauthorized(self) -> list[DiscoveredOnu]:
            raise NotImplementedError(msg)

        def list_vlans(self) -> list[int]:
            raise NotImplementedError(msg)

        def authorize(self, req: AuthorizeRequest) -> AuthorizeResult:
            raise NotImplementedError(msg)

        def suspend(self, pon_port: str, onu_id: int) -> None:
            raise NotImplementedError(msg)

        def resume(self, pon_port: str, onu_id: int) -> None:
            raise NotImplementedError(msg)

        def delete(self, pon_port: str, onu_id: int) -> None:
            raise NotImplementedError(msg)

    _Pending.vendor = vendor
    _Pending.__name__ = f"{label}PendingAdapter"
    return _Pending
