from sqlalchemy.orm import Session

from app.modules.quotes.schema import QuoteResponse
from app.modules.shipments.model import Shipment
from app.modules.shipments.service import get_shipment, mark_shipment_as_quoted


FRAGILITY_SURCHARGES = {
    "BAJA": 0.00,
    "MEDIA": 5.00,
    "ALTA": 10.00,
}
CANCELED_STATUS = "ANULADA"


def calculate_quote_for_shipment(shipment: Shipment) -> QuoteResponse:
    base_rate = 10.00
    weight_cost = shipment.weight_kg * 2.00
    volume_m3 = shipment.length_cm * shipment.width_cm * shipment.height_cm / 1_000_000
    volume_cost = volume_m3 * 20.00
    fragility_surcharge = FRAGILITY_SURCHARGES[shipment.fragility]

    subtotal = base_rate + weight_cost + volume_cost + fragility_surcharge
    igv = subtotal * 0.18
    total = subtotal + igv

    return QuoteResponse(
        encomienda_id=shipment.id,
        codigo_encomienda=shipment.shipment_code,
        subtotal=round(subtotal, 2),
        igv=round(igv, 2),
        total=round(total, 2),
        moneda="PEN",
        detalle={
            "base_rate": round(base_rate, 2),
            "weight_cost": round(weight_cost, 2),
            "volume_m3": round(volume_m3, 6),
            "volume_cost": round(volume_cost, 2),
            "fragility": shipment.fragility,
            "fragility_surcharge": round(fragility_surcharge, 2),
        },
    )


def calculate_quote(db: Session, shipment_id: int) -> QuoteResponse | None:
    shipment = get_shipment(db, shipment_id)
    if shipment is None:
        return None
    if shipment.status == CANCELED_STATUS:
        raise ValueError("No se puede cotizar una encomienda anulada")
    quote = calculate_quote_for_shipment(shipment)
    mark_shipment_as_quoted(db, shipment)
    return quote
