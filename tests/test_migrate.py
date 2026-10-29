import sqlite3
import tempfile

from sqlalchemy import create_engine, text

from app.db import Base
from app.migrate import add_missing_columns


def test_old_database_gets_new_columns_and_keeps_rows():
    path = tempfile.mkdtemp() + "/old.db"
    con = sqlite3.connect(path)
    # esquema anterior: olts sin software_version/pon_type
    con.execute("CREATE TABLE olts (id INTEGER PRIMARY KEY, name VARCHAR(80), vendor VARCHAR(30), model VARCHAR(60), "
                "host VARCHAR(253), cli_protocol VARCHAR(10), ssh_port INT, telnet_port INT, snmp_port INT, "
                "username VARCHAR(80), password_enc TEXT, snmp_read_enc TEXT, snmp_write_enc TEXT, gateway_id INT, created_at DATETIME)")
    con.execute("INSERT INTO olts (id, name, vendor, host) VALUES (1, 'vieja', 'tplink', '10.0.0.1')")
    con.commit(); con.close()

    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)  # crea las tablas nuevas, no toca olts
    added = add_missing_columns(eng, Base.metadata)
    assert "olts.software_version" in added and "olts.pon_type" in added
    with eng.connect() as c:
        row = c.execute(text("SELECT name, pon_type, software_version FROM olts")).one()
    assert tuple(row) == ("vieja", "gpon", "")  # la fila vieja queda con los valores por defecto
    assert add_missing_columns(eng, Base.metadata) == []  # idempotente
