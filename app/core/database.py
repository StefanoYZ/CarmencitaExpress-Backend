from collections.abc import Generator

from sqlalchemy import create_engine
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
    from app.modules.shipments import model  # noqa: F401

    Base.metadata.create_all(bind=engine)
