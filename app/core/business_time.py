from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE_NAME = "America/Lima"
BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)


def business_now() -> datetime:
    return datetime.now(BUSINESS_TIMEZONE)


def business_today() -> date:
    return business_now().date()


def business_day_utc_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    selected_day = day or business_today()
    start_local = datetime.combine(selected_day, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = datetime.combine(selected_day, time.max, tzinfo=BUSINESS_TIMEZONE)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
