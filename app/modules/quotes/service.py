import unicodedata

from sqlalchemy.orm import Session

from app.modules.quotes.schema import QuoteResponse
from app.modules.measurement_logs.service import start_service_phase
from app.modules.shipments.constants import CANCELED_STATUS
from app.modules.shipments.model import Shipment
from app.modules.shipments.service import get_shipment, mark_shipment_as_quoted


FRAGILITY_SURCHARGES = {
    "BAJA": 0.00,
    "MEDIA": 5.00,
    "ALTA": 10.00,
}
ROUTE_BASE_RATES = {
    ("trujillo", "angasmarca"): 10.00,
    ("angasmarca", "trujillo"): 10.00,
    ("trujillo", "huamachuco"): 8.00,
    ("huamachuco", "trujillo"): 8.00,
}
DEFAULT_BASE_RATE = 12.00


def calculate_quote_for_shipment(shipment: Shipment) -> QuoteResponse:
    base_rate = _base_rate_for_route(shipment.origin, shipment.destination)
    weight_cost = shipment.weight_kg * 2.00
    volume_m3 = shipment.length_cm * shipment.width_cm * shipment.height_cm / 1_000_000
    volume_cost = volume_m3 * 20.00
    fragility_surcharge = _fragility_surcharge(shipment)

    subtotal = base_rate + weight_cost + volume_cost + fragility_surcharge
    igv = subtotal * 0.18
    total = subtotal + igv

    return QuoteResponse(
        encomienda_id=shipment.id,
        codigo_encomienda=shipment.shipment_code,
        origen=shipment.origin,
        destino=shipment.destination,
        subtotal=round(subtotal, 2),
        igv=round(igv, 2),
        total=round(total, 2),
        moneda="PEN",
        detalle={
            "base_rate": round(base_rate, 2),
            "route": f"{shipment.origin} - {shipment.destination}",
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
    start_service_phase(db, "registro", encomienda_id=shipment.id, timestamp_inicio=shipment.created_at)
    mark_shipment_as_quoted(db, shipment)
    return quote


def _base_rate_for_route(origin: str, destination: str) -> float:
    route_key = (_normalize_location(origin), _normalize_location(destination))
    return ROUTE_BASE_RATES.get(route_key, DEFAULT_BASE_RATE)


def _normalize_location(value: str) -> str:
    text = " ".join(value.strip().split()).lower()
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _fragility_surcharge(shipment: Shipment) -> float:
    surcharge = FRAGILITY_SURCHARGES.get(shipment.fragility, 0.00)
    content_type = _normalize_location(shipment.content_type or "")
    if "fragil" in content_type:
        return max(surcharge, FRAGILITY_SURCHARGES["MEDIA"])
    return surcharge
