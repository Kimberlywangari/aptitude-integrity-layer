from alembic import command
from sqlalchemy import create_engine, inspect

from tests.conftest import alembic_config

CORE_TABLES = {
    "candidates",
    "sittings",
    "sessions",
    "questions",
    "options",
    "question_stats",
    "session_questions",
}


def test_downgrade_to_base_then_upgrade_to_head(test_engine, test_database_url):
    test_engine.dispose()  # no pooled connection may hold a lock while the schema changes
    cfg = alembic_config(test_database_url)

    command.downgrade(cfg, "base")
    engine = create_engine(test_database_url)
    try:
        assert CORE_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(test_database_url)
    try:
        assert CORE_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
