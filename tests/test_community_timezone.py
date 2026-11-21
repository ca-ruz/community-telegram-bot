from datetime import datetime, timezone

import pytest

from core import community_timezone
from core.monthly_calendar import current_calendar_month
from core.prompts import build_event_parser_prompt


@pytest.fixture
def restore_community_timezone():
    """Restore the process timezone after tests that change it."""
    original_timezone = community_timezone.get_community_timezone()
    yield
    community_timezone.configure_community_timezone(original_timezone.key)


def test_configure_community_timezone_selects_valid_iana_zone(
    restore_community_timezone,
):
    """Valid IANA timezone values become the active community timezone."""
    community_timezone.configure_community_timezone("America/New_York")

    assert community_timezone.get_community_timezone().key == "America/New_York"


def test_configure_community_timezone_falls_back_for_unknown_zone(
    restore_community_timezone,
):
    """Unknown timezone names fall back to the documented default."""
    community_timezone.configure_community_timezone("Not/A_Timezone")

    assert (
        community_timezone.get_community_timezone().key
        == community_timezone.DEFAULT_COMMUNITY_TIMEZONE
    )


def test_calendar_month_uses_configured_community_timezone(
    restore_community_timezone,
):
    """Calendar month boundaries follow the configured local timezone."""
    community_timezone.configure_community_timezone("America/New_York")
    just_after_utc_month_boundary = datetime(
        2026, 11, 1, 2, 30, tzinfo=timezone.utc
    )

    assert current_calendar_month(just_after_utc_month_boundary) == "2026-10"


def test_event_parser_prompt_uses_configured_timezone():
    """Generated event-parser instructions use the community timezone."""
    prompt = build_event_parser_prompt(
        "2026-11-20",
        {
            "COMMUNITY_CITY": "Example City, Country",
            "COMMUNITY_TIMEZONE": "Europe/Madrid",
        },
    )

    assert '"timeZone": "Europe/Madrid"' in prompt
    assert "Default timezone is 'Europe/Madrid'" in prompt
