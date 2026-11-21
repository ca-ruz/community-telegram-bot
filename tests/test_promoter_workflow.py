import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.promoter import check_calendar


class FakeBot:
    """Minimal Telegram bot double for calendar reminder tests."""

    def __init__(self, failures=None):
        self.failures = set(failures or [])
        self.messages = []

    async def send_message(self, chat_id, message, **kwargs):
        """Record a reminder or simulate a failed subscriber delivery."""
        if chat_id in self.failures:
            raise RuntimeError("simulated subscriber failure")
        self.messages.append({"chat_id": chat_id, "message": message, "kwargs": kwargs})


def make_config(tmp_path):
    """Build the file-backed configuration needed by the calendar job."""
    return {
        "ADMIN_ID": 42,
        "SCOPES": [],
        "SERVICE_ACCOUNT_FILE": "unused.json",
        "CALENDAR_ID": "calendar-id",
        "REMINDERS_FILE": str(tmp_path / "sent_reminders.json"),
        "PROMOTED_FILE": str(tmp_path / "notified_promos.json"),
        "PENDING_PROMOS_FILE": str(tmp_path / "pending_promos.json"),
        "IMPORTED_EVENTS_FILE": str(tmp_path / "imported_events.json"),
        "REMINDER_RULES": {"24h": timedelta(days=1), "1h": timedelta(hours=1)},
    }


def make_state(subscribers):
    """Build the state required by the calendar job."""
    return {
        "sent_reminders": {},
        "subscribers": set(subscribers),
        "notified_promos": {},
        "pending_promos": {},
    }


def make_event(event_id="event-001", recurring_id=None, start="2026-10-15T12:00:00+00:00"):
    """Build a calendar event inside the reminder window."""
    event = {
        "id": event_id,
        "summary": "Bitcoin Meetup",
        "description": "Register at https://example.com/meetup",
        "htmlLink": "https://calendar.google.com/event",
        "start": {"dateTime": start},
    }
    if recurring_id:
        event["recurringEventId"] = recurring_id
    return event


def run_calendar_check(events, now, state, config, bot, source="google_calendar"):
    """Run the calendar job with the selected event source mocked."""
    context = SimpleNamespace(bot=bot, bot_data={})
    if source == "meetup_ics":
        config["EVENT_SOURCE"] = source
        config["MEETUP_ICS_URL"] = "https://example.com/events.ics"
        with patch(
            "core.promoter.fetch_upcoming_events_for_source",
            return_value=(events, now),
        ):
            asyncio.run(check_calendar(context, config, state))
        return

    with patch("core.promoter.get_calendar_service_with_creds", return_value=object()), patch(
        "core.promoter.fetch_upcoming_events", return_value=(events, now)
    ):
        asyncio.run(check_calendar(context, config, state))


def make_proactive_event(event_id="meetup-001"):
    """Build an event inside the proactive three-day suggestion window."""
    return make_event(
        event_id,
        start="2026-10-17T12:00:00+00:00",
    )


def prepare_proactive_check(tmp_path, event_id="meetup-001"):
    """Build state and config for a deterministic proactive suggestion check."""
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    state = make_state(set())
    state["imported_events"] = {}
    config = make_config(tmp_path)
    config["REMINDER_RULES"]["72h"] = timedelta(days=3)
    return now, state, config, make_proactive_event(event_id)


def test_check_calendar_sends_subscriber_reminders_and_deduplicates(tmp_path):
    """Calendar reminders reach subscribers once for the same-day stage."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101, 202})
    config = make_config(tmp_path)
    bot = FakeBot()
    event = make_event()

    run_calendar_check([event], now, state, config, bot)
    run_calendar_check([event], now, state, config, bot)

    subscriber_messages = [
        message for message in bot.messages if message["chat_id"] in state["subscribers"]
    ]
    assert {message["chat_id"] for message in subscriber_messages} == {101, 202}
    storage_key = "event-001_20261015T120000Z"
    assert set(state["sent_reminders"][storage_key].keys()) == {"same_day"}
    assert set(state["sent_reminders"][storage_key]["same_day"]) == {101, 202}
    assert "https://example.com/meetup" in subscriber_messages[0]["message"]


def test_check_calendar_appends_configured_community_link(tmp_path):
    """Calendar reminders append the configured community CTA after the event link."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101})
    config = make_config(tmp_path)
    config["COMMUNITY_GROUP_URL"] = "https://t.me/bitcoin_gdl"
    bot = FakeBot()

    run_calendar_check([make_event()], now, state, config, bot)

    message = bot.messages[0]["message"]
    assert "Únete al grupo de la comunidad" in message
    assert message.index("https://example.com/meetup") < message.index(
        "Únete al grupo de la comunidad"
    )


