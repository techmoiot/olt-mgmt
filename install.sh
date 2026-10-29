#!/usr/bin/env bash
# OLT Management: instala o actualiza el servicio en un LXC/servidor Debian 12 / Ubuntu 22.04+.
# Se puede volver a correr cuantas veces haga falta: la primera vez instala, las demás actualiza.
#
#   curl -fsSL https://raw.githubusercontent.com/techmoiot/olt-mgmt/main/install.sh | bash
#
# Variables opcionales (todas tienen valor por defecto):
#   OLT_REPO   repositorio a clonar        (https://github.com/techmoiot/olt-mgmt)
#   OLT_BRANCH rama                        (main)
#   OLT_DIR    dónde queda el código       (/opt/olt-mgmt)
#   OLT_DATA   base de datos y clave       (/var/lib/olt-mgmt)
#   OLT_ENV    archivo de configuración    (/etc/olt-mgmt.env)
#   OLT_BIND   IP donde escucha            (127.0.0.1: solo local; la API aún no tiene login)
#   OLT_PORT   puerto                      (8000)

# Todo vive dentro de main() y se llama al final: si la descarga llega cortada no se ejecuta nada,
# y ningún comando puede leer el script desde la entrada estándar cuando se usa "| bash".
main() {
  set -euo pipefail

  local REPO="${OLT_REPO:-https://github.com/techmoiot/olt-mgmt}"
  local BRANCH="${OLT_BRANCH:-main}"
  local APP_DIR="${OLT_DIR:-/opt/olt-mgmt}"
  local DATA_DIR="${OLT_DATA:-/var/lib/olt-mgmt}"
  local ENV_FILE="${OLT_ENV:-/etc/olt-mgmt.env}"
  local BIND="${OLT_BIND:-127.0.0.1}"
  local PORT="${OLT_PORT:-8000}"
  local SVC_USER="oltmgmt"
  local UNIT="/etc/systemd/system/olt-mgmt.service"

  say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
  die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

  [ "$(id -u)" -eq 0 ] || die "Ejecútalo como root (o con:  curl -fsSL URL | sudo bash)"

  # 1) Dependencias del sistema (solo instala lo que falta)
  venv_ok() {
    local d; d="$(mktemp -d)"
    if python3 -m venv "$d/v" >/dev/null 2>&1; then rm -rf "$d"; return 0; fi
    rm -rf "$d"; return 1
  }
  local need=()
  command -v git >/dev/null 2>&1 || need+=(git)
  if ! command -v python3 >/dev/null 2>&1; then need+=(python3 python3-venv python3-pip)
  elif ! venv_ok; then need+=(python3-venv python3-pip); fi
  if [ "${#need[@]}" -gt 0 ]; then
    command -v apt-get >/dev/null 2>&1 || die "Faltan paquetes (${need[*]}) y no hay apt-get: instálalos a mano"
    say "Instalando paquetes: ${need[*]}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq </dev/null
    apt-get install -y -qq "${need[@]}" </dev/null
  fi
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "Se necesita Python 3.10 o superior (usa Debian 12 / Ubuntu 22.04+). Tienes: $(python3 --version)"

  # 2) Usuario sin privilegios para el servicio
  if ! id "$SVC_USER" >/dev/null 2>&1; then
    say "Creando el usuario $SVC_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
  fi

  # 3) Código: clona la primera vez, actualiza las siguientes
  export GIT_TERMINAL_PROMPT=0
  if [ -d "$APP_DIR/.git" ]; then
    say "Actualizando el código en $APP_DIR"
    git -C "$APP_DIR" fetch -q origin "$BRANCH" </dev/null || die "No se pudo consultar $REPO"
    git -C "$APP_DIR" checkout -q "$BRANCH"
    git -C "$APP_DIR" merge -q --ff-only "origin/$BRANCH" \
      || die "No se pudo actualizar sin conflictos: hay cambios locales en $APP_DIR"
  elif [ -n "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]; then
    die "$APP_DIR existe, no está vacío y no es un repositorio git: muévelo o usa OLT_DIR"
  else
    say "Descargando $REPO"
    git clone -q --branch "$BRANCH" "$REPO" "$APP_DIR" </dev/null \
      || die "No se pudo clonar $REPO (si el repositorio es privado necesitas una deploy key o un token)"
  fi

  # 4) Entorno de Python y dependencias
  [ -x "$APP_DIR/.venv/bin/python" ] || { say "Creando el entorno virtual"; python3 -m venv "$APP_DIR/.venv"; }
  say "Instalando dependencias de Python"
  "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" </dev/null

  # 5) Datos y configuración (la configuración existente NUNCA se sobrescribe)
  install -d -o "$SVC_USER" -g "$SVC_USER" -m 700 "$DATA_DIR"
  # Repara dueños por si algo se corrió a mano como root (el servicio corre como $SVC_USER y debe poder escribir)
  chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"
  if [ ! -f "$ENV_FILE" ]; then
    say "Creando $ENV_FILE"
    umask 077
    cat > "$ENV_FILE" <<EOF
ONU_DATABASE_URL=sqlite:///$DATA_DIR/onu_auth.db
ONU_SECRET_KEY_FILE=$DATA_DIR/secret.key
EOF
    chmod 600 "$ENV_FILE"
  fi

  # 6) Servicio systemd
  local started=0
  if [ -d /run/systemd/system ]; then
    cat > "$UNIT" <<EOF
[Unit]
Description=OLT Management
After=network-online.target
Wants=network-online.target

[Service]
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host $BIND --port $PORT
Restart=on-failure
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable -q olt-mgmt
    systemctl restart olt-mgmt
    started=1
  else
    say "systemd no está activo en este sistema: no se instaló el servicio."
    say "Para probarlo a mano:  set -a; . $ENV_FILE; set +a; cd $APP_DIR && .venv/bin/uvicorn app.main:app --port $PORT"
  fi

  # 7) Comprobación
  local version; version="$(git -C "$APP_DIR" rev-parse --short HEAD)"
  if [ "$started" -eq 1 ]; then
    local ok=0 i
    for i in $(seq 1 20); do
      if "$APP_DIR/.venv/bin/python" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/health', timeout=2)" >/dev/null 2>&1; then
        ok=1; break
      fi
      sleep 1
    done
    if [ "$ok" -eq 1 ]; then
      say "Listo (versión $version): el servicio responde en http://127.0.0.1:$PORT"
    else
      die "El servicio no respondió en 20 s. Revisa:  journalctl -u olt-mgmt -n 50 --no-pager"
    fi
  else
    say "Listo (versión $version)."
  fi

  cat <<EOF

Siguientes pasos
  - Abrir la pantalla web desde tu PC (túnel SSH):  ssh -L $PORT:127.0.0.1:$PORT root@IP_DE_ESTE_SERVIDOR
    y luego http://localhost:$PORT
  - Respalda la clave de cifrado (se crea al guardar la primera contraseña): $DATA_DIR/secret.key
    Sin ella no se pueden recuperar las contraseñas ni claves guardadas.
  - La API aún no tiene login: por eso escucha solo en $BIND. No la abras a la red (OLT_BIND) hasta que lo tenga.
  - Para actualizar más adelante, vuelve a correr este mismo comando.
EOF
}

main "$@"
