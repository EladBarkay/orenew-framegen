"""A frame's date as text (DESIGN.md 4.3, T-14).

Gregorian formats go through Babel, which uses the same Unicode CLDR data as the
browser's Intl.DateTimeFormat, so a pattern or style reads the same in any locale.
Hebrew formats go through pyluach. An evening event (afterSunset) falls on the next
Hebrew date; the Gregorian date stays as given.
"""

import datetime

from babel import Locale
from babel.dates import format_date
from pyluach.dates import HebrewDate

from framegen.spec.text import Date, DateFormat, GregorianFormat


def date_text(date: Date) -> str:
    """The text the frame shows: the formats, joined on one line or stacked one per line
    (a joiner of null), or the text typed by hand instead."""
    if date.override is not None:
        return date.override
    parts = [_format(date, format) for format in date.formats]
    return "\n".join(parts) if date.joiner is None else date.joiner.join(parts)


def _format(date: Date, format: DateFormat) -> str:
    if isinstance(format, GregorianFormat):
        pattern = format.pattern or format.style
        assert pattern is not None  # one of them is given (GregorianFormat checks it)
        return str(format_date(date.value, pattern, locale=Locale.parse(format.locale, sep="-")))
    day = date.value + datetime.timedelta(days=1 if date.after_sunset else 0)
    hebrew = HebrewDate.from_pydate(day)
    if format.numerals == "hebrew":
        # Gematria, with geresh and gershayim, and the year without its thousands.
        number, year = hebrew.hebrew_day(), hebrew.hebrew_year()
    else:
        number, year = str(hebrew.day), str(hebrew.year)
    month = hebrew.month_name(hebrew=True)
    match format.style:
        case "day-month-year":
            return f"{number} {month} {year}"
        case "month-year":
            return f"{month} {year}"
        case "year":
            return year
