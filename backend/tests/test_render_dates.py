"""Dates in Gregorian and Hebrew calendars (T-14), checked against known dates."""

import re
from typing import Any

import pytest

from framegen.render.dates import date_text
from framegen.render.svg import render_svg
from framegen.spec import SpecInvalid, read_spec
from framegen.spec.text import Date

HEBREW = {"calendar": "hebrew"}


def date(value: str = "2026-10-12", *formats: dict[str, Any], **more: Any) -> Date:
    return Date.model_validate({
        "value": value, "font": "heebo", "color": "#000000", "size": 0.03,
        "formats": list(formats) or [HEBREW], "slot": "bottom-band", **more,
    })  # fmt: skip


@pytest.mark.parametrize(
    ("value", "after_sunset", "text"),
    [
        ("2026-10-12", False, "א׳ חשון תשפ״ז"),
        ("2026-10-12", True, "ב׳ חשון תשפ״ז"),
        # Rosh Hashana 5787 starts on the evening of 11 September 2026.
        ("2026-09-11", False, "כ״ט אלול תשפ״ו"),
        ("2026-09-11", True, "א׳ תשרי תשפ״ז"),
        # 5787 is a leap year: Purim is on 14 Adar II, 23 March 2027.
        ("2027-02-20", False, "י״ג אדר א׳ תשפ״ז"),
        ("2027-03-23", False, "י״ד אדר ב׳ תשפ״ז"),
    ],
)
def test_hebrew_dates_in_gematria(value: str, after_sunset: bool, text: str) -> None:
    assert date_text(date(value, afterSunset=after_sunset)) == text


@pytest.mark.parametrize(
    ("style", "numerals", "text"),
    [
        ("day-month-year", "digits", "1 חשון 5787"),
        ("month-year", "hebrew", "חשון תשפ״ז"),
        ("year", "hebrew", "תשפ״ז"),
        ("year", "digits", "5787"),
    ],
)
def test_hebrew_styles_and_numerals(style: str, numerals: str, text: str) -> None:
    fmt = {"calendar": "hebrew", "style": style, "numerals": numerals}
    assert date_text(date("2026-10-12", fmt)) == text


@pytest.mark.parametrize(
    ("fmt", "text"),
    [
        ({"pattern": "dd.MM.yyyy"}, "12.10.2026"),
        ({"pattern": "d.M.yy"}, "12.10.26"),
        ({"pattern": "d MMMM yyyy", "locale": "en"}, "12 October 2026"),
        ({"pattern": "d MMMM yyyy"}, "12 אוקטובר 2026"),
        ({"style": "long"}, "12 באוקטובר 2026"),
        ({"style": "full", "locale": "en-US"}, "Monday, October 12, 2026"),
        ({"style": "short", "locale": "en-GB"}, "12/10/2026"),
    ],
)
def test_gregorian_patterns_and_styles(fmt: dict[str, str], text: str) -> None:
    assert date_text(date("2026-10-12", {"calendar": "gregorian", **fmt})) == text


def test_after_sunset_moves_only_the_hebrew_date() -> None:
    both = date("2026-09-11", HEBREW, {"calendar": "gregorian", "pattern": "d.M.yyyy"},
                afterSunset=True)  # fmt: skip
    assert date_text(both) == "א׳ תשרי תשפ״ז · 11.9.2026"


def test_formats_join_or_stack() -> None:
    gregorian = {"calendar": "gregorian", "pattern": "dd.MM.yy"}
    assert date_text(date("2026-10-12", HEBREW, gregorian, joiner=" | ")) == (
        "א׳ חשון תשפ״ז | 12.10.26"
    )
    assert date_text(date("2026-10-12", HEBREW, gregorian, joiner=None)) == (
        "א׳ חשון תשפ״ז\n12.10.26"
    )


def test_the_text_can_be_typed_by_hand() -> None:
    assert date_text(date(override="מוצ״ש, ערב חג")) == "מוצ״ש, ערב חג"


@pytest.mark.parametrize("locale", ["xx", "und", "iw"])
def test_an_unknown_locale_is_refused(locale: str) -> None:
    inset = {"top": 0.1, "bottom": 0.2, "start": 0.1, "end": 0.1}
    with pytest.raises(SpecInvalid) as error:
        read_spec({
            "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
            "window": {"shape": "rectangle", "portrait": {"inset": inset},
                       "landscape": {"inset": inset}},
            "decoration": {"archetype": "surround", "layers": [
                {"kind": "vector", "shape": "rectangle", "color": "#336699",
                 "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
            "date": {**date().model_dump(by_alias=True, mode="json"),
                     "formats": [{"calendar": "gregorian", "style": "long", "locale": locale}]},
        })  # fmt: skip
    assert [problem.code for problem in error.value.problems] == ["spec_date_locale"]


def test_the_date_is_drawn_under_the_headline_one_line_per_format() -> None:
    inset = {"top": 0.1, "bottom": 0.2, "start": 0.1, "end": 0.1}
    spec = read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle", "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "surround", "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
        "headline": {"text": "נועה ועודד", "font": "heebo-bold", "color": "#ffffff",
                     "size": 0.05, "slot": "bottom-band"},
        "date": {"value": "2026-10-12", "afterSunset": True, "font": "heebo", "color": "#ffffff",
                 "size": 0.02, "joiner": None, "slot": "under-headline",
                 "formats": [HEBREW, {"calendar": "gregorian", "pattern": "dd.MM.yyyy"}]},
    })  # fmt: skip
    svg = render_svg(spec, "portrait", 600, 900)
    bodies = re.findall(r'direction="(\w+)"[^>]*>([^<]*)</text>', svg)
    assert bodies == [("rtl", "נועה ועודד"), ("rtl", "ב׳ חשון תשפ״ז"), ("rtl", "12.10.2026")]
    # The headline's area ends at 819.6 (T-13a): both date lines are below it.
    ys = [float(y) for y in re.findall(r'<text x="[\d.]+" y="([\d.]+)"', svg)]
    assert ys[0] < 819.6 < ys[1] < ys[2]
