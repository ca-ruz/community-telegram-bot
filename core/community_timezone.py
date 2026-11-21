"""Runtime timezone selection for the configured community."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_COMMUNITY_TIMEZONE = "America/Mexico_City"
_community_timezone = ZoneInfo(DEFAULT_COMMUNITY_TIMEZONE)


def configure_community_timezone(timezone_name):
    """Set the process-wide timezone used by community workflows."""
    global _community_timezone
    try:
        _community_timezone = ZoneInfo(str(timezone_name))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        _community_timezone = ZoneInfo(DEFAULT_COMMUNITY_TIMEZONE)


def get_community_timezone():
    """Return the currently configured community timezone."""
    return _community_timezone
