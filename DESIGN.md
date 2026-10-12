# Orenew FrameGen — Design

> **Purpose of this file:** the design of FrameGen, written to be built from. It records
> what the product does, how it is built, and why. Requirement IDs are stable; refer to
> them by ID. Decisions are recorded in section 13, open questions in section 14.
>
> Tasks, questions and decisions are tracked in Notion, in the "Orenew FrameGen" page:
> "FrameGen tasks" (task IDs T-xx refer to it), "FrameGen questions and decisions", and
> "FrameGen reference".

---

## 1. Product

FrameGen makes decorative photo frames for event photographers who print on the spot
(see Orenew, `github.com/EladBarkay/orenew`). For each event the photographer needs a
frame in a landscape and a portrait version, at the exact pixel sizes their printer
layouts need, with most of the frame see-through so the photo shows.

FrameGen produces those frames from whatever the photographer has: a frame they already
use with new names and a new date, an invitation whose style the frame should match, a
photo of a fridge magnet, or just a few words. The photographer refines the result in
a conversation until it is right, then receives the full package (PNGs and/or editable
PSDs, both orientations, every size they asked for).

### Product promise

1. **The window is always truly transparent.** Frames work in Orenew (FR-7) and in any
   other tool that finds the window from the see-through area.
2. **Landscape and portrait are the same design**, not two similar-looking guesses.
3. **Names and dates are always spelled right**, in any language, including Hebrew.
4. **Cheap by default.** AI is used only where it adds something, and the expensive
   steps happen only after the photographer approves a draft.
5. **API first.** Everything the web app does, another program can do through the
   public API. A future version of Orenew uses the same API.

### Glossary

Shared terms (frame, window, layout, position, sheet) mean exactly what they mean in
Orenew's `PRODUCT_SPEC.md`.

| Term | Meaning |
|---|---|
| **Frame spec** | The structured description of one frame design: window, decoration, headline, date, stamp, and how each is placed in each orientation. The source of truth; every image is drawn from it. |
| **Component** | One of the four parts of a frame: decoration, headline, date, stamp (section 4). |
| **Piece** | One raster image used by a decoration (a corner ornament, a floral cluster, a texture). Pieces are AI-generated, uploaded, or taken from a template. |
| **Draft** | A low-resolution portrait render of a frame spec, for review. |
| **Revision** | One turn of the conversation that changes the spec and produces a new draft. |
| **Package** | The final files for an approved design, per the output preset. |
| **Output preset** | The list of files the photographer wants: sizes, orientations, PNG and/or PSD. |
| **Template** | A frame the photographer already uses, imported from PSD or PNG and mapped to the four components, so it can be reused with new text. |
| **Brand kit** | The photographer's stamp, fonts and favourite colors. |
| **Style profile** | What FrameGen has learned about a photographer's taste, from their library and their revisions. Viewable and editable. |
| **Workspace** | One photographer or one studio. Owns credentials, brand kit, library, style profile and projects. |
| **Project** | One event's frame work: the brief, references, conversation, versions and packages. |
| **Provider** | An AI service (OpenAI, Google, Anthropic, Replicate, fal, Stability, …) reached with the workspace's own API key. |

---

## 2. Users

| Persona | What they need most |
|---|---|
| **Solo event photographer** (primary) | A frame for tomorrow's event in minutes, usually a reused preset with new names and date. |
| **Studio** | Several members sharing one library, brand kit and set of provider keys. |
| **Integrator** (future: Orenew, other apps) | A complete, documented, stable API: create a project, get drafts, revise, get the package. |

Users bring their own provider API keys and pay providers directly. A hosted,
pay-per-use version may follow; the design keeps that possible (section 10.4) without
building it now.

---

## 3. Core workflows

### 3.1 Reuse a template (the most common case)

1. Pick a template from the library.
2. Type the headline and the date. The stamp comes from the brand kit.
3. See the preview, then download the package.

**No AI call is needed** when the template is a layered PSD or a PNG that was mapped at
import time (6.3). This is fast, free and exactly reproducible.

### 3.2 New design from a brief

1. **Brief.** Headline, date, free-text description, and any references (invitation,
   magnet photo, existing frames, nothing at all). Output preset chosen (remembered).
2. **Draft.** FrameGen produces **one low-resolution portrait draft** (around 768 px on
   the long edge). A cost estimate is shown before the first AI call.
