from datetime import date, datetime, timezone

from app.core.business_time import BUSINESS_TIMEZONE, business_day_utc_bounds
from app.modules.shipments import repository as shipments_repository


def test_business_day_bounds_follow_peru_midnight():
    start, end = business_day_utc_bounds(date(2026, 6, 22))

    assert start == datetime(2026, 6, 22, 5, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 23, 4, 59, 59, 999999, tzinfo=timezone.utc)
    assert start.astimezone(BUSINESS_TIMEZONE).date() == date(2026, 6, 22)
    assert end.astimezone(BUSINESS_TIMEZONE).date() == date(2026, 6, 22)


def test_shipment_prefix_uses_business_date(monkeypatch):
    monkeypatch.setattr(
        shipments_repository,
        "business_today",
        lambda: date(2026, 6, 22),
    )

    assert shipments_repository.expected_shipment_code_prefix() == "L"
