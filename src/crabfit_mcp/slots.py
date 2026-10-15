"""Crab Fit UTC slot encoding and upstream-compatible expansion."""

import re
from datetime import date

_PATTERN = re.compile(r"([0-9]{2})([0-9]{2})-([0-9]{8}|[0-6])", re.ASCII)


def validate_times(times: list[str], *, allow_empty: bool) -> list[str]:
    if not times and not allow_empty:
        raise ValueError("times must not be empty")
    kind = None
    for value in times:
        match = _PATTERN.fullmatch(value)
        if match is None:
            raise ValueError("Slots must use UTC HHmm-DDMMYYYY (0900-20102026) or HHmm-d (0900-2; Sunday=0)")
        hour, minute, suffix = match.groups()
        if int(hour) > 23 or int(minute) > 59:
            raise ValueError("Slot hour must be 00..23 and minute 00..59")
        current = "date" if len(suffix) == 8 else "weekday"
        if kind is not None and kind != current:
            raise ValueError("Date and weekday slots cannot be mixed")
        kind = current
        if current == "date":
            try:
                date(int(suffix[4:]), int(suffix[2:4]), int(suffix[:2]))
            except ValueError:
                raise ValueError("Slot must contain a real Gregorian date") from None
    return list(dict.fromkeys(times))


def expand_times(times: list[str]) -> list[str]:
    validated = validate_times(times, allow_empty=True)
    return list(dict.fromkeys(
        value[:2] + minute + value[4:]
        for value in validated
        for minute in ("00", "15", "30", "45")
    ))
