from datetime import datetime

def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")

def create_ics(title: str, start: datetime, end: datetime, description: str = "") -> str:
    """
    Creates a valid iOS-compatible .ics calendar event.
    """
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//RNV Monitor//DE
BEGIN:VEVENT
UID:{datetime.utcnow().timestamp()}
SUMMARY:{title}
DESCRIPTION:{description}
DTSTART:{format_dt(start)}
DTEND:{format_dt(end)}
END:VEVENT
END:VCALENDAR
"""
