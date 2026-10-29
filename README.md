# Ritsuko

Sistema de autorización y gestión de ONUs para OLTs de varias marcas (TP-Link, ZTE, VSOL, BTPON).

## Estado

| Componente | Estado |
|---|---|
| API (FastAPI), base de datos, auditoría | Listo (esqueleto) |
| Alta de OLTs completa (IP, puertos SSH/Telnet/SNMP, comunidades, usuario, contraseña) | Listo, secretos cifrados |
| VPN WireGuard servidor <-> MikroTik (script RouterOS + config del servidor) | Listo (sintaxis sin probar en un router real) |
| Script MikroTik de VLAN de gestión y firewall por OLT | Listo (sintaxis sin probar en un router real) |
| Adaptador simulado (`mock`) | Listo, sirve para probar el flujo |
| Adaptador TP-Link DS-P7001-08 | Conexión SSH lista; comandos pendientes de salidas reales de la CLI |
| Adaptadores ZTE, VSOL, BTPON | Pendientes |
| Login (usuarios, roles admin/operador, sesiones, CSRF) | Listo |
| Panel web con menú lateral (una pantalla por tarea) | Listo |
| Autorizar ONU: VLAN (CVLAN/SVLAN), plan o perfiles de la OLT, Routing/Bridge, cliente, zona y NAP | Listo en el sistema y con OLT simulada; falta el comando real de cada marca |

## Arquitectura

```
API (FastAPI) -> services (locks por OLT, auditoría) -> adaptador por marca -> OLT
                                  |
                      PostgreSQL / SQLite  (secretos cifrados con Fernet)

Servidor (LXC) ==WireGuard== MikroTik --VLAN de gestión--> OLT      (si no están conectados directo)
```

## Instalar en el LXC (Debian 12 / Ubuntu 22.04+)

Como root dentro del LXC, un solo comando para instalar:

```bash
curl -fsSL https://raw.githubusercontent.com/techmoiot/olt-mgmt/main/install.sh | bash
```

Eso deja además el comando **`ritsuko-update`** en el servidor. Desde ahí, para actualizar a la última versión basta:

```bash
ritsuko-update
```

(Trae el código nuevo y vuelve a correr el instalador ya actualizado; conserva tu configuración. También puedes volver a pegar el `curl`.)

Instala lo que falte (git, python3-venv), crea el usuario `oltmgmt`, el código en `/opt/olt-mgmt`, los datos en `/var/lib/olt-mgmt`, la configuración en `/etc/olt-mgmt.env` (nunca la sobrescribe) y el servicio `olt-mgmt`, y comprueba que responde. **Cómo abrir la pantalla web.** Por defecto escucha solo en `127.0.0.1:8000`. Hay login, pero va por HTTP sin cifrar (las contraseñas viajan en claro), así que úsalo en una red de confianza. Dos opciones:

