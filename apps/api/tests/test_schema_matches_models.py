"""The SQL migrations own the schema; the ORM models must describe exactly the same columns."""

from sqlalchemy import inspect

from app.core.database import get_engine
from app.models import Base


def test_every_table_has_the_same_columns_in_sql_and_in_the_models():
    inspector = inspect(get_engine())
    assert len(Base.metadata.sorted_tables) == 15
    for table in Base.metadata.sorted_tables:
        in_database = {column["name"] for column in inspector.get_columns(table.name)}
        in_models = {column.name for column in table.columns}
        assert in_database == in_models, f"{table.name} differs"


def test_row_level_security_is_enabled_on_every_table():
    with get_engine().connect() as connection:
        unprotected = (
            connection.exec_driver_sql(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity "
                "AND relname <> 'schema_migrations'"
            )
            .scalars()
            .all()
        )
    assert unprotected == []
