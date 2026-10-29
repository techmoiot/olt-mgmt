# OLT Management

Sistema de autorización y gestión de ONUs para OLTs de varias marcas (TP-Link, ZTE, VSOL, BTPON).

## Estado

| Componente | Estado |
|---|---|
| API (FastAPI), base de datos, auditoría | Listo (esqueleto) |
| Adaptador simulado (`mock`) | Listo, sirve para probar el flujo |
| Adaptador TP-Link DS-P7001-08 | Conexión SSH lista; comandos pendientes de salidas reales de la CLI |
| Adaptadores ZTE, VSOL, BTPON | Pendientes |
| Panel web | Pendiente |

## Arquitectura

```
API (FastAPI) -> services (locks por OLT, auditoría) -> adaptador por marca -> OLT
                                  |
                              PostgreSQL / SQLite
```

Cada marca implementa la interfaz de `app/adapters/base.py`
(`list_unauthorized`, `authorize`, `suspend`, `resume`, `delete`).

## Ejecutar en desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# Documentación interactiva: http://localhost:8000/docs
pytest
```

Configuración por variables de entorno (prefijo `ONU_`), por ejemplo en `.env`:

```
ONU_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/onu_auth
```

## Completar el adaptador TP-Link

1. Captura la salida de comandos de lectura de tu OLT:
   `python tools/capture_cli.py --host IP --user admin "show version" ...`
2. Con esas salidas se implementan los métodos marcados `TODO` en `app/adapters/tplink.py`.

## Pendiente antes de producción

- Autenticación en la API (hoy está abierta).
- Cifrar las contraseñas de las OLTs (hoy se guardan en texto plano).
- Migraciones con Alembic.
- Escaneo periódico automático y panel web.