3. **Revise.** The photographer says what to change ("smaller flowers", "names in
   gold", "use the bar style instead"). Each revision changes only what it must and
   produces a new draft. Every version is kept and can be returned to.
4. **Approve.** The approved version is shown in landscape as well, still low
   resolution, so the photographer confirms both orientations before paying for
   full resolution.
5. **Package.** A cost estimate is shown; on confirmation FrameGen produces every file
   in the output preset.

### 3.3 Import a library

The photographer uploads existing frames (PSD or PNG). Each is stored, its window
found, its components mapped, and its style analysed. They become templates (3.1),
references for new designs, and input to the style profile (7.5). Uploading is opt-in;
nothing is kept unless the photographer chooses to import.

---

## 4. The frame model

Almost every event frame is made of the same four components. FrameGen models frames
this way, so the AI never draws the whole frame as one picture.

| Component | What it is | Typical forms |
|---|---|---|
| **Decoration** | The artwork around or over the photo. | A stroke around the photo; a single bar at the bottom; corner ornaments; a full painted surround; scattered elements. |
| **Headline** | The event's title. | "Ofri's Bar Mitzva", "Noa & Oded's Wedding", in any language. |
| **Date** | The event's date, in one or more calendars and formats. | `12.10.2026`; `October 12, 2026`; `א׳ בחשוון תשפ״ז`; Gregorian and Hebrew together. |
| **Stamp** | The photographer's mark. | A text signature (name + phone), or an image (logo PNG/JPEG/SVG). |

Plus the **window**: one per frame (always exactly one photo), with a shape (rectangle,
rounded rectangle, arch, oval, or a custom mask) and its place within the frame.

### 4.1 Frame spec

The frame spec is JSON, validated by a published schema (`backend/framegen/spec`, exported as JSON Schema). Shortened:

```jsonc
{
  "specVersion": 1,
  "aspect": { "portrait": "2:3", "landscape": "3:2" },   // from the output preset
  "window": { "shape": "rounded", "radius": 0.02,
              "portrait":  { "inset": { "top": 0.06, "start": 0.06, "end": 0.06, "bottom": 0.22 } },
              "landscape": { "inset": { "top": 0.06, "start": 0.05, "end": 0.05, "bottom": 0.20 } } },
  "decoration": {
    "archetype": "corners",                              // stroke | bar | corners | surround | scatter | template
    "layers": [
      { "kind": "vector", "shape": "stroke", "width": 0.012, "color": "#c9a24a" },
      { "kind": "piece",  "piece": "pc_7f…", "anchor": "top-start", "size": 0.32, "mirror": "inline" },
      { "kind": "piece",  "piece": "pc_7f…", "anchor": "bottom-end", "size": 0.32, "rotate": 180 }
    ]
  },
  "headline": { "text": "נועה ועודד", "font": "font_…", "color": "#3a2c12", "size": 0.07,
                "slot": { "portrait": "bottom-band", "landscape": "bottom-band" } },
  "date": { "value": "2026-10-12", "afterSunset": true,
            "font": "font_…", "color": "#3a2c12", "size": 0.03,
            "formats": [ { "calendar": "hebrew", "style": "day-month-year", "numerals": "hebrew" },
                         { "calendar": "gregorian", "pattern": "dd.MM.yyyy" } ],
            "joiner": " · ", "slot": "under-headline" },
  "stamp": { "source": "brand-kit", "slot": "end-edge", "size": 0.08 }
}
```

Rules:

- **Geometry is relative** (fractions of the frame), so one spec draws at any size.
- **Each component has a slot per orientation.** Slots are named regions ("bottom-band",
  "top-band", "bottom-end corner") with rules for re-flow, so landscape is derived from
  portrait instead of designed again.
- **Vector where possible.** Strokes, bars, solid bands and simple shapes are drawn
  by the renderer: crisp at any size, editable, and free.
- **Pieces for artwork.** Ornaments and painted elements are raster pieces with their
  own transparency, placed by anchor, size, rotation and mirroring.
- **Border pieces are nine-slice.** A border that runs around the photo is generated
  as corners plus seamlessly tileable edges, so it fits any aspect ratio without
  stretching.
- **Text is never in a piece.** Headline, date and text stamps are drawn by the
  renderer with real fonts (4.3).

### 4.2 Keeping landscape and portrait the same design

Both orientations are drawn from the same spec and the same pieces; only the slot
placement changes. The approved draft is shown in both orientations before packaging
(3.2 step 4).

The one exception is a **surround** decoration that cannot be split into placeable
pieces (for example one continuous watercolour scene). Then the second orientation is
generated by image editing from the first (outpainting / recomposition), with the
first as reference. FrameGen labels this result "AI-matched, check it" and shows both
side by side.

### 4.3 Text, languages and dates

- Text is shaped and laid out by a real text engine (section 9: Chromium), so every
  script, right-to-left text, mixed Hebrew/English and ligatures work correctly.
- Fonts: a curated set of open-licence fonts per script (Hebrew and Latin first), plus
  the workspace's uploaded fonts, which are used only inside that workspace.
- **Dates:** stored as one calendar date plus `afterSunset`. Each format renders it in
  a calendar:
  - Gregorian through `Intl.DateTimeFormat` patterns or styles, in any locale.
  - Hebrew through `pyluach`, with Hebrew-letter numerals (gematria, `תשפ״ז`)
    or digits. `afterSunset` moves the Hebrew date to the next day, because evening
    events (most weddings) fall on the following Hebrew date.
  - Several formats can be shown together with a joiner, or stacked.
- The photographer can always override the rendered date text by hand.

### 4.4 Window and transparency rules (compatibility with Orenew)

- The window area is **fully transparent** (alpha 0), always: the renderer cuts it
  from the mask after every layer is drawn. Nothing the AI produces can fill it.
- Decoration may **overlap the window** only where the spec says so (`overlapsWindow` on
  a layer): a flower over the corner of the photo, or a caption bar across it as in many
  real frames. The rest of the window stays clear, and the output check (T-18)
  looks at the window minus what those layers cover.
- Everything outside the window is whatever the design is: opaque, partly or fully
  transparent.
- Output is checked after rendering: window alpha exactly 0, the size in pixels exactly
  as requested, no stray semi-transparent pixels in the window.

---

## 5. Making transparency work

Most image models cannot output transparency, and the ones that can do it unevenly.
FrameGen does not depend on it:

1. **The window is never generated.** It is cut by the renderer (4.4).
2. **Vector layers are transparent by construction.**
3. **Pieces** (the only AI raster output) get their alpha by the best method the chosen
   provider supports, in this order:

| Method | How | When |
|---|---|---|
| **Native alpha** | Ask the provider for a transparent background. | The provider supports it (for example OpenAI's image models). Validated: if the result has no real alpha, fall through to the next method. |
| **Difference matting** | Generate the piece on pure white, then edit the same image to put it on pure black. Alpha and true colour are computed from the two: `α = 1 − (white − black)`, colour = `black / α`. | The provider supports image editing that keeps the subject in place. Keeps soft edges, glow and translucency (glass, glitter, petals). |
| **Matting model** | Generate on a plain contrasting background, then separate it with a segmentation/matting model (BiRefNet, RMBG class). | Generate-only providers. Good for solid objects; weaker on translucency. |
| **Chroma key** | Generate on a flat key colour and key it out, with despill. | Last resort. |

After any method: trim to the content, de-fringe edges, and check that the piece has
real transparency where expected. A piece that fails is retried once with the next
method, then reported.

Matting and upscaling run in FrameGen's own workers when possible (open models via
ONNX), so they do not need a provider key and cost nothing per call.

---

## 6. Inputs and references

### 6.1 Reference types

| Input | What FrameGen does with it |
|---|---|
| **Verbal brief only** | The planner works from the text, the style profile and the brand kit. |
| **Invitation** (photo, scan, PDF, image) | Vision analysis extracts palette, typography class, motifs, ornament style and layout feel. Optionally, distinctive motifs are recreated as pieces in the same style. |
| **Object photo** (a magnet, a cake, a venue sign) | Vision analysis extracts style; the photo is used as an image reference when generating pieces. Background and perspective are ignored. |
| **Existing frame** (from the library or uploaded once) | Used as a strong style and layout reference, or as a template (6.3). |

Each reference is analysed **once** and its result (a *style brief*: JSON plus a short
text summary) is stored with it, so revisions do not pay for analysis again.

### 6.2 Uploads

Files go straight to object storage through pre-signed URLs; the API never streams
large files. Accepted: PNG, JPEG, WebP, HEIC (phone photos), TIFF, PSD, PDF (first
page), SVG (stamps), and font files (TTF, OTF, WOFF2).

The client declares each file's type, size and SHA-256 first. The upload link is signed
with that checksum, so the storage refuses any other content. On completion FrameGen
reads only the file's first bytes: it checks that they really are the declared type, and
deletes the file otherwise, so nothing can be stored as an image and served back as a
page. It also reads the pixel size. Download links always download, never display, and
expire after 15 minutes. Browsers reach the storage through the site itself (Caddy
forwards the bucket's path), so no second domain or certificate is needed.

### 6.3 Templates (importing existing frames)

| Source | Import |
|---|---|
| **Layered PSD** | Layers are read (`psd-tools`). Text layers become headline / date / stamp candidates by layer name, content (does it parse as a date? a phone number?) and position; the rest become decoration pieces in their original positions. The photographer confirms the mapping once. **Reuse costs no AI.** |
| **PNG with transparency** | Window found from the see-through area (same rule as Orenew FR-7). A vision model finds the headline, date and stamp regions. Their text is removed with one image-edit (inpainting) call at import, and the clean decoration is stored. After that, **reuse costs no AI.** |
| **One orientation only** | The other orientation is derived by re-flow if the decoration splits into pieces, otherwise by the AI-matched path (4.2), once, at import. |

The original upload is always kept unchanged next to the derived template.

---

## 7. AI pipeline

### 7.1 Roles

| Role | Does | Model type |
|---|---|---|
| **Analyst** | Turns references and library frames into style briefs. | Vision LLM |
| **Planner** | Turns brief + style briefs + style profile + brand kit into a frame spec, plus a prompt for each piece it needs. | LLM with structured output (the spec schema) |
| **Reviser** | Turns a revision message into a patch to the spec (JSON Patch) plus the list of pieces to regenerate, if any. | LLM with structured output |
| **Painter** | Generates and edits pieces. | Image model |
| **Upscaler** | Brings approved pieces to final resolution, alpha included. | Upscaling model (local or provider) |

### 7.2 Cost discipline

- **Draft:** one portrait, low resolution, cheapest adequate quality tier. Vector-only
  designs (stroke, bar) need no image call at all.
- **Revisions:** a patch, not a redo. "Make the names gold" changes one field and costs
  one small LLM call; "different flowers" regenerates only the flower piece.
- **Package:** pieces are upscaled or regenerated once at the largest size any output
  needs; every other size, both orientations and the PSDs are drawn by the renderer.
  **An editable PSD costs no more AI than a PNG**: it is the same layers, saved
  separately.
- Before each paid step the API returns an **estimate** (calls by provider and model,
  approximate cost). A workspace can set a per-project spending cap.
- Every provider call is recorded (provider, model, tokens/images, estimated cost,
  duration, outcome) for the usage view, and later for billing (10.4).

### 7.3 Providers

One interface per capability; each adapter declares what it can do:

```ts
interface ImageProvider {
  id: string
  capabilities: {
    generate: boolean, edit: boolean, mask: boolean, nativeAlpha: boolean,
    referenceImages: number, maxSize: [number, number], sizes?: [number, number][]
  }
  generate(req: GenerateRequest): Promise<ImageResult>
  edit?(req: EditRequest): Promise<ImageResult>
  estimate(req: GenerateRequest | EditRequest): CostEstimate
}
// Likewise: TextProvider (chat, vision, structured output), UpscaleProvider, MattingProvider.
```

First adapters: OpenAI (text, vision, image with native alpha), Google Gemini (text,
vision, image edit), Anthropic (text, vision), Replicate and fal (Flux family image
models, upscalers, matting). Adding a provider is one adapter file plus its tests.

**Routing:** each pipeline step picks a provider by capability and the workspace's
preferences (a default per role, overridable per project). If a step needs a
capability no connected provider has, the API says which one is missing instead of
failing midway.

### 7.4 Conversation

A project holds an ordered list of messages (user and assistant) and a tree of
versions. Each revision creates a version with a parent, so the photographer can go
back to any earlier draft and continue from there. The reviser sees the current spec,
the last few messages and the current draft image, not the whole history, which keeps
each turn cheap. Direct edits made in the UI (moving the headline, changing a colour)
are also spec patches and create versions the same way.

### 7.5 Style profile and preferences

Remembered per workspace, between sessions:

- **Explicit preferences:** default output preset, fonts, date formats and calendars,
  stamp and its placement, preferred providers per role, spending cap.
- **Learned style:** built from imported library frames (their style briefs) and from
  revisions (for example "asks for smaller ornaments 4 times out of 5", "always moves
  the date under the headline"). Stored as structured fields plus a short summary that
  the planner reads.
- **Library retrieval:** style briefs are embedded (pgvector) so the planner can pull
  the most similar library frames as references for a new brief.

The photographer can see, edit and clear the learned profile. It is a suggestion to the
planner, never a hidden rule.

---

## 8. Outputs

### 8.1 Output presets

An output preset is a list of outputs; each output is a pixel size, an orientation and
a format:

```jsonc
{ "name": "Wedding standard",
  "outputs": [
    { "size": [1800, 1200], "orientation": "landscape", "format": "png" },
    { "size": [1200, 1800], "orientation": "portrait",  "format": "png" },
    { "size": [1800, 1200], "orientation": "landscape", "format": "psd" },
    { "size": [1200, 1800], "orientation": "portrait",  "format": "psd" } ] }
```

Every output in one package must share the spec's aspect ratios. Requesting two aspect
ratios (two different printer layouts) creates two specs from the approved one: the
slots re-flow, and the photographer reviews the second before packaging.

**Ready-made sizes** follow Orenew's ready-made layouts (Orenew CA-4, CA-13), at 300 dpi:

| Paper | Per sheet | Landscape | Portrait |
|---|---|---|---|
| 10 × 15 cm (4 × 6 in) | 1 | 1800 × 1200 | 1200 × 1800 |
| 10 × 15 cm (4 × 6 in) | 2 | 1200 × 900 | 900 × 1200 |
| 13 × 18 cm (5 × 7 in) | 1 | 2100 × 1500 | 1500 × 2100 |
| 13 × 18 cm (5 × 7 in) | 2 | 1500 × 1050 | 1050 × 1500 |
| 15 × 20 cm (6 × 8 in) | 1 | 2400 × 1800 | 1800 × 2400 |
| 15 × 20 cm (6 × 8 in) | 2 | 1800 × 1200 | 1200 × 1800 |
| 15 × 20 cm (6 × 8 in) | 4 | 1200 × 900 | 900 × 1200 |

Custom sizes are entered in pixels, or as paper, photos per sheet and dpi, which
FrameGen converts the same way Orenew's designer brief does.

### 8.2 PNG

8-bit RGBA, sRGB, exact requested size, with the 300 dpi value written into the file.

### 8.3 Editable PSD

Written in two steps: `psd-tools` builds the file with groups and pixel layers, and a
small `psd-writer` service (`ag-psd`) adds the text layers, which `psd-tools` cannot
create (D8). One layer per component, named and grouped:

```
Frame — Noa & Oded — portrait 1200×1800
├── Stamp          (text layer, or image layer for logo stamps)
├── Date           (text layer)
├── Headline       (text layer)
├── Decoration     (group: one layer per vector shape and per piece, in order)
└── Window guide   (hidden; shows the window shape)
```

Text layers carry real text, font, size, colour and alignment, so they can be edited in
Photoshop; each also carries a rendered preview so the file looks right in tools that
cannot render text layers. The font files used are included in the package (8.4,
D3), so the text stays editable on any machine.

### 8.4 Package

A ZIP with every output, a `fonts/` folder with the font files the design uses, a
`frame.json` (the spec, so the design can be re-opened in
FrameGen or rendered by an integrator), a small preview image, and a readme listing
fonts used. Packages are kept per project and can be downloaded again.

---

## 9. Architecture

### 9.1 Overview

```
 Web app (SvelteKit, thin)        Integrators (future Orenew, others)
           │  HTTPS, public API only  │
           ▼                          ▼
 ┌────────────────────────────────────────────┐
 │ API (FastAPI, OpenAPI 3.1, /v1)            │── Postgres (+pgvector)
 │ auth · validation · resources · estimates  │── Object storage (S3-compatible)
 └───────────────┬────────────────────────────┘
                 │ jobs (Procrastinate, in Postgres)
                 ▼
 ┌────────────────────────────────────────────┐
 │ Workers                                    │── Provider adapters → AI providers
 │ analyse · plan · paint · matte · upscale   │   (workspace's own keys)
 │ render (Chromium) · PSD · package          │
 └────────────────────────────────────────────┘
```

- **The web app does no heavy lifting.** It uploads, calls the API, shows images the
  API produced, and edits the spec through the API. It uses only the public API, so
  nothing the web app can do is out of reach of an integrator.
- **Everything slow is a job.** Analysis, generation, rendering and packaging run in
  workers. The API answers immediately with a job; progress arrives by server-sent
  events or webhooks.

### 9.2 Stack

The backend is **Python** (D8). The web app stays TypeScript; it is thin and talks
only to the API.

| Part | Choice | Why |
|---|---|---|
| Backend language | Python 3.12 | The owner's language; the best ecosystem for image work, local models and AI provider SDKs. |
| API | FastAPI + Pydantic v2 → OpenAPI 3.1 | Pydantic models are the contract; docs, the JSON Schema of the frame spec and the TypeScript client are generated from them. |
| Database | PostgreSQL + pgvector, via SQLAlchemy 2 + Alembic | One store for data, jobs and embeddings; Alembic for schema changes. |
| Jobs | Procrastinate | Queue in Postgres; no extra service to run. Workers are plain Python processes. |
| Files | S3-compatible storage (RustFS, in the same Docker Compose setup, D9), via `boto3` with path-style addressing | Pre-signed uploads/downloads. |
| Renderer | Headless Chromium (Playwright for Python) drawing the spec as SVG/HTML, transparent background | A complete, correct text engine (every script, right-to-left, font fallback) and exact vector drawing, for free. |
| Pixel work | Pillow + NumPy | Difference matting, alpha checks, trims, conversions. |
| Local models | ONNX Runtime (matting, upscaling) | No key and no per-call cost for those steps. |
| PSD reading | `psd-tools` | Reads templates: layers, groups, text layer content and fonts. |
| PSD writing | `psd-tools` for pixel layers and groups; `psd-writer`, a small internal Node service using `ag-psd`, for text layers | `psd-tools` cannot create text layers or change their text (checked, 1.24.0). The Node part is one small, isolated service: JSON layer list in, PSD out. |
| Hebrew calendar | `pyluach` | Hebrew dates and gematria numerals (`א׳ חשון תשפ״ז`). |
| Tooling | `uv` (dependencies), Ruff (lint/format), mypy, pytest | Fast and standard. |
| Web app | SvelteKit (static build) + TypeScript, client generated from the OpenAPI document | Same UI technology as Orenew. |
| Deployment | Docker Compose on one VPS (D2): Caddy (HTTPS), API, worker, psd-writer, web, Postgres, RustFS. The same file runs locally. | One command to run everything, locally and in production. |

### 9.3 Repository layout

```
backend/                 Python package `framegen` (one codebase, two entry points)
  framegen/api/          HTTP API (FastAPI routers)
  framegen/worker/       job runners
  framegen/spec/         frame spec models, validation, re-flow rules (exported as JSON Schema)
  framegen/render/       spec → SVG/HTML → PNG / PSD layers
  framegen/providers/    provider interfaces and adapters
  framegen/pipeline/     analyst, planner, reviser, painter, transparency methods
  framegen/storage/ db/  object storage, database models, migrations
  tests/
services/psd-writer/     Node + ag-psd: writes PSD text layers (internal only)
web/                     SvelteKit web app
sdk/typescript/          client generated from the OpenAPI document (published)
deploy/                  docker-compose.yml, Caddyfile, backup scripts
```

### 9.4 Renderer determinism

The renderer is the only thing that draws final images. Given a spec, its pieces and
its fonts, it always produces the same pixels. Drafts and packages use the same code
at different sizes, so what the photographer approved is what they receive.
Chromium and fonts are pinned per renderer version, and each version records the
renderer version that drew it.

---

## 10. API

### 10.1 Conventions

- REST over HTTPS, JSON, versioned under `/v1`. Breaking changes only in a new version.
- OpenAPI 3.1 document at `/v1/openapi.json`; reference docs generated from it.
- Resource IDs are prefixed strings (`prj_…`, `ver_…`, `job_…`, `ast_…`).
- Every mutating request accepts an `Idempotency-Key` header.
- Long work returns `202 Accepted` with a job. Jobs are followed by polling
  `GET /v1/workspaces/{workspace_id}/jobs/{id}`, by server-sent events at its `/events`, or by
  webhooks registered per workspace (signed).
- Errors are `{ "error": { "code": "provider_missing_capability", "message": "…",
  "detail": { … } } }` with stable codes, so clients (like Orenew, which translates
  every message) can show their own text.
- Lists use cursor pagination.
- **Auth:** browser sessions for the web app; workspace API keys for scripts; OAuth 2
  (authorization code + PKCE) for third-party apps acting for a user, such as a future
  Orenew.

### 10.2 Resources

A workspace's resources live under its path: `/v1/brand-kit` below stands for
`/v1/workspaces/{workspace_id}/brand-kit`, and so on. Roles are checked once, at that
prefix (D5). Accounts (`/v1/auth/…`, `/v1/me`), the workspace list and invitations sit
outside it.

| Endpoint | Purpose |
|---|---|
| `POST /v1/assets` → pre-signed upload; `POST /v1/assets/{id}/complete`; `GET /v1/assets[/{id}]` | Upload any file (6.2); list and download. |
| `GET/PUT /v1/brand-kit` | Stamps, fonts, colours. |
| `GET/POST/DELETE /v1/provider-credentials` | Connect provider keys; `POST …/{id}/test` checks one. Keys are never returned. |
| `GET/POST /v1/output-presets` | Output presets. |
| `POST /v1/library/frames` → job | Import PSD/PNG as a template (analysis + mapping). |
| `GET /v1/library/frames`, `PATCH …/{id}` | Browse; confirm or fix component mapping. |
| `GET/PATCH /v1/style-profile` | See and edit preferences and learned style. |
| `POST /v1/projects` | Create a project: brief, headline, date, references, preset, optional template. |
| `POST /v1/projects/{id}/drafts` → job | First draft. `?estimate=true` returns the cost estimate only. |
| `POST /v1/projects/{id}/messages` → job | A revision in words. |
| `PATCH /v1/projects/{id}/versions/{v}/spec` | A direct edit (JSON Patch); creates a new version. |
| `GET /v1/projects/{id}/versions` | The version tree with draft images. |
| `POST /v1/projects/{id}/versions/{v}/approve` | Approve; renders the other orientation as a draft. |
| `POST /v1/projects/{id}/packages` → job | Produce the package. `?estimate=true` supported. |
| `GET /v1/packages/{id}` | Status, file list, download links. |
| `POST /v1/render` → job | Render any valid spec + output preset directly (the template quick path, and integrators that edit specs themselves). |
| `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/events` | Job status and progress stream. |
| `GET /v1/usage` | Provider calls and estimated cost, by project and period. |

### 10.3 Security of provider keys

Keys are encrypted at rest with envelope encryption (a per-workspace data key, wrapped
by a master key kept in a Docker secret on the VPS, outside the database and its
backups). They are decrypted only
inside workers for the duration of a call, never logged, never returned by the API,
and can be revoked at any time. Only workspace admins can add or remove keys.

### 10.4 Room for a hosted, pay-per-use version

Not built now; kept possible by: every provider call already metered (7.2), credentials
resolved through one function (which can later return platform keys instead of the
workspace's), and plans/limits checked at one point in the API.

---

## 11. Data model

| Entity | Key fields |
|---|---|
| `user` | email, name, language |
| `workspace` | name, kind (personal/studio) |
| `membership` | user, workspace, role (owner/admin/member) |
| `provider_credential` | workspace, provider, encrypted key, label, last checked |
| `asset` | workspace, kind (reference, font, stamp, template-source, piece, render, package), storage key, mime, size, pixel size, checksum |
| `brand_kit` | workspace, stamps (text or asset), fonts, colours, default stamp placement |
| `library_frame` | workspace, source asset, derived template spec, component mapping, style brief, embedding, confirmed |
| `style_profile` | workspace, explicit preferences, learned fields, summary, updated from (events) |
| `output_preset` | workspace, name, outputs |
| `project` | workspace, title, brief, headline, date, references, preset, template, budget cap, status |
| `message` | project, role, text, attachments, resulting version |
| `version` | project, parent, spec (JSON), pieces used, draft assets per orientation, renderer version, created by (planner/reviser/user edit/template) |
| `piece` | workspace, asset, prompt, provider + model, transparency method, resolution, parent piece (for upscales/edits) |
| `job` | workspace, type, input, status, progress, result, error |
| `package` | project, version, preset, files, ZIP asset |
| `provider_call` | workspace, project, job, provider, model, units, estimated cost, duration, outcome |
| `api_key`, `oauth_client`, `webhook` | integration access |

Specs and pieces are immutable once created; changes always make new rows. That is
what makes the version tree, "go back to any draft", and exact re-downloads work.

---

## 12. Build order

Each milestone is usable on its own.

| # | Milestone | Done when |
|---|---|---|
| M0 | **Foundation.** Monorepo, Docker Compose, API skeleton with auth and workspaces, asset upload, jobs with SSE, OpenAPI docs, CI. | A file can be uploaded and a dummy job followed to completion through the API. |
| M1 | **Spec + renderer.** Frame spec schema, renderer (vector decorations, window cut, headline, date with both calendars, stamp), PNG output, output presets with the ready-made sizes, brand kit. | A stroke-style and a bar-style frame are produced in both orientations, at exact sizes, with correct Hebrew, without any AI. |
| M2 | **Templates.** PSD import and mapping, quick re-render with new text, packages. | A photographer's existing PSD frame is reused with new names and date in under a minute, no AI. |
| M3 | **AI drafting.** Provider interface + first adapters, credentials, planner, painter, transparency methods, low-res portrait drafts, cost estimates, usage records. | A verbal brief produces a portrait draft with transparent pieces from at least two different providers. |
| M4 | **Conversation.** Reviser, version tree, direct edits, approval with landscape draft. | Ten consecutive revisions each change only what was asked. |
| M5 | **Packages at full quality.** Upscaling, all outputs, layered PSD export. | The full package opens in Photoshop with editable text, and the PNGs load in Orenew with the window found automatically. |
| M6 | **References and memory.** Invitation and object-photo analysis, PNG template import with text removal, library import, style profile, library retrieval. | A frame made from an invitation photo is recognisably in its style; preferences carry over to the next project. |
| M7 | **Integrators.** API keys, OAuth, webhooks, published SDK, API stability review. | An external script performs the full workflow using only the SDK and docs. |

---

## 13. Decisions

| # | Decision | Date |
|---|---|---|
| D1 | **Licence: AGPL-3.0**, intended. Anyone running a changed FrameGen as a service must publish their changes. | 2026-10-11 |
| D2 | **Hosting: one VPS with Docker Compose.** Caddy terminates HTTPS; Postgres and the S3 storage (RustFS, D9) run as containers with volumes on the VPS. Nightly backups of the database and storage go off the machine (`pg_dump` + storage bucket sync). Workers run in the same Compose setup and can be scaled with more replicas, or moved to a second machine later without changes, because they share nothing but Postgres and storage. | 2026-10-11 |
| D3 | **Fonts are included in packages.** The package's `fonts/` folder holds every font file the design uses. Built-in fonts are open-licence, so including them is allowed. When a photographer uploads a font, they confirm they have the right to use and share it; FrameGen shows that confirmation once per font. | 2026-10-11 |
| D4 | **Contributions need the agreement.** As in Orenew, outside contributions are accepted only with the agreement in `CONTRIBUTING.md`, so the owner can reuse all of FrameGen's code. | 2026-10-11 |
| D5 | **Studio roles: owner, admin, member only for now.** Finer permissions (for example members who can use but not see provider keys) come later; roles are checked at one point in the API so more can be added. | 2026-10-11 |
| D6 | **Retention is configurable.** Settings per deployment (overridable per workspace later): drafts and unused pieces 30 days after the project's last activity; packages, uploads, templates and library 365 days; job records and usage 365 days. A workspace can delete everything in one action. Numbers are a starting point for the first version. | 2026-10-11 |
| D7 | **Interface in one language (English) for now**, built so a language can be added easily: all interface text in `web/src/locales/<language>.json`, components contain no text, layout with CSS logical properties so right-to-left needs no second layout, and the API returns error codes, never user-facing text. Frame text (headline, date) supports every language, Hebrew and English first. | 2026-10-11 |
| D8 | **Backend in Python**, not TypeScript, because the owner knows it better. PSD reading uses `psd-tools`. Because `psd-tools` cannot write text layers, a small internal `psd-writer` service (Node, `ag-psd`) adds them; it is the only non-Python backend code. The web app stays TypeScript. | 2026-10-11 |
| D9 | **Storage: RustFS instead of MinIO.** MinIO stopped publishing its community images in October 2025 and archived its repository. RustFS (Apache-2.0, S3-compatible) replaces it. The code uses plain S3 through `boto3`, so the storage server can be swapped again without code changes. | 2026-10-11 |

## 14. Open questions

None at the moment. If anything in this document is unclear or seems to be missing, ask
rather than assume.