- **Túnel SSH (recomendado):** `ssh -L 8000:127.0.0.1:8000 root@IP_DEL_LXC` y abre `http://localhost:8000`.
- **Directo por la IP del LXC** (`http://IP_DEL_LXC:8000`), solo en una red de gestión de confianza o con firewall:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/techmoiot/olt-mgmt/main/install.sh | OLT_BIND=0.0.0.0 bash
  ```
  Si ya está instalado: `OLT_BIND=0.0.0.0 ritsuko-update`. Basta indicarlo una vez: se guarda en `/etc/olt-mgmt.env` y las actualizaciones lo conservan. Para volver a modo local, `OLT_BIND=127.0.0.1`.

Otras variables opcionales: `OLT_REPO`, `OLT_BRANCH`, `OLT_DIR`, `OLT_DATA`, `OLT_ENV`, `OLT_PORT`, `OLT_CMD` (dónde se crea `ritsuko-update`). Si el repositorio es privado, `raw.githubusercontent.com` y `git clone` necesitan un token o una deploy key.

## Pantallas

Todas viven bajo `/static/*.html` (la raíz `/` es el login). Menú lateral:

| Menú | Qué hace | Quién |
|---|---|---|
| Dashboard | ONUs en el sistema, sin autorizar, activas, fuera de línea, baja señal (< -27 dBm), autorizadas hoy/este mes | todos |
| OLTs / Agregar OLT | lista, probar conexión, buscar ONUs; alta con marca, modelo, versión, tipo de PON, puertos, SNMP y VPN | todos / admin |
| Sin autorizar | ONUs detectadas; filtrar por OLT; botón *Autorizar* | todos |
| Autorizar ONU | pestañas *Datos de ONU* y *Datos de cliente* | todos |
| Autorizadas | suspender, reactivar (todos) y eliminar (admin) | todos |
| MikroTik y VPN | VPN WireGuard y scripts de RouterOS | admin |
| Planes de velocidad, Zonas y NAP | catálogos | admin |
| Usuarios, Auditoría | gestión de accesos y registro de acciones | admin |

Hasta que existan los adaptadores reales, las pantallas funcionan completas con una OLT de marca `mock` (simulada). Los campos *Line profile*, *perfil de subida* y *perfil de bajada* se leen de la OLT; si el adaptador de esa marca aún no sabe leerlos, la pantalla lo avisa y se usa un plan propio.

**Actualizar una instalación anterior:** `ritsuko-update` agrega solas las columnas nuevas a la base existente (solo agrega, nunca borra).

## Login y usuarios

Todo exige iniciar sesión salvo la página de ingreso y `/health` (si se agrega una ruta nueva queda cerrada por defecto).

- **Primer ingreso:** al terminar la instalación se imprime una vez el usuario `admin` y una contraseña aleatoria. Al entrar, el sistema te obliga a cambiarla. Si la pierdes: `ritsuko-user reset admin --generate`.
- **Roles:** *administrador* (todo, incluidos OLTs, MikroTik/VPN, planes, usuarios y auditoría) y *operador* (ver OLTs, escanear, autorizar/suspender/reactivar ONUs).
- **Usuarios:** desde la web (sección *Usuarios*, solo admin) o en el servidor: `ritsuko-user list | create NOMBRE --role admin|operator | reset NOMBRE | deactivate NOMBRE | activate NOMBRE`.
- **Seguridad:** contraseñas con scrypt (mín. 10 caracteres); cookie `HttpOnly` + `SameSite=Strict`, token CSRF en cada cambio, sesión de 12 h con cierre a las 2 h sin actividad, bloqueo de 5 min tras 5 intentos fallidos, y cada acción queda en la auditoría con el usuario real.
- **HTTPS:** el login solo protege el acceso; sin HTTPS las contraseñas viajan en claro. Si lo pones detrás de un proxy con HTTPS, agrega `ONU_COOKIE_SECURE=true` en `/etc/olt-mgmt.env`. Las sesiones y bloqueos se reinician si cambias a varios procesos (hoy corre uno).

## Ejecutar en desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# Pantalla web: http://localhost:8000/    Documentación de la API: http://localhost:8000/docs
pytest
# crear tu usuario local:  python tools/manage_users.py create admin --role admin
```

Configuración por variables de entorno (prefijo `ONU_`), por ejemplo en `.env`:

```
ONU_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/onu_auth
ONU_SECRET_KEY=...   # opcional; si falta se crea ./secret.key (permisos 600) la primera vez
```

**Respalda la clave de cifrado** (`secret.key` o `ONU_SECRET_KEY`) aparte de la base de datos: sin ella no se pueden descifrar las contraseñas, comunidades SNMP ni las claves de VPN guardadas.

## Agregar una OLT

Desde la web o `POST /olts`. Datos: nombre, marca, modelo, **IP de la OLT**, **puertos SSH, Telnet y SNMP**, protocolo principal de consola, usuario, contraseña, **comunidad SNMP de lectura y de escritura**, y cómo llega el servidor a ella (directo o por la VPN de un MikroTik).

- Contraseña y comunidades se guardan **cifradas** y la API nunca las devuelve (solo indica si están configuradas).
- `POST /olts/{id}/test`: prueba TCP a cada puerto de consola. No envía credenciales. SNMP (UDP) aún no se comprueba.
- `DELETE /olts/{id}`: la quita del sistema (no toca la OLT física); se bloquea si tiene ONUs autorizadas.

## Conectar el servidor con las OLTs

### Si el servidor está conectado directo al MikroTik
En la OLT, botón **Script MikroTik**: indicas la IP del servidor, el puerto del MikroTik hacia la OLT, la VLAN de gestión y la IP del MikroTik en esa VLAN.

### Si el servidor está lejos: VPN WireGuard
Requiere **RouterOS 7.x** en el MikroTik y que sea alcanzable por UDP (IP pública, DDNS o puerto redirigido).

1. **Agregar el MikroTik** (`POST /gateways`): el sistema genera el par de claves del servidor (la privada queda cifrada y nunca sale por la API) y asigna una red de túnel `/30` (`10.99.x.x`).
2. **Script VPN** (`POST /gateways/{id}/vpn-script`): pégalo en el MikroTik. Crea su interfaz WireGuard, su IP en el túnel, el servidor como único par permitido y la regla de firewall del puerto UDP. **Imprime la clave pública del MikroTik.**
3. **Guardar esa clave** (`PUT /gateways/{id}/router-key`, o el campo en la tabla de la web).
4. **En el servidor**, genera su configuración y levanta el túnel:
   ```bash
   umask 077
   python tools/wg_server_config.py 1 > /etc/wireguard/onugw1.conf
   systemctl enable --now wg-quick@onugw1
   ```
   Esa configuración contiene la clave privada, por eso se lee directo de la base de datos y no pasa por la API. Incluye una ruta por cada OLT asociada al MikroTik: cuando agregues una OLT nueva, vuelve a generarla.
5. Con la OLT asociada a ese MikroTik, el botón **Script MikroTik** de la OLT ya no pide la IP del servidor: usa la del túnel.

> **LXC en Proxmox:** WireGuard dentro de un contenedor necesita el módulo `wireguard` cargado en el host y el dispositivo `/dev/net/tun` habilitado para el contenedor.

### Qué hacen los scripts
Solo **agregan** configuración (nunca borran ni modifican lo existente) y se pueden volver a correr sin duplicar. Todo dato que entra al script pasa por validación estricta (IPs reales, nombres sin comillas ni saltos de línea) para que un valor mal escrito no pueda inyectar comandos en el router. **Haz un respaldo (`/system backup save`) antes de aplicarlos y revísalos**: la sintaxis de RouterOS no se ha probado contra un router real.

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

## Completar el adaptador TP-Link

1. Captura la salida de comandos de lectura de tu OLT:
   `python tools/capture_cli.py --host IP --user admin "show version" ...`
2. Con esas salidas se implementan los métodos marcados `TODO` en `app/adapters/tplink.py`.

Los backups de OLT (`*.cfg`) traen hashes de contraseñas y datos de clientes: están en `.gitignore`, no los subas al repositorio.

## Pendiente antes de producción

- HTTPS delante de la pantalla web (proxy inverso) y, opcionalmente, 2FA.
- Migraciones con Alembic (hoy las tablas se crean al arrancar).
- Adaptadores reales (comandos por marca), lectura de estado/señal de las ONUs y escaneo periódico automático.
- PostgreSQL para producción (hoy se usa SQLite en `/var/lib/olt-mgmt`).
