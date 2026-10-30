"""Registro de adaptadores por marca. Para agregar una marca: crear su módulo y registrarla aquí."""
from .base import AdapterError, OltAdapter, OltCredentials
from .mock import MockAdapter
from .pending import pending_adapter
from .tplink import TplinkAdapter

ADAPTERS: dict[str, type[OltAdapter]] = {
    "mock": MockAdapter,
    "tplink": TplinkAdapter,
    # Registrables ya; operar la OLT responde 501 hasta que exista el adaptador real de la marca.
    "zte": pending_adapter("zte", "ZTE"),
    "vsol": pending_adapter("vsol", "VSOL"),
    "btpon": pending_adapter("btpon", "BTPON"),
    "huawei": pending_adapter("huawei", "Huawei"),
}

# Marcas con adaptador real (las demás solo se pueden registrar)
IMPLEMENTED = {"mock", "tplink"}


def get_adapter(vendor: str, creds: OltCredentials) -> OltAdapter:
    try:
        return ADAPTERS[vendor](creds)
    except KeyError:
        raise AdapterError(f"Marca {vendor!r} sin adaptador. Disponibles: {', '.join(ADAPTERS)}")
