from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.modules.sunat.model import ElectronicReceipt


def get_receipt_by_shipment(db: Session, shipment_id: int) -> ElectronicReceipt | None:
    return (
        db.query(ElectronicReceipt)
        .filter(ElectronicReceipt.shipment_id == shipment_id)
        .first()
    )


def get_next_receipt_number(db: Session, series: str) -> str:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("LOCK TABLE boletas_electronicas IN EXCLUSIVE MODE"))

    current_max = (
        db.query(func.max(ElectronicReceipt.number))
        .filter(ElectronicReceipt.series == series)
        .scalar()
    )
    return str((int(current_max or 0)) + 1).zfill(8)


def create_receipt(db: Session, **data) -> ElectronicReceipt:
    receipt = ElectronicReceipt(**data)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt
