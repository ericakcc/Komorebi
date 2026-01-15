"""Tests for calendar tools."""

from unittest.mock import MagicMock, patch

import pytest

from komorebi.tools import calendar


@pytest.fixture(autouse=True)
def setup_config():
    """Set up calendar config for all tests."""
    calendar.set_config(
        {
            "credentials_path": "~/.config/komorebi/credentials.json",
            "token_path": "~/.config/komorebi/token.json",
            "default_calendar": "primary",
        }
    )


@pytest.fixture
def mock_events():
    """Sample calendar events."""
    return {
        "items": [
            {
                "summary": "Team Standup",
                "start": {"dateTime": "2026-01-15T09:00:00+08:00"},
                "end": {"dateTime": "2026-01-15T10:00:00+08:00"},
            },
            {
                "summary": "1:1 with Manager",
                "start": {"dateTime": "2026-01-15T14:00:00+08:00"},
                "end": {"dateTime": "2026-01-15T15:00:00+08:00"},
            },
        ]
    }


@pytest.fixture
def mock_service(mock_events):
    """Create mock Calendar API service."""
    service = MagicMock()
    service.events().list().execute.return_value = mock_events
    service.events().insert().execute.return_value = {
        "summary": "Test Event",
        "htmlLink": "https://calendar.google.com/event/123",
    }
    return service


class TestListEvents:
    """Tests for list_events tool."""

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_list_events_returns_events(self, mock_get_service, mock_service):
        """Should return formatted event list."""
        mock_get_service.return_value = mock_service

        result = await calendar.list_events.handler({"date": "2026-01-15"})

        assert result.get("is_error") is not True
        text = result["content"][0]["text"]
        assert "Team Standup" in text
        assert "1:1 with Manager" in text
        assert "09:00-10:00" in text
        assert "Total: 2 event(s)" in text

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_list_events_no_events(self, mock_get_service, mock_service):
        """Should handle no events gracefully."""
        mock_service.events().list().execute.return_value = {"items": []}
        mock_get_service.return_value = mock_service

        result = await calendar.list_events.handler({"date": "2026-01-15"})

        assert result.get("is_error") is not True
        assert "No events" in result["content"][0]["text"]

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_list_events_uses_default_date(self, mock_get_service, mock_service):
        """Should default to today if no date provided."""
        mock_get_service.return_value = mock_service

        result = await calendar.list_events.handler({})

        assert result.get("is_error") is not True
        # Should call list() with some date
        mock_service.events().list.assert_called()

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_list_events_handles_all_day_event(self, mock_get_service, mock_service):
        """Should format all-day events correctly."""
        mock_service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Holiday",
                    "start": {"date": "2026-01-15"},
                    "end": {"date": "2026-01-16"},
                }
            ]
        }
        mock_get_service.return_value = mock_service

        result = await calendar.list_events.handler({"date": "2026-01-15"})

        text = result["content"][0]["text"]
        assert "all day" in text
        assert "Holiday" in text

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_list_events_handles_api_error(self, mock_get_service):
        """Should return error on API failure."""
        from googleapiclient.errors import HttpError

        mock_get_service.side_effect = HttpError(resp=MagicMock(status=403), content=b"Forbidden")

        result = await calendar.list_events.handler({})

        assert result.get("is_error") is True
        assert "API error" in result["content"][0]["text"]

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_list_events_handles_missing_credentials(self, mock_get_service):
        """Should return error if credentials not found."""
        mock_get_service.side_effect = FileNotFoundError("credentials not found")

        result = await calendar.list_events.handler({})

        assert result.get("is_error") is True
        assert "credentials" in result["content"][0]["text"].lower()


class TestAddEvent:
    """Tests for add_event tool."""

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_add_event_creates_timed_event(self, mock_get_service, mock_service):
        """Should create a timed event."""
        mock_get_service.return_value = mock_service

        result = await calendar.add_event.handler(
            {
                "summary": "Code Review",
                "start_time": "14:00",
                "end_time": "15:00",
                "date": "2026-01-15",
            }
        )

        assert result.get("is_error") is not True
        text = result["content"][0]["text"]
        assert "Event Created" in text
        assert "Code Review" in text

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_add_event_creates_all_day_event(self, mock_get_service, mock_service):
        """Should create an all-day event."""
        mock_get_service.return_value = mock_service

        result = await calendar.add_event.handler(
            {
                "summary": "Day Off",
                "start_time": "all_day",
                "date": "2026-01-15",
            }
        )

        assert result.get("is_error") is not True
        assert "Event Created" in result["content"][0]["text"]

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_add_event_defaults_duration(self, mock_get_service, mock_service):
        """Should default to 1 hour if end_time not provided."""
        mock_get_service.return_value = mock_service

        result = await calendar.add_event.handler(
            {
                "summary": "Quick Meeting",
                "start_time": "10:00",
                "date": "2026-01-15",
            }
        )

        assert result.get("is_error") is not True
        # Verify insert was called
        mock_service.events().insert.assert_called()

    @pytest.mark.asyncio
    async def test_add_event_requires_summary(self):
        """Should error if summary not provided."""
        result = await calendar.add_event.handler({"start_time": "10:00", "date": "2026-01-15"})

        assert result.get("is_error") is True
        assert "summary" in result["content"][0]["text"].lower()

    @pytest.mark.asyncio
    async def test_add_event_requires_start_time(self):
        """Should error if start_time not provided."""
        result = await calendar.add_event.handler({"summary": "Test Event", "date": "2026-01-15"})

        assert result.get("is_error") is True
        assert "start time" in result["content"][0]["text"].lower()

    @pytest.mark.asyncio
    @patch("komorebi.tools.calendar._get_calendar_service")
    async def test_add_event_handles_api_error(self, mock_get_service):
        """Should return error on API failure."""
        from googleapiclient.errors import HttpError

        mock_get_service.side_effect = HttpError(resp=MagicMock(status=403), content=b"Forbidden")

        result = await calendar.add_event.handler({"summary": "Test", "start_time": "10:00"})

        assert result.get("is_error") is True


class TestFormatEvent:
    """Tests for _format_event helper."""

    def test_format_timed_event(self):
        """Should format timed event with times."""
        event = {
            "summary": "Meeting",
            "start": {"dateTime": "2026-01-15T09:00:00+08:00"},
            "end": {"dateTime": "2026-01-15T10:00:00+08:00"},
        }

        result = calendar._format_event(event)

        assert "09:00-10:00" in result
        assert "Meeting" in result

    def test_format_all_day_event(self):
        """Should format all-day event."""
        event = {
            "summary": "Holiday",
            "start": {"date": "2026-01-15"},
            "end": {"date": "2026-01-16"},
        }

        result = calendar._format_event(event)

        assert "all day" in result
        assert "Holiday" in result

    def test_format_event_no_title(self):
        """Should handle missing title."""
        event = {
            "start": {"dateTime": "2026-01-15T09:00:00+08:00"},
            "end": {"dateTime": "2026-01-15T10:00:00+08:00"},
        }

        result = calendar._format_event(event)

        assert "(no title)" in result
