import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "install.sh"


def test_install_script_has_valid_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_install_script_runs_only_when_fully_downloaded():
    # Todo va dentro de main() y se llama al final: una descarga cortada no ejecuta nada a medias,
    # y ningún comando puede consumir el script desde la entrada estándar con "curl | bash".
    text = SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    # "exit $?" tras main: bash no sigue leyendo el archivo si se reemplaza durante una actualización.
    assert text.rstrip().endswith('main "$@"\nexit $?')


def test_install_script_creates_the_update_command():
    text = SCRIPT.read_text()
    assert "/usr/local/bin/ritsuko-update" in text
    assert "exec bash \"$OLT_DIR/install.sh\"" in text      # el comando re-ejecuta el instalador ya actualizado


def test_install_script_listens_locally_by_default():
    # La API aún no tiene login: por defecto solo debe escuchar en 127.0.0.1.
    assert 'ensure_setting OLT_BIND "${OLT_BIND-}" 127.0.0.1' in SCRIPT.read_text()


def test_install_script_validates_bind_and_port_before_saving_them():
    # Un valor inválido no debe llegar a guardarse en el archivo de configuración (rompería las
    # ejecuciones siguientes), así que la validación tiene que ir antes de escribirlo.
    text = SCRIPT.read_text()
    validated = text.index('valid_ipv4 "$OLT_BIND"')
    saved = text.index('ensure_setting OLT_BIND "${OLT_BIND-}"')
    assert validated < saved
    assert text.index('valid_port "$OLT_PORT"') < text.index('ensure_setting OLT_PORT "${OLT_PORT-}"')


def test_install_script_never_overwrites_existing_config():
    text = SCRIPT.read_text()
    assert 'if [ ! -f "$ENV_FILE" ]' in text


def test_install_script_creates_first_admin_and_user_command():
    text = SCRIPT.read_text()
    assert "manage_users.py\" bootstrap" in text and "ritsuko-user" in text
    assert "no se vuelve a mostrar" in text
