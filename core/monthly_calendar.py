"""Persistence helpers for the administrator-managed monthly calendar image."""

from datetime import datetime
from zoneinfo import ZoneInfo

from tools.local.data_manager import load_json, save_json
from core.community_timezone import DEFAULT_COMMUNITY_TIMEZONE, get_community_timezone

CALENDAR_TIMEZONE = ZoneInfo(DEFAULT_COMMUNITY_TIMEZONE)
SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def current_calendar_month(now=None):
    """Return the current Guadalajara calendar month as ``YYYY-MM``."""
    community_timezone = get_community_timezone()
    current_time = now or datetime.now(community_timezone)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=community_timezone)
    return current_time.astimezone(community_timezone).strftime("%Y-%m")


def parse_calendar_month(raw_month, now=None):
    """Validate a calendar month or return the current Guadalajara month."""
    if not raw_month:
        return current_calendar_month(now)
    try:
        parsed_month = datetime.strptime(raw_month, "%Y-%m")
    except ValueError as exc:
        raise ValueError("Calendar month must use YYYY-MM format.") from exc
    return parsed_month.strftime("%Y-%m")


def build_monthly_calendar(month, file_id, caption="", uploaded_at=None):
    """Build persisted metadata for one Telegram calendar image."""
    return {
        "month": month,
        "file_id": file_id,
        "caption": caption,
        "uploaded_at": uploaded_at or datetime.now(get_community_timezone()).isoformat(),
    }


def load_monthly_calendar(file_path):
    """Load monthly calendar metadata, returning an empty record when absent."""
    calendar = load_json(file_path, {})
    if not isinstance(calendar, dict):
        return {}
    if not calendar.get("month") or not calendar.get("file_id"):
        return {}
    return calendar


def save_monthly_calendar(file_path, calendar):
    """Persist monthly calendar metadata atomically."""
    save_json(file_path, calendar)


def format_calendar_title(calendar):
    """Return a Spanish title for a persisted monthly calendar."""
    month = calendar.get("month", "")
    try:
        year, month_number = month.split("-")
        month_name = SPANISH_MONTHS[int(month_number) - 1]
    except (ValueError, IndexError):
        return "🗓 Calendario del mes"
    return f"🗓 Calendario de {month_name} de {year}"
