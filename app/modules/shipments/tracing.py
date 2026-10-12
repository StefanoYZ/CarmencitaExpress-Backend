from app.modules.claims.model import ShipmentTraceEvent
from app.modules.shipments.model import Shipment
from app.modules.users.model import InternalUser


def append_shipment_trace_event(
    db,
    shipment: Shipment,
    *,
    event_type: str,
    description: str,
    location: str | None = None,
    actor: InternalUser | None = None,
    actor_user_id: int | None = None,
    source: str = "SISTEMA",
    visible_to_customer: bool = True,
) -> ShipmentTraceEvent:
    event = ShipmentTraceEvent(
        shipment_id=shipment.id,
        agency_id=shipment.agency_id,
        actor_user_id=actor.id if actor is not None else actor_user_id,
        event_type=event_type,
        status=shipment.status,
        location=location,
        description=description,
        source=source,
        visible_to_customer=visible_to_customer,
    )
    db.add(event)
    return event
