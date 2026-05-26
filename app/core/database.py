from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_tables() -> None:
    # Temporal en desarrollo: crea tablas automaticamente.
    # En una fase posterior se reemplazara por Alembic con una migracion inicial.
    from app.modules.clients import model as clients_model  # noqa: F401
    from app.modules.shipments import model as shipments_model  # noqa: F401
    from app.modules.users import model as users_model  # noqa: F401

    Base.metadata.create_all(bind=engine)
    sync_development_schema()


def sync_development_schema() -> None:
    """Add missing model columns in local development databases.

    create_all() creates new tables but does not alter existing ones. The project
    is still pre-Alembic, so this keeps local PostgreSQL schemas compatible with
    the SQLAlchemy models after sprint changes add columns.
    """
    inspector = inspect(engine)

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue

            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                column_type = column.type.compile(dialect=engine.dialect)
                default_sql = ""
                nullable_sql = ""

                if column.name in {"fecha_creacion", "fecha_actualizacion"}:
                    default_sql = " DEFAULT CURRENT_TIMESTAMP"
                    nullable_sql = " NOT NULL"

                connection.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        f'ADD COLUMN IF NOT EXISTS "{column.name}" {column_type}{default_sql}{nullable_sql}'
                    )
                )

            for timestamp_column in ("fecha_creacion", "fecha_actualizacion"):
                if timestamp_column in {column.name for column in table.columns}:
                    connection.execute(
                        text(
                            f'UPDATE "{table.name}" '
                            f'SET "{timestamp_column}" = CURRENT_TIMESTAMP '
                            f'WHERE "{timestamp_column}" IS NULL'
                        )
                    )
