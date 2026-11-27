# migrations/helpers.py
# Shared by every migration: add each column that a table doesn't have yet.
from sqlalchemy import inspect, text


def add_missing_columns(bind, table: str, columns: dict) -> list:
    existing = {col["name"] for col in inspect(bind).get_columns(table)}
    added = []
    with bind.begin() as conn:
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                added.append(name)
    return added
