from datetime import datetime
from .build_ics import create_ics

def build_ios_push(event: dict):
    """
    event = {
        "summary": "...",
        "start": datetime,
        "end": datetime,
        "description": "..."
    }
    """

    ics_file = create_ics(
        title=event["summary"],
        start=event["start"],
        end=event["end"],
        description=event.get("description", "")
    )

    push_payload = {
        "title": "📅 Kalender-Eintrag verfügbar",
        "body": event["summary"],
        "ics_file": ics_file,
        "ios_action": "open_calendar"
    }

    return push_payload
