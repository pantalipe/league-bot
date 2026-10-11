from pathlib import Path

def load_attendance_screens():
    """Calibrated Claim-ready/Claim-disabled states, independent of the reward day."""
    import json
    return json.loads((Path(__file__).resolve().parent / "assets/attendance.json").read_text(encoding="utf-8"))


def load_daily_navigation():
    import json
    return json.loads((Path(__file__).resolve().parent / "assets/daily-navigation.json").read_text(encoding="utf-8"))
