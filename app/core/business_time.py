from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE_NAME = "America/Lima"
BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)


def business_now() -> datetime:
    return datetime.now(BUSINESS_TIMEZONE)


def ensure_business_tz(value: datetime | None) -> datetime | None:
    """Normaliza un datetime a la zona de negocio (aware).

    Evita comparar datetimes naive (p. ej. los que devuelve SQLite) con aware
    (los de business_now). Si es naive se asume la zona de negocio.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BUSINESS_TIMEZONE)
    return value.astimezone(BUSINESS_TIMEZONE)


def business_today() -> date:
    return business_now().date()


def business_day_utc_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    selected_day = day or business_today()
    start_local = datetime.combine(selected_day, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = datetime.combine(selected_day, time.max, tzinfo=BUSINESS_TIMEZONE)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
