# Test material (T-10)

Real frames from past events, provided by the owner, for building and testing the frame
spec, the renderer and template import (DESIGN.md sections 4 and 6). They are examples
only: they are not shipped with FrameGen and must not be used as built-in templates.

Each folder is one event, named by its date. File names are Hebrew:

| Name | Meaning |
|---|---|
| `אורך` | portrait |
| `רוחב` | landscape |
| `… גדול` | large (mostly 2:3, 1600×2400 or 2400×1600); without it 3:4 (1200×1600 or 1600×1200) |

`.psd` files are the layered designs; `.png` files are the exported overlays (8-bit RGBA,
the photo window transparent; see the `14.8.26` note for an exception).

## Events

| Folder | Event | Files | Notes |
|---|---|---|---|
| `1.12.24` | Tribute evening (ערב הוקרה) | portrait-large, landscape-large `.psd` | Bottom band, logo, two text lines. A hidden date layer, so no visible date. Landscape-large is 2399×1714, not 3:2. Portrait-large has a stray visible `Lorem Ipsum` placeholder layer under the stamp. |
| `14.8.26` | Bar mitzvah (נעם) | portrait-large `.psd` + `.png`, landscape-large `.png`, `Inventation.heic` | The landscape-large PSD has no `.psd` extension. Decoration copied from the invitation, so this event is the reference for "design from an invitation". Hebrew date only. The PNGs' window is not clean: it holds opaque and half-transparent pixels, so it is a test for window detection. |
| `22.12.25` | Henna (חינה) | portrait, landscape `.png` only | Flat PNG, no layers; text and stamp must be found and removed at import (DESIGN.md 6.3). |
| `23.9.26` | Wedding (עפרי ושלוה) | portrait-large, landscape-large `.psd` + `.png`, `magnet picture example.heic` | Bar style with icons; Gregorian and Hebrew dates. The `.heic` is a photo of a printed magnet. |
| `7.9.26` | Bat mitzvah | four sizes `.psd` + `.png`, `name and date.psb` | Torn-paper band. Name and date are a smart object (`name and date.psb`), not live text. Each PSD also has a hidden smart object with an older name and date, and the flowers smart object is visible only in portrait, so the four sizes do not share one layer structure: an importer must respect visibility. |

## What the layers show

- **Stamp:** every PSD has the photographer's credit as a live text layer,
  `ברקאי צלמים: 050-…` or `ברקאי: 050-…`, set vertically along the right edge, near the
  window. There is no separate stamp file.
- **Headline and dates:** live text layers in most PSDs. Only `23.9.26` has both a
  Hebrew and a Gregorian date; `14.8.26` has a Hebrew date only, and `1.12.24` hides its
  date. In `7.9.26` the name and date are inside a smart object.
- **Decoration:** pixel layers, shapes and smart objects, usually a band at the bottom,
  sometimes a full background around the window (`14.8.26`).

## Fonts

No font files are included. The PSDs name these fonts (Photoshop's internal `AdobeInvisFont`
aside). In `7.9.26` the stamp mixes two fonts in one layer:

| Font in the PSD | Used in | Licence | Built-in stand-in |
|---|---|---|---|
| Amatic SC Bold | `23.9.26` | open (OFL, Google Fonts) | the same font |
| Suez One | `23.9.26` | open (OFL, Google Fonts) | the same font |
| Heebo ExtraBold | `7.9.26`, stamp name only | open (OFL, Google Fonts) | the same font |
| FtJimbory Rounded Bold | `1.12.24` | commercial | a rounded open font, e.g. Varela Round |
| Flamingo FM | `14.8.26` | commercial | a handwritten open font |
| Shluk DL | `7.9.26`, stamp phone number only | commercial | a display open font |
| Myriad Hebrew | `1.12.24`, the `Lorem Ipsum` placeholder | commercial (Adobe) | not needed |

Until the owner adds the commercial ones, the renderer uses the built-in open-licence
fonts (T-13). Invitations rarely name their font, so picking the closest built-in font
from an invitation photo is a separate AI task.
