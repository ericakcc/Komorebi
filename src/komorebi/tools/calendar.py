"""Calendar integration tools for Komorebi.

Provides Google Calendar integration:
- list_events: Query events for a date range
- add_event: Create new calendar events

Setup:
    1. Create OAuth 2.0 credentials at Google Cloud Console
    2. Download credentials.json to ~/.config/komorebi/
    3. First use will open browser for authorization
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..auth.google_auth import get_calendar_credentials

# Configuration set by agent
_config: dict[str, Any] = {}


def set_config(config: dict[str, Any]) -> None:
    """Set calendar configuration.

    Args:
        config: Dictionary with credentials_path, token_path, default_calendar.
    """
    global _config
    _config = config


def _get_calendar_service():
    """Get authenticated Calendar API service.

    Returns:
        Google Calendar API service object.

    Raises:
        FileNotFoundError: If credentials not configured.
    """
    credentials_path = Path(
        _config.get("credentials_path", "~/.config/komorebi/credentials.json")
    ).expanduser()
    token_path = Path(_config.get("token_path", "~/.config/komorebi/token.json")).expanduser()

    creds = get_calendar_credentials(credentials_path, token_path)
    return build("calendar", "v3", credentials=creds)


def _format_event(event: dict[str, Any]) -> str:
    """Format a calendar event for display.

    Args:
        event: Google Calendar event object.

    Returns:
        Formatted string like "- 09:00-10:00 | Meeting".
    """
    start = event.get("start", {})
    end = event.get("end", {})
    summary = event.get("summary", "(no title)")

    # All-day event
    if "date" in start:
        return f"- all day | {summary}"

    # Timed event
    start_dt = datetime.fromisoformat(start.get("dateTime", "").replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.get("dateTime", "").replace("Z", "+00:00"))

    return f"- {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')} | {summary}"


@tool(
    name="list_events",
    description="Query calendar events for a date range. Defaults to today's events.",
    input_schema={
        "date": str,
        "days": int,
        "calendar_id": str,
    },
)
async def list_events(args: dict[str, Any]) -> dict[str, Any]:
    """List calendar events for a date range.

    Args:
        args: Dictionary containing:
            - date: Start date (YYYY-MM-DD), defaults to today
            - days: Number of days to query, defaults to 1
            - calendar_id: Calendar ID, defaults to "primary"

    Returns:
        Tool response with formatted event list.
    """
    date_str = args.get("date", datetime.now().strftime("%Y-%m-%d"))
    days = args.get("days", 1)
    calendar_id = args.get("calendar_id", _config.get("default_calendar", "primary"))

    try:
        service = _get_calendar_service()

        # Calculate time range
        start_date = datetime.strptime(date_str, "%Y-%m-%d")
        end_date = start_date + timedelta(days=days)

        # RFC3339 format with timezone
        time_min = start_date.strftime("%Y-%m-%dT00:00:00Z")
        time_max = end_date.strftime("%Y-%m-%dT00:00:00Z")

        # Query events
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return {
                "content": [
                    {"type": "text", "text": f"## {date_str} - No events\n\nNo events scheduled."}
                ],
            }

        # Format output
        lines = [f"## {date_str} Events\n"]
        for event in events:
            lines.append(_format_event(event))
        lines.append(f"\nTotal: {len(events)} event(s)")

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
        }

    except FileNotFoundError as e:
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }
    except HttpError as e:
        return {
            "content": [{"type": "text", "text": f"Google Calendar API error: {e}"}],
            "is_error": True,
        }


@tool(
    name="add_event",
    description="Add a new calendar event. Supports timed events and all-day events.",
    input_schema={
        "summary": str,
        "start_time": str,
        "end_time": str,
        "date": str,
        "description": str,
        "calendar_id": str,
    },
)
async def add_event(args: dict[str, Any]) -> dict[str, Any]:
    """Add a new calendar event.

    Args:
        args: Dictionary containing:
            - summary: Event title (required)
            - start_time: Start time HH:MM or "all_day" (required)
            - end_time: End time HH:MM, defaults to start_time + 1 hour
            - date: Date YYYY-MM-DD, defaults to today
            - description: Event description (optional)
            - calendar_id: Calendar ID, defaults to "primary"

    Returns:
        Tool response confirming event creation.
    """
    summary = args.get("summary", "")
    start_time = args.get("start_time", "")
    end_time = args.get("end_time", "")
    date_str = args.get("date", datetime.now().strftime("%Y-%m-%d"))
    description = args.get("description", "")
    calendar_id = args.get("calendar_id", _config.get("default_calendar", "primary"))

    if not summary:
        return {
            "content": [{"type": "text", "text": "Event summary (title) is required."}],
            "is_error": True,
        }

    if not start_time:
        return {
            "content": [{"type": "text", "text": "Start time is required (HH:MM or 'all_day')."}],
            "is_error": True,
        }

    try:
        service = _get_calendar_service()

        # Build event body
        event_body: dict[str, Any] = {"summary": summary}

        if description:
            event_body["description"] = description

        if start_time.lower() == "all_day":
            # All-day event
            event_body["start"] = {"date": date_str}
            # All-day events need end date to be the next day
            end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            event_body["end"] = {"date": end_date.strftime("%Y-%m-%d")}
        else:
            # Timed event
            start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")

            if end_time:
                end_dt = datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M")
            else:
                # Default to 1 hour duration
                end_dt = start_dt + timedelta(hours=1)

            # Use local timezone format
            event_body["start"] = {
                "dateTime": start_dt.isoformat(),
                "timeZone": "Asia/Taipei",
            }
            event_body["end"] = {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Asia/Taipei",
            }

        # Create event
        created_event = service.events().insert(calendarId=calendar_id, body=event_body).execute()

        event_link = created_event.get("htmlLink", "")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"## Event Created\n\n"
                    f"**Title**: {summary}\n"
                    f"**Date**: {date_str}\n"
                    f"**Time**: {start_time}"
                    + (f" - {end_time}" if end_time else "")
                    + f"\n**Link**: {event_link}",
                }
            ],
        }

    except FileNotFoundError as e:
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }
    except HttpError as e:
        return {
            "content": [{"type": "text", "text": f"Google Calendar API error: {e}"}],
            "is_error": True,
        }
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"Invalid date/time format: {e}"}],
            "is_error": True,
        }


# Export all tools for agent registration
all_tools = [list_events, add_event]
