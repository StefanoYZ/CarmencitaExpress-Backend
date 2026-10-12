import logging

from app.core.database import SessionLocal, create_db_tables
from app.modules.agencies.service import backfill_shipment_agencies_by_origin
from app.modules.destinations.service import seed_default_destinations
from app.modules.users.service import seed_initial_access_control


logger = logging.getLogger(__name__)


def bootstrap_database() -> None:
    create_db_tables()
    db = SessionLocal()
    try:
        seed_initial_access_control(db)
        seed_default_destinations(db)
        reassigned = backfill_shipment_agencies_by_origin(db)
        if reassigned:
            logger.info("Assigned %s existing shipments to their origin agencies", reassigned)
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting database schema and seed bootstrap")
    bootstrap_database()
    logger.info("Database bootstrap completed")


if __name__ == "__main__":
    main()
