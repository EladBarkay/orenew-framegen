"""Headline, date, stamp, slots and the rules across the whole spec (T-11b)."""

import datetime
from typing import Any

import pytest

from framegen.spec import SpecInvalid, read_spec
from framegen.spec.text import SlotPerOrientation, TextStamp, slot_in

PIECE = "pc_" + "a2" * 13
ASSET = "ast_" + "b3" * 13
BRAND_KIT_STAMP = {"source": "brand-kit", "slot": "end-edge", "size": 0.16}


def frame(decoration: dict[str, Any], **components: Any) -> dict[str, Any]:
    edge = {"inset": {"top": 0, "bottom": 0, "start": 0, "end": 0}}
    return {
        "specVersion": 1,
        "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle", "portrait": edge, "landscape": edge},
        "decoration": decoration,
        **components,
    }


def band(edge: str = "bottom", thickness: float = 0.1) -> dict[str, Any]:
    return {
        "kind": "vector",
        "shape": "band",
        "edge": edge,
        "thickness": thickness,
        "color": "#ffffff",
    }


def piece(anchor: str) -> dict[str, Any]:
    return {"kind": "piece", "piece": PIECE, "anchor": anchor, "size": 0.1}


def headline(text: str = "עפרי ושלוה", slot: Any = "bottom-band") -> dict[str, Any]:
    return {"text": text, "font": "amatic-sc-bold", "color": "#000000", "size": 0.06, "slot": slot}


def date(**changes: Any) -> dict[str, Any]:
    return {
        "value": "2026-09-23", "font": "amatic-sc-bold", "color": "#000000", "size": 0.025,
        "formats": [{"calendar": "hebrew", "style": "day-month-year"},
                    {"calendar": "gregorian", "pattern": "d.M.yyyy"}],
        "slot": "under-headline", **changes,
    }  # fmt: skip


def codes(data: dict[str, Any]) -> set[str]:
    with pytest.raises(SpecInvalid) as caught:
        read_spec(data)
    return {problem.code for problem in caught.value.problems}


# Every event in attachments/ can be written as a spec (pieces stand for the artwork).
ATTACHMENTS = {
    "23.9.26 wedding, bar with icons": frame(
        {"archetype": "bar", "layers": [
            {"kind": "vector", "shape": "bar", "edge": "bottom", "distance": 0.09,
             "thickness": 0.074, "color": "#ffffff"},
            piece("bottom-start"), piece("bottom-end")]},
        headline=headline(), date=date(), stamp=BRAND_KIT_STAMP,
    ),
    "7.9.26 bat mitzvah, torn-paper band": frame(
        {"archetype": "template", "layers": [piece("bottom")]},
        headline=headline("אורי | בת מצווה", "bottom-band"),
        date=date(value="2026-09-07", joiner=" | ",
                  formats=[{"calendar": "hebrew", "style": "month-year"},
                           {"calendar": "gregorian", "pattern": "d.M.yy"}]),
        stamp={"source": "text", "text": "ברקאי צלמים: 050-2433950", "font": "heebo",
               "color": "#000000", "size": 0.016, "slot": "end-edge"},
    ),
    "1.12.24 tribute evening, band and logo": frame(
        {"archetype": "bar", "layers": [band(thickness=0.095), piece("bottom-start")]},
        headline=headline("ערב הוקרה \"חרבות ברזל\"\nרבנות עוצבת הבשן"),
        stamp=BRAND_KIT_STAMP,
    ),
    "14.8.26 bar mitzvah, surround from the invitation": frame(
        {"archetype": "surround", "layers": [piece("center")]},
        headline=headline("נעם חוגג בר מצווה"),
        date=date(value="2026-08-14", override="שבת פרשת שופטים התשפ״ו"),
        stamp={"source": "image", "image": ASSET, "slot": "end-edge"},
    ),
    "22.12.25 henna, corner hamsas": frame(
        {"archetype": "corners", "layers": [piece("bottom-start"), piece("bottom-end")]},
        headline=headline("החינה של ני ושמעון"),
        date=date(value="2025-12-22", formats=[{"calendar": "gregorian", "pattern": "dd.MM.yy"}]),
        stamp=BRAND_KIT_STAMP,
    ),
}  # fmt: skip


@pytest.mark.parametrize("data", ATTACHMENTS.values(), ids=ATTACHMENTS.keys())
def test_each_attachment_can_be_expressed(data: dict[str, Any]) -> None:
    assert read_spec(data)


def test_components_are_optional() -> None:
    spec = read_spec(frame({"archetype": "bar", "layers": [band()]}))
    assert (spec.headline, spec.date, spec.stamp) == (None, None, None)


