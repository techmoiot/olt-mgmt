# OLT Management

Sistema de autorización y gestión de ONUs para OLTs de varias marcas (TP-Link, ZTE, VSOL, BTPON).

## Estado

| Componente | Estado |
|---|---|
| API (FastAPI), base de datos, auditoría | Listo (esqueleto) |
| Adaptador simulado (`mock`) | Listo, sirve para probar el flujo |
| Adaptador TP-Link DS-P7001-08 | Conexión SSH lista; comandos pendientes de salidas reales de la CLI |
| Adaptadores ZTE, VSOL, BTPON | Pendientes |
| Alta de OLTs + prueba de conexión (API y pantalla web) | Listo |
| Generador de script MikroTik | Listo (sintaxis sin probar en un router real) |
| Panel web de autorización de ONUs | Pendiente |

## Arquitectura

```
API (FastAPI) -> services (locks por OLT, auditoría) -> adaptador por marca -> OLT
                                  |
                              PostgreSQL / SQLite
```

Cada marca implementa la interfaz de `app/adapters/base.py`
(`list_unauthorized`, `authorize`, `suspend`, `resume`, `delete`).

## Agregar una OLT

Desde la web (`http://servidor:8000/`) o la API:

- `POST /olts`: nombre, marca, IP de gestión, protocolo (ssh/telnet/snmp), puerto (si se omite, el estándar del protocolo) y credenciales. Valida marca, formato de campos y nombres duplicados; la contraseña nunca se devuelve.
- `POST /olts/{id}/test`: prueba TCP al puerto de gestión. No envía credenciales ni comandos.
- `DELETE /olts/{id}`: la quita del sistema (no toca la OLT física). Se bloquea si tiene ONUs autorizadas.

## Conectar el sistema con la OLT a través del MikroTik

`POST /olts/{id}/mikrotik-script` (o el botón "Script MikroTik" en la web) **genera** un script de RouterOS; el sistema nunca se conecta al MikroTik ni lo ejecuta. Datos que pide: IP del sistema, puerto del MikroTik hacia la OLT, VLAN de gestión, IP del MikroTik en esa VLAN y prefijo (y el bridge, si usa vlan-filtering).

El script solo **agrega** cosas (nunca borra ni modifica lo existente) y se puede volver a correr sin duplicar:

1. VLAN de gestión sobre el puerto indicado (reutiliza una existente con ese VLAN ID).
2. IP del MikroTik en esa red.
3. Reglas de firewall: solo el sistema puede llegar a la IP de la OLT, solo a ping y al puerto de gestión.
4. Masquerade opcional hacia la OLT, para que no necesite ruta de vuelta.
5. Ping de prueba.

Todo lo que se escribe en el script pasa por validación estricta (IPs reales, nombres sin comillas ni saltos de línea) para que un dato mal escrito no pueda inyectar comandos en el router.
Aviso: la sintaxis de RouterOS no se ha probado contra un router real; revisa el script y pruébalo primero con un respaldo hecho (`/system backup save`).

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
