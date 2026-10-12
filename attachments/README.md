# Test material (T-10)

Real frames from past events, provided by the owner, for building and testing the frame
spec, the renderer and template import (DESIGN.md sections 4 and 6). They are examples
only: they are not shipped with FrameGen and must not be used as built-in templates.

Each folder is one event, named by its date. File names are Hebrew:

| Name | Meaning |
|---|---|
| `אורך` | portrait |
| `רוחב` | landscape |
| `… גדול` | large (2:3, 1600×2400 or 2400×1600); without it 3:4 (1200×1600 or 1600×1200) |

`.psd` files are the layered designs; `.png` files are the exported overlays (8-bit RGBA,
the photo window fully transparent).

## Events

| Folder | Event | Files | Notes |
|---|---|---|---|
| `1.12.24` | Tribute evening (ערב הוקרה) | portrait-large, landscape-large `.psd` | Bottom band, logo, two text lines. A hidden date layer. |
| `14.8.26` | Bar mitzvah (נעם) | portrait-large `.psd` + `.png`, landscape-large `.png`, `Inventation.heic` | The landscape-large PSD has no `.psd` extension. Decoration copied from the invitation, so this event is the reference for "design from an invitation". |
| `22.12.25` | Henna (חינה) | portrait, landscape `.png` only | Flat PNG; text must be found and removed at import (DESIGN.md 6.3). |
| `23.9.26` | Wedding (עפרי ושלוה) | portrait-large, landscape-large `.psd` + `.png`, `magnet picture example.heic` | Bar style with icons; Gregorian and Hebrew dates. The `.heic` is a photo of a printed magnet. |
| `7.9.26` | Bat mitzvah | four sizes `.psd` + `.png`, `name and date.psb` | Torn-paper band. Name and date are a smart object (`name and date.psb`), not live text. |

## What the layers show

- **Stamp:** every design has the photographer's credit as a live text layer,
  `ברקאי צלמים: 050-…` or `ברקאי: 050-…`, set vertically along the right edge, near the
  window. There is no separate stamp file.
- **Headline and dates:** live text layers in most PSDs (names, event, Hebrew and
  Gregorian date); in `7.9.26` they are inside a smart object.
- **Decoration:** pixel layers, shapes and smart objects, usually a band at the bottom,
  sometimes a full background around the window (`14.8.26`).

## Fonts

No font files are included. The PSDs name these fonts:

| Font in the PSD | Used in | Licence | Built-in stand-in |
|---|---|---|---|
| Amatic SC Bold | `23.9.26` | open (OFL, Google Fonts) | the same font |
| Suez One | `23.9.26` | open (OFL, Google Fonts) | the same font |
| Heebo ExtraBold | `7.9.26` | open (OFL, Google Fonts) | the same font |
| FtJimbory Rounded Bold | `1.12.24` | commercial | a rounded open font, e.g. Varela Round |
| Flamingo FM | `14.8.26` | commercial | a handwritten open font |
| Shluk DL | `7.9.26` | commercial | a display open font |

Until the owner adds the commercial ones, the renderer uses the built-in open-licence
fonts (T-13). Invitations rarely name their font, so picking the closest built-in font
from an invitation photo is a separate AI task.
