"""Built-in fonts: open-licence fonts for Hebrew and Latin (DESIGN.md 4.3, D3).

The files are the families' releases from Google Fonts (github.com/google/fonts, ofl/),
under the SIL Open Font License, with each family's licence beside its files. They are
kept unmodified, so they can go into packages as they are: some licences reserve their
font names, so a subset or other changed file would need a new name. `files/SHA256SUMS`
pins them; changing a file changes the pixels, so it is a new renderer version.

A built-in font is one family at one weight, named as the spec names it ("heebo-bold").
Families with a variable file give several weights from that one file.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FILES = Path(__file__).parent / "files"

Script = Literal["hebrew", "latin"]
Style = Literal["sans", "serif", "display", "handwriting", "script"]


@dataclass(frozen=True)
class BuiltInFont:
    family: str
    """The family's own name, as the package's readme lists it."""
    file: str
    """Relative to FILES."""
    weight: int
    """CSS weight: this font's place in its family, and the axis value of a variable file."""
    variable: bool
    scripts: tuple[Script, ...]
    style: Style

    @property
    def path(self) -> Path:
        return FILES / self.file


def _family(
    family: str,
    style: Style,
    scripts: tuple[Script, ...],
    files: dict[str, tuple[str, int]],
) -> dict[str, BuiltInFont]:
    return {
        name: BuiltInFont(family, file, weight, "[" in file, scripts, style)
        for name, (file, weight) in files.items()
    }


HEBREW_LATIN: tuple[Script, ...] = ("hebrew", "latin")

_HEEBO = "heebo/Heebo[wght].ttf"
_FRANK = "frankruhllibre/FrankRuhlLibre[wght].ttf"
_RUBIK = "rubik/Rubik[wght].ttf"
_PLAYPEN = "playpensanshebrew/PlaypenSansHebrew[wght].ttf"
_PLAYFAIR = "playfairdisplay/PlayfairDisplay[wght].ttf"

BUILT_IN: dict[str, BuiltInFont] = {
    **_family("Heebo", "sans", HEBREW_LATIN, {
        "heebo-light": (_HEEBO, 300),
        "heebo": (_HEEBO, 400),
        "heebo-medium": (_HEEBO, 500),
        "heebo-bold": (_HEEBO, 700),
        "heebo-extrabold": (_HEEBO, 800),
        "heebo-black": (_HEEBO, 900),
    }),
    **_family("Rubik", "sans", HEBREW_LATIN, {
        "rubik": (_RUBIK, 400),
        "rubik-bold": (_RUBIK, 700),
    }),
    **_family("Varela Round", "sans", HEBREW_LATIN, {
        "varela-round": ("varelaround/VarelaRound-Regular.ttf", 400),
    }),
    **_family("Secular One", "sans", HEBREW_LATIN, {
        "secular-one": ("secularone/SecularOne-Regular.ttf", 400),
    }),
    **_family("Frank Ruhl Libre", "serif", HEBREW_LATIN, {
        "frank-ruhl-libre": (_FRANK, 400),
        "frank-ruhl-libre-bold": (_FRANK, 700),
    }),
    **_family("David Libre", "serif", HEBREW_LATIN, {
        "david-libre": ("davidlibre/DavidLibre-Regular.ttf", 400),
        "david-libre-bold": ("davidlibre/DavidLibre-Bold.ttf", 700),
    }),
    **_family("Bellefair", "serif", HEBREW_LATIN, {
        "bellefair": ("bellefair/Bellefair-Regular.ttf", 400),
    }),
    **_family("Suez One", "display", HEBREW_LATIN, {
        "suez-one": ("suezone/SuezOne-Regular.ttf", 400),
    }),
    **_family("Karantina", "display", HEBREW_LATIN, {
        "karantina": ("karantina/Karantina-Regular.ttf", 400),
        "karantina-bold": ("karantina/Karantina-Bold.ttf", 700),
    }),
    **_family("Amatic SC", "handwriting", HEBREW_LATIN, {
        "amatic-sc": ("amaticsc/AmaticSC-Regular.ttf", 400),
        "amatic-sc-bold": ("amaticsc/AmaticSC-Bold.ttf", 700),
    }),
    **_family("Playpen Sans Hebrew", "handwriting", HEBREW_LATIN, {
        "playpen-sans-hebrew": (_PLAYPEN, 400),
        "playpen-sans-hebrew-bold": (_PLAYPEN, 700),
    }),
    **_family("Playfair Display", "serif", ("latin",), {
        "playfair-display": (_PLAYFAIR, 400),
        "playfair-display-bold": (_PLAYFAIR, 700),
    }),
    **_family("Great Vibes", "script", ("latin",), {
        "great-vibes": ("greatvibes/GreatVibes-Regular.ttf", 400),
    }),
}  # fmt: skip
