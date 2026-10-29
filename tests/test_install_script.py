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
    assert text.rstrip().endswith('main "$@"')


def test_install_script_listens_locally_by_default():
    # La API aún no tiene login: por defecto solo debe escuchar en 127.0.0.1.
    assert 'OLT_BIND:-127.0.0.1' in SCRIPT.read_text()


def test_install_script_never_overwrites_existing_config():
    text = SCRIPT.read_text()
    assert 'if [ ! -f "$ENV_FILE" ]' in text