def test_check_calendar_processes_a_recurring_series_once(tmp_path):
    """Only the first event instance in a recurring series is delivered per run."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101})
    config = make_config(tmp_path)
    bot = FakeBot()
    events = [
        make_event("event-001", recurring_id="series-001"),
        make_event(
            "event-002",
            recurring_id="series-001",
            start="2026-10-15T13:00:00+00:00",
        ),
    ]

    run_calendar_check(events, now, state, config, bot)

    subscriber_messages = [
        message for message in bot.messages if message["chat_id"] in state["subscribers"]
    ]
    assert len(subscriber_messages) == 1
    assert subscriber_messages[0]["chat_id"] == 101


def test_check_calendar_respects_event_notification_preferences(tmp_path):
    """Calendar reminders skip users who disabled event notifications."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101, 202})
    state["notification_preferences"] = {
        "101": {"events": True, "coffee": False, "payments": False},
        "202": {"events": False, "coffee": True, "payments": False},
    }
    config = make_config(tmp_path)
    bot = FakeBot()

    run_calendar_check([make_event()], now, state, config, bot)

    subscriber_messages = [
        message for message in bot.messages if message["chat_id"] in {101, 202}
    ]
    assert [message["chat_id"] for message in subscriber_messages] == [101]


def test_check_calendar_retries_failed_subscriber_delivery(tmp_path):
    """Failed subscriber deliveries remain eligible for a later scheduler run."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101, 202})
    config = make_config(tmp_path)
    bot = FakeBot(failures={202})
    event = make_event()

    run_calendar_check([event], now, state, config, bot)

    storage_key = "event-001_20261015T120000Z"
    assert set(state["sent_reminders"][storage_key]["same_day"]) == {101}

    bot.failures.clear()
    run_calendar_check([event], now, state, config, bot)

    subscriber_messages = [
        message for message in bot.messages if message["chat_id"] in state["subscribers"]
    ]
    assert [message["chat_id"] for message in subscriber_messages] == [101, 202]
    assert set(state["sent_reminders"][storage_key]["same_day"]) == {101, 202}


def test_check_calendar_sends_same_day_reminders_to_groups(tmp_path):
    """Scheduled same-day reminders reach configured groups as well as DMs."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101})
    state["groups"] = {-100}
    state["group_notification_categories"] = {
        "events": [-100],
        "payments": [],
        "coworking": [],
    }
    config = make_config(tmp_path)
    bot = FakeBot()

    run_calendar_check([make_event()], now, state, config, bot)

    assert [message["chat_id"] for message in bot.messages[:2]] == [101, -100]
    assert bot.messages[2]["chat_id"] == 42
    storage_key = "event-001_20261015T120000Z"
    assert state["sent_reminders"][storage_key]["same_day_groups"] == [-100]


def test_check_calendar_skips_groups_without_event_category(tmp_path):
    """Scheduled event reminders exclude groups outside the event category."""
    now = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
    state = make_state({101})
    state["groups"] = {-100, -200}
    state["group_notification_categories"] = {
        "events": [-100],
        "payments": [-200],
        "coworking": [-100, -200],
    }
    config = make_config(tmp_path)
    bot = FakeBot()

    run_calendar_check([make_event()], now, state, config, bot)

    assert [message["chat_id"] for message in bot.messages[:2]] == [101, -100]


def test_meetup_event_with_assigned_flyer_is_not_suggested_again(tmp_path):
    """An imported Meetup event with an assigned flyer gets no proactive prompt."""
    now, state, config, event = prepare_proactive_check(tmp_path)
    state["imported_events"]["meetup_ics:meetup-001"] = {
        "source": "meetup_ics",
        "source_id": "meetup-001",
        "flyer_file_id": "existing-telegram-photo",
    }
    bot = FakeBot()

    run_calendar_check([event], now, state, config, bot, source="meetup_ics")

    assert bot.messages == []


def test_meetup_event_without_flyer_still_gets_proactive_suggestion(tmp_path):
    """Imported events that still need flyers remain eligible for suggestions."""
    now, state, config, event = prepare_proactive_check(tmp_path)
    bot = FakeBot()

    run_calendar_check([event], now, state, config, bot, source="meetup_ics")

    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == config["ADMIN_ID"]
    assert "Bitcoin Meetup" in bot.messages[0]["message"]


def test_event_with_existing_generated_flyer_is_not_suggested_again(tmp_path):
    """The existing generated-flyer state continues to prevent repeated prompts."""
    now, state, config, event = prepare_proactive_check(tmp_path)
    storage_key = "meetup-001_20261017T120000Z"
    state["notified_promos"][storage_key] = {
        "notified_thresholds": [],
        "flyer_created": True,
    }
    bot = FakeBot()

    run_calendar_check([event], now, state, config, bot)

    assert bot.messages == []


def test_check_calendar_stops_after_calendar_fetch_failure(tmp_path):
    """A calendar fetch failure does not send subscriber messages."""
    now = datetime.now(timezone.utc)
    state = make_state({101})
    config = make_config(tmp_path)
    bot = FakeBot()
    context = SimpleNamespace(bot=bot, bot_data={})

    with patch("core.promoter.get_calendar_service_with_creds", return_value=object()), patch(
        "core.promoter.fetch_upcoming_events", side_effect=RuntimeError("calendar unavailable")
    ):
        asyncio.run(check_calendar(context, config, state))

    assert bot.messages == []
