"""Catálogo de marcas y modelos de OLT para el formulario de alta.

Es solo ayuda para elegir: el modelo se guarda como texto libre, así que un equipo que no esté en la
lista se registra igual con «Otro». Agregar modelos aquí no cambia el comportamiento del sistema.
"""

CATALOG: dict[str, dict] = {
    "tplink": {"label": "TP-Link", "models": ["DS-P7001-08", "DS-P7001-04"]},
    "zte": {"label": "ZTE", "models": ["ZXA10 C300", "ZXA10 C300M", "ZXA10 C320", "ZXA10 C600", "ZXA10 C610", "ZXA10 C620", "ZXA10 C650"]},
    "vsol": {"label": "VSOL", "models": ["V1600D4", "V1600D8", "V1600D16", "V1600G0", "V1600G1", "V1600G2"]},
    "btpon": {"label": "BTPON", "models": []},
    "huawei": {"label": "Huawei", "models": ["MA5608T", "MA5603T", "MA5600T", "MA5683T", "MA5800-X2", "MA5800-X7", "MA5800-X15"]},
    "mock": {"label": "Simulada (pruebas)", "models": ["Simulada"]},
}
