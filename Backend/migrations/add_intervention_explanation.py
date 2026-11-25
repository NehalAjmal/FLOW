from db_models.base import engine
from migrations.helpers import add_missing_columns


NEW_COLUMNS = {
    "explanation": "JSON NULL",
}


def run(bind=engine):
    return add_missing_columns(
        bind,
        "interventions",
        NEW_COLUMNS,
    )


if __name__ == "__main__":
    added = run()

    print(
        "Added:",
        ", ".join(added)
        if added
        else "Nothing, all columns already exist"
    )
