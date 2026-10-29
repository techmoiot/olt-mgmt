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

## Autorizar una ONU

Al autorizar se elige:

- **VLAN**: `GET /olts/{id}/vlans` devuelve las que existen en la OLT; el sistema rechaza (400) cualquiera que no esté.
- **Plan de velocidad**: se crean en `POST /speed-plans` (subida/bajada en kbps) y el límite se aplica en la OLT.
- El **ONU ID** lo asigna el adaptador: primer hueco libre del puerto PON.

```
POST /onus/{id}/authorize
{"vlan": 254, "speed_plan_id": 1, "customer_name": "...", "customer_ref": "..."}
```

Lo que sabemos de la TP-Link DS-P7001-08 (por su backup): la VLAN vive en el `ont-lineprofile`
(`gem mapping ... vlan N`) y el límite de subida en el `dba-profile` (`type4 max <kbps>`).
Falta confirmar cómo limitar la bajada.

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
