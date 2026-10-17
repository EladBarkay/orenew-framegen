"""A frame's date as text (DESIGN.md 4.3, T-14).

Gregorian formats go through Babel, which uses the Unicode CLDR data behind the
browser's Intl.DateTimeFormat: a style reads as the browser's does, except that digits
are always 0-9, and a pattern is a CLDR pattern of day, month and year fields only (the
spec allows no others).

Each format is a bidi isolate taking its direction from its own first letter, or
left-to-right if it has none: so "12 10 2026" or "12 October 2026" keep their order on a
Hebrew line, and a Hebrew date keeps its own on an English one.
Hebrew formats go through pyluach. An evening event (afterSunset) falls on the next
Hebrew date; the Gregorian date stays as given.
"""

import datetime

from babel.dates import format_date
from pyluach.dates import HebrewDate

from framegen.spec.text import Date, DateFormat, GregorianFormat, parse_locale


def date_text(date: Date) -> str:
    """The text the frame shows: the formats, joined on one line or stacked one per line
    (a joiner of null), or the text typed by hand instead."""
    if date.override is not None:
        return date.override
    parts = [FSI + _format(date, format) + PDI for format in date.formats]
    return "\n".join(parts) if date.joiner is None else date.joiner.join(parts)


FSI, PDI = "\u2068", "\u2069"
"""First strong isolate and its end (Unicode bidi): draw nothing, measured as nothing."""


def _format(date: Date, format: DateFormat) -> str:
    if isinstance(format, GregorianFormat):
        pattern = format.pattern or format.style
        assert pattern is not None  # one of them is given (GregorianFormat checks it)
        locale = parse_locale(format.locale)
        assert locale is not None  # a locale CLDR has (GregorianFormat checks it)
        return str(format_date(date.value, pattern, locale=locale))
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
