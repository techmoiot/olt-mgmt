"""Registro de adaptadores por marca. Para agregar una marca: crear su módulo y registrarla aquí."""
from .base import AdapterError, OltAdapter, OltCredentials
from .mock import MockAdapter
from .tplink import TplinkAdapter

ADAPTERS: dict[str, type[OltAdapter]] = {
    "mock": MockAdapter,
    "tplink": TplinkAdapter,
    # "zte": ZteAdapter,      # pendiente
    # "vsol": VsolAdapter,    # pendiente
    # "btpon": BtponAdapter,  # pendiente
}


def get_adapter(vendor: str, creds: OltCredentials) -> OltAdapter:
    try:
        return ADAPTERS[vendor](creds)
    except KeyError:
        raise AdapterError(f"Marca {vendor!r} sin adaptador. Disponibles: {', '.join(ADAPTERS)}")
