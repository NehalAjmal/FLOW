# migrations/add_user_mfa_columns.py
# Nehal's Task 5 added mfa_secret and mfa_enabled to the users model.
# create_all() won't add them to an existing users table, so do it here.
# Safe to run twice. Run from Backend:   python -m migrations.add_user_mfa_columns

from sqlalchemy import inspect, text

from db_models.base import engine

NEW_COLUMNS = {
    "mfa_secret":  "VARCHAR(64) NULL",
    "mfa_enabled": "BOOLEAN NOT NULL DEFAULT 0",
}


def run(bind=engine):
    existing = {col["name"] for col in inspect(bind).get_columns("users")}
    added = []
    with bind.begin() as conn:
        for name, ddl in NEW_COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
                added.append(name)
    return added


if __name__ == "__main__":
    added = run()
    print("added:", ", ".join(added) if added else "nothing, all columns already exist")
