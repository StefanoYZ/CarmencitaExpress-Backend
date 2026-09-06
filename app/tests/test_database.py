from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

import app.core.database as database


def test_schema_sync_uses_a_single_connection(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)

    try:
        database.sync_development_schema()
    finally:
        engine.dispose()
