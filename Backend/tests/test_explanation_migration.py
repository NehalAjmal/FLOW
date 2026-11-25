from sqlalchemy import create_engine, inspect, text

from migrations.add_intervention_explanation import run


def test_migration_preserves_existing_records():
    engine = create_engine("sqlite:///:memory:")

    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE interventions ("
                "id VARCHAR(36) PRIMARY KEY, "
                "kind VARCHAR(30)"
                ")"
            ))

            conn.execute(text(
                "INSERT INTO interventions (id, kind) "
                "VALUES ('old-prompt', 'fatigue')"
            ))

        added = run(engine)

        assert added == ["explanation"]

        columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "interventions"
            )
        }

        assert "explanation" in columns

        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id, kind, explanation "
                "FROM interventions "
                "WHERE id = 'old-prompt'"
            )).one()

            assert row.id == "old-prompt"
            assert row.kind == "fatigue"
            assert row.explanation is None

    finally:
        engine.dispose()


def test_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:")

    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE interventions ("
                "id VARCHAR(36) PRIMARY KEY"
                ")"
            ))

        assert run(engine) == ["explanation"]
        assert run(engine) == []

    finally:
        engine.dispose()
