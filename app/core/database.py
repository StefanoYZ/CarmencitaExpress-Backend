from collections.abc import Generator
import logging
import time

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.business_time import BUSINESS_TIMEZONE_NAME
from app.core.config import settings


logger = logging.getLogger(__name__)

engine = create_engine(
    settings.sqlalchemy_database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "connect_timeout": 10,
        "options": f"-c timezone={BUSINESS_TIMEZONE_NAME}",
    },
)

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
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_db_tables(max_attempts: int = 5, retry_delay_seconds: int = 3) -> None:
    # Crea tablas nuevas y sincroniza columnas faltantes en desarrollo.
    from app.modules.clients import model as clients_model  # noqa: F401
    from app.modules.charge_logs import model as charge_logs_model  # noqa: F401
    from app.modules.destinations import model as destinations_model  # noqa: F401
    from app.modules.shipments import model as shipments_model  # noqa: F401
    from app.modules.sunat import model as sunat_model  # noqa: F401
    from app.modules.users import model as users_model  # noqa: F401

    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            sync_development_schema()
            return
        except OperationalError:
            if attempt == max_attempts:
                logger.exception(
                    "No se pudo conectar a PostgreSQL. Verifica DATABASE_URL y que "
                    "la base Render este en la misma region si usas la URL interna."
                )
                raise
            logger.warning(
                "PostgreSQL no disponible (intento %s/%s). Reintentando en %s segundos.",
                attempt,
                max_attempts,
                retry_delay_seconds,
            )
            time.sleep(retry_delay_seconds)


def sync_development_schema() -> None:
    """Add missing model columns in local development databases.

    create_all() creates new tables but does not alter existing ones, so this
    keeps local PostgreSQL schemas compatible with the SQLAlchemy models.
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
