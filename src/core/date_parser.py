import re
import datetime
from datetime import timedelta
import logging

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
RANGE_SEPARATOR_PATTERN = r"(?:\s+(?:to|until|through|till)\s+|\s*-\s*)"


def parse_dates(query: str) -> list[str]:
    logging.info(f"[TEMPORAL PARSING] Parsing dates from query: {query}")
    today = datetime.date.today()
    
    # 1. Look for explicit YYYY-MM-DD
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", query)
    if len(dates) >= 2:
        return [dates[0], dates[1]]
    if len(dates) == 1:
        return [dates[0], dates[0]]

    # 2. Look for DD/MM/YYYY or DD-MM-YYYY (common in enterprise chat)
    slash_dates = re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", query)
    if len(slash_dates) >= 2:
        start = _safe_date(int(slash_dates[0][2]), int(slash_dates[0][1]), int(slash_dates[0][0]))
        end = _safe_date(int(slash_dates[1][2]), int(slash_dates[1][1]), int(slash_dates[1][0]))
        if start and end:
            return [start.isoformat(), end.isoformat()]
    if len(slash_dates) == 1:
        parsed = _safe_date(int(slash_dates[0][2]), int(slash_dates[0][1]), int(slash_dates[0][0]))
        if parsed:
            return [parsed.isoformat(), parsed.isoformat()]

    natural_dates = _parse_natural_date_range(query, today)
    if natural_dates:
        logging.info(f"[DATE NORMALIZATION] Normalized natural range to: {natural_dates[0]} to {natural_dates[1]}")
        return natural_dates

    # 3. Look for relative days
    lowered = query.lower()
    
    start_date = None
    end_date = None
    
    if "today" in lowered:
        start_date = today
        end_date = today
    elif "tomorrow" in lowered:
        start_date = today + timedelta(days=1)
        end_date = start_date
    elif "next week" in lowered:
        # Start next Monday, end next Friday
        days_ahead = 7 - today.weekday()
        start_date = today + timedelta(days=days_ahead)
        end_date = start_date + timedelta(days=4)
    elif "this week" in lowered or "entire week" in lowered:
        # Remaining current work week to avoid past-date rejection.
        start_date = today
        end_date = today + timedelta(days=max(0, 4 - today.weekday()))
    elif "next monday" in lowered:
        days_ahead = 7 - today.weekday()
        start_date = today + timedelta(days=days_ahead)
        end_date = start_date
    elif "coming monday" in lowered:
        days_ahead = (0 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        start_date = today + timedelta(days=days_ahead)
        end_date = start_date
    elif "next tuesday and wednesday" in lowered or "next tuesday to wednesday" in lowered:
        tuesday = _next_weekday(today, 1)
        start_date = tuesday
        end_date = tuesday + timedelta(days=1)
    elif "tomorrow evening" in lowered:
        start_date = today + timedelta(days=1)
        end_date = start_date
    elif "next friday" in lowered:
        days_ahead = 4 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        start_date = today + timedelta(days=days_ahead)
        end_date = start_date
    elif "this friday" in lowered:
        days_ahead = 4 - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
        start_date = today + timedelta(days=days_ahead)
        end_date = start_date
    elif "till friday" in lowered or "until friday" in lowered:
        days_ahead = 4 - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
        start_date = today
        end_date = today + timedelta(days=days_ahead)
    
    if start_date and end_date:
        logging.info(f"[DATE NORMALIZATION] Normalized to: {start_date.isoformat()} to {end_date.isoformat()}")
        return [start_date.isoformat(), end_date.isoformat()]
        
    # If no dates found, return empty so it can prompt the user instead of defaulting
    logging.info("[TEMPORAL PARSING] No dates found. Returning empty.")
    return []


def _parse_natural_date_range(query: str, today: datetime.date) -> list[str]:
    lowered = query.lower()
    parsed_range = _parse_day_month_range(lowered, today) or _parse_month_day_range(lowered, today)
    if parsed_range:
        return [parsed_range[0].isoformat(), parsed_range[1].isoformat()]

    mentions = _extract_natural_date_mentions(lowered, today)
    if len(mentions) >= 2:
        return [mentions[0].isoformat(), mentions[1].isoformat()]
    if len(mentions) == 1:
        return [mentions[0].isoformat(), mentions[0].isoformat()]
    return []


def _parse_day_month_range(text: str, today: datetime.date) -> tuple[datetime.date, datetime.date] | None:
    pattern = re.compile(
        rf"\b(?:from\s+)?"
        rf"(?P<start_day>\d{{1,2}})(?:st|nd|rd|th)?"
        rf"(?:\s+(?P<start_month>{MONTH_PATTERN}))?"
        rf"(?:\s*,?\s*(?P<start_year>\d{{4}}))?"
        rf"{RANGE_SEPARATOR_PATTERN}"
        rf"(?P<end_day>\d{{1,2}})(?:st|nd|rd|th)?"
        rf"(?:\s+(?P<end_month>{MONTH_PATTERN}))?"
        rf"(?:\s*,?\s*(?P<end_year>\d{{4}}))?\b"
    )
    for match in pattern.finditer(text):
        start_month_name = match.group("start_month")
        end_month_name = match.group("end_month")
        if not start_month_name and not end_month_name:
            continue
        start_month = MONTHS[start_month_name or end_month_name]
        end_month = MONTHS[end_month_name or start_month_name]
        start_year = int(match.group("start_year")) if match.group("start_year") else None
        end_year = int(match.group("end_year")) if match.group("end_year") else None
        return _build_date_range(
            today,
            int(match.group("start_day")),
            start_month,
            start_year,
            int(match.group("end_day")),
            end_month,
            end_year,
        )
    return None


def _parse_month_day_range(text: str, today: datetime.date) -> tuple[datetime.date, datetime.date] | None:
    pattern = re.compile(
        rf"\b(?:from\s+)?"
        rf"(?P<start_month>{MONTH_PATTERN})\s+"
        rf"(?P<start_day>\d{{1,2}})(?:st|nd|rd|th)?"
        rf"(?:\s*,?\s*(?P<start_year>\d{{4}}))?"
        rf"{RANGE_SEPARATOR_PATTERN}"
        rf"(?:(?P<end_month>{MONTH_PATTERN})\s+)?"
        rf"(?P<end_day>\d{{1,2}})(?:st|nd|rd|th)?"
        rf"(?:\s*,?\s*(?P<end_year>\d{{4}}))?\b"
    )
    match = pattern.search(text)
    if not match:
        return None
    start_month = MONTHS[match.group("start_month")]
    end_month = MONTHS[match.group("end_month") or match.group("start_month")]
    start_year = int(match.group("start_year")) if match.group("start_year") else None
    end_year = int(match.group("end_year")) if match.group("end_year") else None
    return _build_date_range(
        today,
        int(match.group("start_day")),
        start_month,
        start_year,
        int(match.group("end_day")),
        end_month,
        end_year,
    )


def _extract_natural_date_mentions(text: str, today: datetime.date) -> list[datetime.date]:
    mentions: list[datetime.date] = []
    patterns = [
        re.compile(
            rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
            rf"(?P<month>{MONTH_PATTERN})(?:\s*,?\s*(?P<year>\d{{4}}))?\b"
        ),
        re.compile(
            rf"\b(?P<month>{MONTH_PATTERN})\s+"
            rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(?P<year>\d{{4}}))?\b"
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            parsed = _safe_date(
                _resolve_year(today, MONTHS[match.group("month")], int(match.group("day")), match.group("year")),
                MONTHS[match.group("month")],
                int(match.group("day")),
            )
            if parsed and parsed not in mentions:
                mentions.append(parsed)
    return sorted(mentions)


def _build_date_range(
    today: datetime.date,
    start_day: int,
    start_month: int,
    start_year: int | None,
    end_day: int,
    end_month: int,
    end_year: int | None,
) -> tuple[datetime.date, datetime.date] | None:
    if start_year:
        resolved_start_year = start_year
    else:
        temp_start = _safe_date(today.year, start_month, start_day)
        resolved_start_year = today.year + 1 if temp_start and temp_start < today else today.year

    start = _safe_date(resolved_start_year, start_month, start_day)
    if not start:
        return None

    if end_year:
        resolved_end_year = end_year
    else:
        temp_end = _safe_date(start.year, end_month, end_day)
        resolved_end_year = start.year + 1 if temp_end and temp_end < start else start.year

    end = _safe_date(resolved_end_year, end_month, end_day)
    if not end:
        return None

    return (start, end)


def _resolve_year(today: datetime.date, month: int, day: int, explicit_year: str | None) -> int:
    if explicit_year:
        return int(explicit_year)
    year = today.year
    parsed = _safe_date(year, month, day)
    if parsed and parsed < today:
        year += 1
    return year


def _safe_date(year: int, month: int, day: int) -> datetime.date | None:
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _next_weekday(base: datetime.date, weekday: int) -> datetime.date:
    days_ahead = (weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)