def test_date_reads_its_formats() -> None:
    spec = read_spec(ATTACHMENTS["23.9.26 wedding, bar with icons"])
    assert spec.date is not None
    assert spec.date.value == datetime.date(2026, 9, 23)
    assert [f.calendar for f in spec.date.formats] == ["hebrew", "gregorian"]
    assert spec.date.joiner == " · " and not spec.date.after_sunset


def test_a_slot_name_means_both_orientations() -> None:
    spec = read_spec(
        frame({"archetype": "bar", "layers": [band()]},
              headline=headline(slot={"portrait": "bottom-band", "landscape": "top-band"}),
              stamp=BRAND_KIT_STAMP)
    )  # fmt: skip
    assert spec.headline is not None and spec.stamp is not None
    assert isinstance(spec.headline.slot, SlotPerOrientation)
    assert slot_in(spec.headline.slot, "landscape") == "top-band"
    assert slot_in(spec.stamp.slot, "portrait") == slot_in(spec.stamp.slot, "landscape")


def test_stamps_by_source() -> None:
    spec = read_spec(ATTACHMENTS["7.9.26 bat mitzvah, torn-paper band"])
    assert isinstance(spec.stamp, TextStamp) and spec.stamp.size == 0.016


BASE = ATTACHMENTS["23.9.26 wedding, bar with icons"]


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"headline": headline("   ")}, "spec_text_empty"),
        ({"headline": headline("a\x00b")}, "spec_text_control"),
        ({"headline": headline("א" * 201)}, "too_long"),
        ({"headline": {**headline(), "font": "../fonts/x.ttf"}}, "string_pattern_mismatch"),
        ({"headline": {**headline(), "size": 0.3}}, "less_than_equal"),
        ({"headline": headline(slot="middle")}, "literal_error"),
        ({"date": date(value="23.9.2026")}, "date_type"),
        ({"date": date(value="2026-02-30")}, "date_from_datetime_parsing"),
        ({"date": date(value=20260923)}, "date_type"),
        ({"date": date(formats=[])}, "too_short"),
        ({"date": date(formats=[{"calendar": "julian"}])}, "union_tag_invalid"),
        ({"date": date(formats=[{"calendar": "gregorian"}])}, "spec_date_pattern_or_style"),
        ({"date": date(formats=[{"calendar": "gregorian", "pattern": "dd.MM.yyyy",
                                 "style": "long"}])}, "spec_date_pattern_or_style"),
        ({"date": date(formats=[{"calendar": "gregorian", "pattern": "hh:mm"}])},
         "string_pattern_mismatch"),
        ({"date": date(formats=[{"calendar": "hebrew", "numerals": "roman"}])}, "literal_error"),
        ({"stamp": {"source": "drawing", "slot": "end-edge"}}, "union_tag_invalid"),
        ({"stamp": {"source": "image", "image": "logo.png", "slot": "end-edge"}},
         "string_pattern_mismatch"),
        ({"stamp": {**BRAND_KIT_STAMP, "size": 0.6}}, "less_than_equal"),
        ({"stamp": {**BRAND_KIT_STAMP, "slot": "bottom-band"}}, "spec_slot_taken"),
        ({"headline": None}, "spec_slot_under_headline"),
        ({"headline": headline(slot="under-headline")}, "spec_slot_under_headline"),
    ],
)  # fmt: skip
def test_invalid_components_are_rejected(changes: dict[str, Any], code: str) -> None:
    assert code in codes({**BASE, **changes})


def test_slots_are_checked_per_orientation() -> None:
    spec = frame({"archetype": "bar", "layers": [band()]},
                 headline=headline(slot={"portrait": "bottom-band", "landscape": "top-band"}),
                 stamp={**BRAND_KIT_STAMP, "slot": {"portrait": "end-edge",
                                                     "landscape": "top-band"}})  # fmt: skip
    assert codes(spec) == {"spec_slot_taken"}


@pytest.mark.parametrize(
    ("decoration", "ok"),
    [
        ({"archetype": "stroke", "layers": [band()]}, False),
        ({"archetype": "stroke", "layers": [
            {"kind": "vector", "shape": "stroke", "width": 0.01, "color": "#000000"}]}, True),
        ({"archetype": "bar", "layers": [piece("bottom")]}, False),
        ({"archetype": "corners", "layers": [piece("bottom"), piece("top")]}, False),
        ({"archetype": "corners", "layers": [piece("top-end")]}, True),
        ({"archetype": "surround", "layers": []}, False),
        ({"archetype": "scatter", "layers": [piece("top")]}, False),
        ({"archetype": "scatter", "layers": [piece("top"), piece("center")]}, True),
        ({"archetype": "template", "layers": [band()]}, False),
    ],
)  # fmt: skip
def test_each_archetype_needs_its_layers(decoration: dict[str, Any], ok: bool) -> None:
    if ok:
        assert read_spec(frame(decoration))
    else:
        assert codes(frame(decoration)) == {"spec_archetype_incomplete"}
