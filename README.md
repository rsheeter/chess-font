# chess-font
I was curious what's involved in creating a chess font :)

For each major permissively licensed set of vector chess assets I could find we create a Unicode font using the standard Chess block:
* 12 base piece glyphs (`U+2654`–`U+265F`, Miscellaneous Symbols) across 3 duplexed `GRAD` masters (`100`, `400`, `700`)
* 44 rotated/turned Unicode Chess Symbols (`U+1FA06`–`U+1FA46`) defined as transformed component references (`GSComponent`)

Gemini did all the work, I just nudged it in the desired direction.

[Live Demo (GitHub Pages)](https://rsheeter.github.io/chess-font/)

## Creation process

Before any python operation establish a virtual environment:

```shell
$ python3 -m venv .venv
$ source .venv/bin/activate
$ pip install -r scripts/requirements.txt
```

1. `python3 scripts/vendor_glyphs.py` - update `third_party/` vendored SVG assets and [`third_party/README.md`](third_party/README.md)
2. `python3 scripts/make_source.py` - establish `sources/<set>.glyphs` for each vendored SVG set
    * Generates grade variants as described in [./grade-generation.md](./grade-generation.md)
3. Edit in Glyphs
    * _In theory, currently just uses generated glyphs_
4. `python3 scripts/build_fonts.py` - download the latest [`googlefonts/fontc`](https://github.com/googlefonts/fontc) release binary for the current OS/arch and compile `sources/<set>.glyphs` into `build/fonts/<set>.ttf`
5. Test the [`docs/index.html`](docs/index.html) demo page locally (deployed automatically to GitHub Pages via [`.github/workflows/pages.yml`](.github/workflows/pages.yml)):
    ```shell
    $ python3 scripts/build_fonts.py --dest docs/fonts
    $ python3 -m http.server -d docs 8000
    ```
    Then open `http://localhost:8000`.

## Technical Transcript: Engineering a High-Quality Variable Chess Font with a Grade (GRAD) Axis

This document contains the complete technical dialogue, architectural decisions, toolchain pipelines, and mathematical strategies established for constructing an open-source, high-quality variable chess font containing a duplexed Grade (`GRAD`) axis.

---

### 1. Initial Discovery: Open-Source Vector & Font Landscapes

#### Vector Chess Pieces (SVG)
The digital chess ecosystem heavily relies on open-source vector foundations. Three primary collections offer cleanly constructed, scalable graphics:
*   **The "Cburnett" Standard Set:** The iconic 2D chess pieces used by Wikipedia, [Lichess](https://github.com/lichess-org/lila/tree/master/public/piece/cburnett), and thousands of apps. Licensed under **Creative Commons Attribution-ShareAlike (CC BY-SA)** and hosted on [Wikimedia Commons](https://commons.wikimedia.org/wiki/Category:SVG_chess_pieces).
*   **[Kmar Chess SVG Piece Sets](https://github.com/kmar/chess_svg_piece_sets):** A GitHub repository hosting multiple sets dual-licensed under **CC0 / Public Domain**, including classic styles and *Meridian* (a 1952 newspaper aesthetic).
*   **[Green Chess Vectors](https://greenchess.net/info.php?item=downloads):** Comprehensive SVG sets supporting both standard chessmen and historical or "fairy" chess variants (circular, hexagonal) under CC BY-SA.

#### Chess Fonts (TTF/OTF)
Chess typefaces are divided into **Diagram Layout Fonts** (matrix-based board wrappers) and **Text/Notation Fonts**:

*   **[Open Chess Font](https://github.com/joshwalters/open-chess-font):** 
    * Built by Josh Walters (CC BY-SA 3.0) from Cburnett SVGs modified with a 5px white knockout halo.
    * Uses [potrace](https://potrace.sourceforge.net/) in [generate.sh](https://github.com/joshwalters/open-chess-font/blob/master/generate.sh) in a `vector => 2000×2000 bitmap => vector` round-trip (`inkscape` → `ImageMagick` → `potrace`) to flatten strokes and knock out dark-square hatch lines without vector boolean ops—replacing Cburnett's clean Béziers with dense auto-traced paths.
*   **[Open Chess Font Fairy](https://github.com/samboy/OpenChessFontFairy):**
    * Maintained by Sam Trenholme (`samboy`, CC BY-SA 3.0) as a direct FontForge derivative ([`OpenChessFontFairy.sfd`](https://github.com/samboy/OpenChessFontFairy/blob/main/OpenChessFontFairy.sfd)) of Josh Walters' `potrace`-traced font.
    * Swaps uppercase/lowercase to match **Chess Merida** mappings (lowercase = light square, uppercase = hatched dark square), aliases `space`/`+` to `z`/`x`, and adds 50-unit rectangular border glyphs (`!"#$%/()`).
    * Fairy pieces are 180°-rotated Bishop/Knight glyphs (`a/A`, `s/S`, `g/G`, `h/H`) plus a Wikimedia compound rook+knight (*Cardinal/Marshal*) glyph (`d/D`, `f/F`).
*   **[Chess Merida Web Toolkit](https://github.com/vasiliyaltunin/chess-merida-font):**
    * Vasiliy Altunin’s webfont conversion (MPL 2.0) of Armando H. Marroquín's 1998 freeware [`MERIFONT.TTF`](https://github.com/vasiliyaltunin/chess-merida-font/tree/master/source) (originally drawn in CorelDraw 3.0/7.0), converted unmodified to `.eot`/`.woff`/`.ttf`/`.svg` via `convertio.co`.
    * [`chessmerida-webfont.css`](https://github.com/vasiliyaltunin/chess-merida-font/blob/master/css/chessmerida-webfont.css) is a 93-line Font Awesome–style wrapper mapping only the 14 unhatched light-square glyphs via `::before { content: "..." }` (e.g., `.cm-w-pawn` → `"p"`, `.cm-b-pawn` → `"o"`), relying on HTML `<table>` cells for boards; piece interiors are transparent, so dark square backgrounds bleed through.

##### Unicode Support ([Chess Symbols in Unicode](https://en.wikipedia.org/wiki/Chess_symbols_in_Unicode))
**None of the three fonts above support the Unicode chess blocks** (**0%** coverage):
*   **Miscellaneous Symbols (`U+2654`–`U+265F`, Unicode 1.1, 1993):**
    *   The 12 standard white and black pieces (`♔♕♖♗♘♙` / `♚♛♜♝♞♟`).
*   **Chess Symbols (`U+1FA00`–`U+1FA6F`, Unicode 11.0–17.0, 2018–2025):**
    *   102 heterodox/fairy symbols: neutral pieces, rotated/turned pieces, equihoppers, compound knighted pieces, shatranj, and xiangqi.

Why and how they map glyphs instead:
*   **1998 ASCII Diagram Hack:**
    *   Unicode only encodes standalone pieces (`U+2654`–`U+265F`).
    *   It has no codepoints for **pieces pre-composited onto hatched dark squares** or **board border/coordinate tiles**.
    *   To render 8×8 boards in 1990s word processors without graphics layering, **Chess Merida** mapped light-square pieces, dark-square pieces, and borders onto ASCII keys (`p`/`P`, `q`/`Q`, `+`, `*`) and Latin-1/MacRoman high bytes (`U+00A1`–`U+00FF`).
    *   Both **Open Chess Font** projects copied this ASCII keymap for backwards compatibility.
*   **`Open Chess Font Fairy` vs. `U+1FA00`–`U+1FA53`:**
    *   Created in 2019 (the same year Unicode 12.0 standardized fairy chess codepoints), but uses `ISO-8859-1` encoding (49 ASCII glyphs in `U+0020`–`U+007E`).
    *   Maps its fairy pieces to unused ASCII letters instead of their official Unicode codepoints:
        *   Turned Bishop: `f/F`, `g/G` instead of `U+1FA21` (`🨡`) / `U+1FA27` (`🨧`)
        *   Turned Knight: `h/H`, `s/S` instead of `U+1FA22` (`🨢`) / `U+1FA28` (`🨨`)
        *   Knight-Rook / Chancellor: `a/A`, `d/D` instead of `U+1FA4F` (`🩏`) / `U+1FA52` (`🩒`)
*   **[`chess_merida_unicode`](https://github.com/xeyownt/chess_merida_unicode) (2007 fork):**
    *   Michaël Peeters's fork of `MERIFONT.TTF` *does* remap the 12 unhatched light-square pieces to **`U+2654`–`U+265F`**.
    *   Moves non-standard board tiles into the **Unicode Private Use Area (`U+E000`–`U+E4FF`)**:
        *   `U+E154`–`U+E15F`: Pieces on hatched dark squares
        *   `U+E254`–`U+E259`: Solid silhouette masks for CSS color layering
        *   `U+E300`–`U+E35F`: Board borders and rank/file coordinates
    *   Predates Unicode 11.0/12.0, so it has no `U+1FA00`–`U+1FA6F` coverage.

---

### 2. Rendering Move Sequences: Figurine Algebraic Notation (FAN)

To display a mini-piece instead of a character initial (e.g., rendering a Bishop glyph inline for `Bb5`), typefaces require specialized internal structures depending on the execution target:

#### Web Development: The Ligature Approach
Modern web engines use font ligatures. Instead of manually altering underlying raw text databases, the web font toolkit intercepts character strings via standard CSS selectors. For example, typing a capital `B` inside an initialized `<span class="chess-move">` class triggers an OpenType ligature that swaps the letter for a perfectly scaled, inline figurine glyph while leaving the trailing lowercase coordinate string (`b5`) untouched.

#### Desktop Publishing: TrueType Figurine Symbol Layouts
For software like MS Word, Adobe InDesign, or LaTeX, layout engines utilize traditional TrueType fonts mapped specifically for running text. These packages contain dedicated **Figurine Variants** (historically suffixed as `T1` or `S1`). 
*   **The Mapping Mechanism:** Typing standard English piece initials (`KQRBN`) directly outputs a mini-piece scaled exactly to the typeface’s running line-height.
*   **Language-Specific Tokens:** Legacy open-source packages vary by language constraint. `T1` targets English notation, while `T2` targets Romance languages (mapping Bishop to `A` for *Alfil* or `F` for *Fou*).

---

### 3. The Conceptual Core: The Variable [Grade (`GRAD`) Axis](https://fonts.google.com/knowledge/glossary/grade_axis)

A dedicated open-source chess font featuring a functional Grade axis does not currently exist in the wild. Implementing one solves a critical UI layout constraint: **Text Reflow**.

#### The Grade Axiom
In variable typography, a **[Grade (`GRAD`) axis](https://fonts.google.com/knowledge/glossary/grade_axis)** alters the perceived weight ("typographic color" / stroke thickness) of a glyph *without changing its physical bounding box or advance width*.

```text
Standard Bold:  [  BISHOP GLYPH  ]  -> Widens character block, breaks grid alignment.
Graded Dark:    [ BISHOP GLYPH ]    -> Thickens internal strokes, advance width remains identical.
```

*   **Why `font-weight: bold` breaks chess layouts:**
    *   Standard bolding expands character advance widths horizontally.
    *   In inline move tables or 8×8 diagram grids, width changes shift columns, fracture board alignments, and trigger unintended line wraps.
*   **Why `GRAD` solves it:**
    *   Thickens or thins internal contours in place—ideal for UI hover/active states or compensating for dark-mode halation—while keeping every metric box frozen at a fixed advance width (`1000` UPM).

#### Alternative Workarounds Today
*   **Duplexed Static Fonts:** Rare legacy families engineered with identical horizontal widths across separate Medium and Bold font files.
*   **SVG Stroke-Width Interpolation:** Bypassing font engines on the web by rendering inline SVGs and driving `stroke-width` / `fill` via CSS variables.
*   **Unicode System Typeface Fallback:** Using global variable fonts like *Roboto Flex* that include a `GRAD` axis, though their `U+2654`–`U+265F` glyphs are generic dingbat symbols rather than tournament-grade chess pieces.

---

### 4. The Engineering Pipeline: Automated Multi-Master Compilation

To build a variable chess font programmatically, we normalize the vendored SVGs into monochrome ink contours, emit multi-master `.glyphs` sources via [`scripts/make_source.py`](scripts/make_source.py), and compile them with [`googlefonts/fontc`](https://github.com/googlefonts/fontc) via [`scripts/build_fonts.py`](scripts/build_fonts.py):

```text
[third_party/glyphs/<set>/*.svg] ➔ picosvg + skia-pathops ➔ scripts/make_source.py ➔ [sources/<set>.glyphs] ➔ scripts/build_fonts.py (fontc) ➔ [build/fonts/<set>.ttf]
```

#### The Toolchain Structure
1.  **SVG Normalization (`picosvg`):**
    *   Flattens SVG primitives (`<circle>`, `<rect>`), transforms, and strokes (`stroke-width`, `stroke-linecap`, `stroke-linejoin`) into explicit `<path>` outlines.
2.  **Monochrome Boolean Resolution (`skia-pathops`):**
    *   Iterates through normalized paths in SVG paint order, applying boolean `UNION` for dark ink paths and `DIFFERENCE` for white/light knockout fills (`#fff`, `#ececec`, Merida highlight gradients) to produce self-intersection-free monochrome contours.
3.  **Coordinate & Curve Conversion (`picosvg` + `fontTools`):**
    *   Maps the SVG `viewBox` into the `1000` UPM font em-box (`ascender = 800`, `descender = -200`) and elevates any quadratic Bézier segments to cubic Béziers.
4.  **Multi-Master `.glyphs` Source Construction (`glyphsLib`):**
    *   Builds a native Glyphs 3 source (`sources/<set>.glyphs`) defining the `GRAD` axis centered at `400` (`Regular Grade` with the initial glyphs) and spanning `±200` (`Thin Grade` at `200`, `Thick Grade` at `600`) with locked `1000`-unit advance widths for `U+2654`–`U+265F`.
5.  **Optical Polish & Compilation (`Glyphs App` / [`fontc`](https://github.com/googlefonts/fontc)):**
    *   Can be opened directly in Glyphs App for optical refinement, and compiled to variable `.ttf` binaries (`build/fonts/<set>.ttf`) via [`scripts/build_fonts.py`](scripts/build_fonts.py).

---

### 5. The Hybrid Parametric Design Methodology

Blindly offsetting all vector points inward or outward fails optically. [`scripts/make_source.py`](scripts/make_source.py) segments contours by geometric role before generating the `Thin Grade` and `Thick Grade` layers:

#### A. Fixed Centerline Scaling & Duplexed Metrics
*   Every master layer locks `width = 1000` across `Thin`, `Regular`, and `Thick`.
*   Contours expand or contract around their internal centerlines while keeping the glyph advance width invariant.

#### B. Segmented Path Categories

```text
                ┌──────────────────────────────┐
                │   Contextual Path Segment    │
                └──────────────┬───────────────┘
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Outer Silhouette│    │Internal Counters│    │Filigree/Accents │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ Asymmetric      │    │ Suppress Offset │    │ Coordinate      │
│ Offsetting      │    │ (Prevent Choke) │    │ Translation     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

*   **Category A: Outer Base Silhouettes (Trunks, Pedestals, Bases)**
    *   *Phenomenon:* Human eyes perceive horizontal strokes as heavier than vertical strokes of identical mathematical thickness; uniform offsetting makes pieces look squat and bloated.
    *   *Rule:* Apply asymmetric offsetting along the vertex normal—full horizontal offset (`+X` for Thick, `-X` for Thin) and attenuated vertical offset (`+0.5X` / `-0.5X`).
*   **Category B: Internal Counters (Negative Space Cavities)**
    *   *Phenomenon:* Delicate interior cutouts (Rook battlements, Bishop miter slot, Knight eye/nostril/neck highlights) choke and fill in under full dilation.
    *   *Rule:* Suppress the offset factor on interior counter contours (attenuated to 35% of the base grade delta) to preserve negative space at heavy grades.
*   **Category C: Intricate Filigree & Micro-Accents (Small Detached Details)**
    *   *Phenomenon:* Small standalone contours distort or collide under heavy dilation.
    *   *Rule:* Apply minimal dilation (25%) paired with a radial translation away from the glyph centroid to maintain breathing room.

#### C. Geometric Fail-Safes
*   **Angle Cap Clipping:**
    *   At acute corners where the turn angle `θ < 45°` (such as Knight ears or crown tips), miter projection is clamped to prevent long spikes.
*   **Handle Ratio Preservation:**
    *   When adjacent on-curve anchor points `P₀, P₁` shift to `P₀′, P₁′`, their cubic Bézier off-curve handles (`offcurve` nodes) translate with their anchors and scale proportionally by `‖P₁′ − P₀′‖ / ‖P₁ − P₀‖` so curves do not kink or flatten.

---

### 6. The Hand-Off Protocol

Running [`scripts/make_source.py`](scripts/make_source.py) establishes an **80% mathematical automation baseline** where every master layer guarantees:
*   **Identical contour and node counts** across `Thin Grade`, `Regular Grade`, and `Thick Grade`.
*   **Matched winding directions** (clockwise outer silhouettes, counter-clockwise internal counters).
*   **Matched start-node indexing** for zero interpolation mismatches in Glyphs App or `fontmake`.

