"""Notification templates and dedupe key helpers."""

def dedupe_key(install_id: str, day: str, ntype: str) -> str:
    return f"{install_id}|{day}|{ntype}"


NOTIFICATION_TEMPLATES = {
    "daily_checkin": {
        "title": "With You",
        "body": "Want to do a gentle check-in?",
        "deep_link": "withyou://today",
    },
    "focus_first_step": {
        "title": "With You",
        "body": "Want help choosing a first step?",
        "deep_link": "withyou://focus",
    },
    "capture_sort": {
        "title": "With You",
        "body": "Want a 60-second sort?",
        "deep_link": "withyou://inbox",
    },
}
