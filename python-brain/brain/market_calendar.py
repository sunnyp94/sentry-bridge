"""
US equity market calendar: full trading days only (no half-days, no holidays).
Used so the 8am opportunity scanner runs only on days the market has a full session.
"""
from datetime import date
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# NYSE closed (full day): (month, day). Add years as needed or use fixed (month, day) for recurring.
# New Year, MLK (3rd Mon Jan), Presidents (3rd Mon Feb), Good Friday (varies), Memorial (last Mon May),
# Juneteenth (June 19), Independence (July 4), Labor (1st Mon Sep), Thanksgiving (4th Thu Nov), Christmas (Dec 25).
_HOLIDAYS_MD = frozenset([
    (1, 1),   # New Year
    (7, 4),   # Independence Day
    (12, 25), # Christmas
    (6, 19),  # Juneteenth
])

# Half-days (early close): do not run scanner so we don't treat as a full opportunity day.
# July 3, Christmas Eve. Day-after-Thanksgiving is variable (4th Fri Nov), handled below.
_HALF_DAYS_MD = frozenset([
    (7, 3),   # Day before Independence Day
    (12, 24), # Christmas Eve
])


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> Optional[date]:
    """nth occurrence of weekday in month (1=first, -1=last). weekday 0=Mon, 6=Sun."""
    from calendar import monthcalendar
    cal = monthcalendar(year, month)
    if n == -1:
        # last occurrence: find last week that has the weekday
        for row in reversed(cal):
            if row[weekday]:
                return date(year, month, row[weekday])
        return None
    count = 0
    for row in cal:
        if row[weekday]:
            count += 1
            if count == n:
                return date(year, month, row[weekday])
    return None


def _nyse_holidays_for_year(year: int) -> frozenset:
    """Set of (month, day) and full date for variable holidays for the given year."""
    out = set()
    for m, d in _HOLIDAYS_MD:
        out.add((m, d))
    # MLK: 3rd Mon Jan
    d = _nth_weekday(year, 1, 0, 3)
    if d:
        out.add((d.month, d.day))
    # Presidents: 3rd Mon Feb
    d = _nth_weekday(year, 2, 0, 3)
    if d:
        out.add((d.month, d.day))
    # Good Friday: Friday before Easter (approx: use simple rule for recent years)
    # Easter: first Sunday after first full moon after vernal equinox. Simplified: use common dates.
    easter = _easter(year)
    if easter:
        from datetime import timedelta
        good_friday = easter - timedelta(days=2)
        out.add((good_friday.month, good_friday.day))
    # Memorial: last Mon May
    d = _nth_weekday(year, 5, 0, -1)
    if d:
        out.add((d.month, d.day))
    # Labor: 1st Mon Sep
    d = _nth_weekday(year, 9, 0, 1)
    if d:
        out.add((d.month, d.day))
    # Thanksgiving: 4th Thu Nov
    d = _nth_weekday(year, 11, 3, 4)
    if d:
        out.add((d.month, d.day))
    return frozenset(out)


def _half_days_for_year(year: int) -> frozenset:
    """Variable half-days: day after Thanksgiving (4th Fri Nov)."""
    out = set()
    d = _nth_weekday(year, 11, 4, 4)  # 4th Friday
    if d:
        out.add((d.month, d.day))
    return frozenset(out)


def _easter(year: int) -> Optional[date]:
    """Easter Sunday (Gregorian) for year. Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j = c // 4
    k = c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    n = (h - m + r + 90) // 25
    p = (h - m + r + n + 19) % 32
    return date(year, n, p)


def is_full_trading_day(d: Optional[date] = None) -> bool:
    """
    True if the given date is a full US equity trading day (weekday, not holiday, not half-day).
    If d is None, use today in Eastern time.
    """
    if d is None and ZoneInfo:
        from datetime import datetime
        d = datetime.now(ZoneInfo("America/New_York")).date()
    elif d is None:
        d = date.today()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    holidays = _nyse_holidays_for_year(d.year)
    if (d.month, d.day) in holidays:
        return False
    if (d.month, d.day) in _HALF_DAYS_MD:
        return False
    if (d.month, d.day) in _half_days_for_year(d.year):
        return False
    return True
