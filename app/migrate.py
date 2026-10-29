"""Migración mínima: agrega a las tablas existentes las columnas nuevas del modelo.

`create_all` crea tablas que faltan pero no toca las que ya existen, y una instalación vieja se
rompería al actualizar. Solo AGREGA columnas (nunca borra ni modifica), con el valor por defecto del
modelo para que las filas viejas queden completas. Cuando el esquema se complique, pasar a Alembic.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Boolean


def _literal(col) -> str | None:
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return None
    v = d.arg
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return None


def add_missing_columns(engine: Engine, metadata) -> list[str]:
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                lit = _literal(col)
                if lit is not None:
                    ddl += f" DEFAULT {lit}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added
