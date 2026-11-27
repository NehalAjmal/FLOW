# migrations/add_break_columns.py
# create_all() never adds columns to a table that already exists,
# so this adds Task 3's new break columns by hand. Safe to run twice:
# it skips any column that is already there.
#
# Run from Backend:   python -m migrations.add_break_columns

from sqlalchemy import inspect, text

from db_models.base import engine

NEW_COLUMNS = {
    "ended_at":           "DATETIME NULL",
    "intervention_id":    "VARCHAR(36) NULL",
    "resumption_lag_sec": "FLOAT NULL",
    "resumption_source":  "VARCHAR(10) NULL",
}


def run(bind=engine):
    existing = {col["name"] for col in inspect(bind).get_columns("breaks")}
    added = []
    with bind.begin() as conn:          # begin() = one transaction, committed at the end
        for name, ddl in NEW_COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE breaks ADD COLUMN {name} {ddl}"))
                added.append(name)
    return added


if __name__ == "__main__":
    added = run()
    print("added:", ", ".join(added) if added else "nothing, all columns already exist")
