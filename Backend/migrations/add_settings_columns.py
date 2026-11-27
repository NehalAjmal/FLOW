# migrations/add_settings_columns.py
# Task 4's new columns on user_settings. Safe to run twice.
# Run from Backend:   python -m migrations.add_settings_columns

from migrations.helpers import add_missing_columns

NEW_COLUMNS = {
    "delivery_mode":    "VARCHAR(10) NOT NULL DEFAULT 'advisory'",
    "break_length_sec": "INTEGER NOT NULL DEFAULT 300",
    "camera_enabled":   "BOOLEAN NOT NULL DEFAULT 1",
    "calendar_enabled": "BOOLEAN NOT NULL DEFAULT 1",
    "llm_enabled":      "BOOLEAN NOT NULL DEFAULT 1",
    "snooze_options":   "JSON NULL",
}


def run(bind=None):
    if bind is None:
        from db_models.base import engine as bind
    return add_missing_columns(bind, "user_settings", NEW_COLUMNS)


if __name__ == "__main__":
    added = run()
    print("added:", ", ".join(added) if added else "nothing, all columns already exist")
