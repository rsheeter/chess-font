# Algorithmic `GRAD` Master Generation for Variable Chess Fonts

This document details how [`scripts/make_source.py`](scripts/make_source.py) synthesizes point-compatible **Thin (`GRAD 100`)**, **Regular (`GRAD 400`)**, and **Thick (`GRAD 700`)** masters in Glyphs 3 (`.glyphs`) format from flat, multi-layered upstream SVG artwork.

The central engineering challenge is reconciling two competing requirements:
1. **Visual fidelity across a wide grade excursion (`GRAD 100`–`700`)**: Upstream chess artwork combines broad solid silhouettes (`400–700` UPM across) with delicate interior cutouts and hatching strokes (`1.5px` in a `45 × 45` SVG `viewBox`, or `~33.3` UPM).
2. **Strict multi-master point compatibility**: Every master layer for a glyph must share an isomorphic contour graph—identical contour count, contour ordering, winding direction, start-node index, segment count, and `line`/`curve` node types—so linear master interpolation produces clean outlines without topological kinks or self-intersecting loops.

---

## 1. Design Space & Duplexed Metrics

Per [Google Fonts Knowledge: Grade (`GRAD`) axis](https://fonts.google.com/knowledge/glossary/grade_axis), `GRAD` modulates perceived stroke weight ("typographic color" / ink density) while holding advance widths and vertical metrics invariant. Unlike `wght`, changing `GRAD` on hover, selection, or dark-mode halation compensation never triggers text or board-grid reflow.

| Parameter | Value | Implementation Notes |
| :--- | :--- | :--- |
| `unitsPerEm` (`upm`) | `1000` | Standard 1000-UPM coordinate grid |
| Vertical metrics | `ascender = 800`, `descender = -200` | Full 1000-unit vertical em-box (`y ∈ [-200, 800]`); optical center at `(500, 300)` |
| Advance width | `width = 1000` | Duplexed across all 56 glyphs and all 3 `GRAD` masters |
| `GRAD` axis range | `100` – `700` (default `400`) | 3 masters: `Thin Grade` (`100`), `Regular Grade` (`400`), `Thick Grade` (`700`) |
| Base offset delta (`δ`) | `-24.0` / `0.0` / `+26.0` UPM | Target outward normal displacement at `GRAD 100` / `400` / `700` |

---

## 2. SVG Normalization & Planar Boolean Resolution (`GRAD 400` Base Master)

Upstream chess SVGs (`cburnett`, `kmar-livius`, `kmar-meridian`, `lichess-merida`) are authored for 2D SVG renderers using layered strokes (`stroke-width`, `stroke-linecap`, `stroke-linejoin`, `stroke-miterlimit`), `<use>` clones, nested affine transforms, and opaque white (`#ffffff` / `#fff`) fills or strokes painted *over* black (`#000000`) bases to carve out interior highlights (crown ribs, mitre slits, and collar bands).

Because an OpenType outline source represents a single binary planar region (ink vs. counter), [`_svg_to_ink_path`](scripts/make_source.py) resolves the net foreground ink in five deterministic stages:

### 2.1 Unit Cleanup & `picosvg` Normalization
- [`_clean_svg_units`](scripts/make_source.py) strips CSS unit suffixes (`px`, `pt`) on numeric SVG attributes (`width="50px"`, `stroke-width="1.5px"`) and normalizes `SVG.fromstring(...).topicosvg(inplace=False)`.
- `picosvg` expands `<use>` references, resolves inline CSS `style="..."` declarations, flattens group transforms, converts geometric primitives (`<circle>`, `<rect>`, `<polygon>`) and stroked paths into closed `<path>` outlines, and normalizes `fill-rule="evenodd"` to `nonzero`.

### 2.2 Coordinate-Space Mapping (`SVG viewBox` → `+Y`-up Font Space)
- Before running planar boolean operations, each shape is mapped from its SVG `viewBox` `(min_x, min_y, vw, vh)` (`+Y`-down) into the `1000 × 1000` font em-box (`x ∈ [0, 1000]`, `y ∈ [-200, 800]`, `+Y`-up) via an aspect-preserving uniform scale `s = min(1000 / vw, 1000 / vh)`:
  ```
  x_font = (x_svg − min_x) × s + dx
  y_font = (vh − (y_svg − min_y)) × s − 200 + dy
  ```
- Transforming into font space *prior* to boolean clipping ensures that curve subdivision tolerances inside `skia-pathops` operate at uniform `1000`-UPM precision regardless of whether the source SVG uses a `45 × 45` (`cburnett`, `s ≈ 22.22`) or `2048 × 2048` (`kmar-livius`, `s ≈ 0.488`) coordinate grid.

### 2.3 Paint-Order `skia-pathops` Boolean Accumulation
- In a 2D painter's-algorithm renderer, subsequent paths occlude earlier paths. [`_svg_to_ink_path`](scripts/make_source.py) iterates over the flattened shapes in document order, computing relative luminance `L = 0.299 R + 0.587 G + 0.114 B` (`L ∈ [0, 1]`) from each shape's resolved `fill` via [`_color_luminance`](scripts/make_source.py):
  - **Foreground ink (`L < 0.5`)**: Accumulated via planar union:
    `ink = pathops.op(ink, shape_path, pathops.PathOp.UNION)`
  - **Background knockout (`L ≥ 0.5`)**: Subtracted via planar difference:
    `ink = pathops.op(ink, shape_path, pathops.PathOp.DIFFERENCE)`
- Under the hood, `skia-pathops` (Cary Clark, Google) constructs a planar arrangement of cubic/quadratic Bézier segments—a curved generalization of the Bentley–Ottmann sweep-line algorithm (Bentley & Ottmann, 1979) and Vatti clipping (Vatti, 1992)—computing exact curve–curve intersections, splitting segments at intersection parameters, and extracting minimal boundary cycles according to non-zero winding numbers.

### 2.4 Overlap Removal & Exact Degree Elevation (`Q` → `C`)
- Calling `ink.simplify(fix_winding=True)` removes any residual self-overlaps and normalizes contour winding.
- [`_extract_cubic_contours`](scripts/make_source.py) then walks `svg_pathops.svg_commands(ink)` and converts any quadratic Bézier segments `(P₀, Q₁, P₂)` into exact degree-elevated cubics `(P₀, C₁, C₂, P₂)` using standard Bernstein basis degree elevation (Farin, *Curves and Surfaces for CAGD*):
  ```
  C₁ = P₀ + (2/3) × (Q₁ − P₀)
  C₂ = P₂ + (2/3) × (Q₁ − P₂)
  ```
- Zero-length degenerate segments (`‖P_end − P_start‖ < 10⁻⁴` UPM) are pruned so downstream tangent and normal evaluations never divide by zero.

---

## 3. Winding Normalization, Canonical Start Nodes & 3-Way Contour Classification

### 3.1 PostScript Winding Conventions in `.glyphs` Sources
Glyphs 3 (`.glyphs`) sources follow cubic PostScript outline conventions in a `+Y`-up Cartesian frame:
- **Outer silhouettes** wind **counter-clockwise (CCW)**, yielding a positive signed area `A > 0`.
- **Inner counters (cutouts)** wind **clockwise (CW)**, yielding a negative signed area `A < 0`.

[`_contour_signed_area`](scripts/make_source.py) evaluates the signed area of each contour by sampling 4 points per cubic segment (`_contour_polygon`) and applying the shoelace formula:
```
A = (1/2) × Σᵢ (xᵢ × yᵢ₊₁ − xᵢ₊₁ × yᵢ)
```

### 3.2 Why Uniform Normal Offsetting Fails Typographically: 3-Way Contour Classification
In classical type design and algorithmic weight generation—see Walter Tracy (*Letters of Credit*, 1986), Fred Smeijers (*Counterpunch*, 1996), and Tim Ahrens (*Size-specific adjustments to type designs* / RMX Scaler, 2007)—increasing weight or grade cannot move outer silhouettes and inner counters at identical rates:
1. If an outer silhouette expands by `+δ` and an interior counter contracts by the full `+δ`, narrow negative spaces (such as the Black Bishop's mitre cross-slit or the parallel hatching ribs in `kmar-meridian`) rapidly choke and fill in, destroying internal contrast long before the outer silhouette looks bold.
2. Conversely, tiny isolated positive contours (such as `25 × 25` UPM crown jewels or horse nostrils) have a total radius smaller than `|δ| = 24` UPM; offsetting them inward by `-24` UPM in `GRAD 100` would invert them through their own centers.

To solve both problems, [`_normalize_and_classify_contours`](scripts/make_source.py) partitions every contour into one of three geometric categories based on signed area `A` and bounding-box area `B = (x_max − x_min) × (y_max − y_min)` (with threshold `_SMALL_ACCENT_AREA_THRESHOLD = 4500.0` UPM²):

| Category | Classification Rule | Winding | Role & Offset Behavior |
| :--- | :--- | :--- | :--- |
| **Category A (`silhouette`)** | `A > 0` and `B ≥ 4500` UPM² | CCW (`A > 0`) | Primary outer piece boundary; receives full `1.0 × δ` outward normal offset |
| **Category B (`counter`)** | `A < 0` (hole inside silhouette) | CW (`A < 0`) | Interior negative-space cutout; receives damped `-0.65 × δ` offset + minor-axis cap |
| **Category C (`accent`)** | `A > 0` and `B < 4500` UPM² | CCW (`A > 0`) | Small isolated detail (jewel, dot); scaled radially around centroid + translated |

### 3.3 Canonical Start-Node Anchoring
After enforcing CCW/CW winding via [`_reverse_contour`](scripts/make_source.py), [`_canonicalize_contour_start`](scripts/make_source.py) cyclically rotates each contour's segment list so `contour.start` is anchored at the on-curve vertex minimizing `(round(y, 3), round(x, 3))` (bottom-most, then left-most). Because `GRAD 100` and `GRAD 700` are derived directly from the canonicalized `GRAD 400` contour list without re-sorting, start-node correspondence is guaranteed by construction.

---

## 4. Topology-Preserving Curve Offsetting & Local Clearance Clamping

### 4.1 Prior Art: Why Classical Offset-Curve Algorithms Break Multi-Master Compatibility
Let `γ(t) = (x(t), y(t))` be a planar cubic Bézier curve with unit tangent `T(t) = γ′(t) / ‖γ′(t)‖` and outward unit normal `N(t)`. The exact parallel (offset) curve at distance `δ` is:
```
γ_δ(t) = γ(t) + δ × N(t)
```
As established by Farouki & Neff (1990, *"Analytic properties of plane offset curves"* and *"Algebraic properties of plane offset curves"*, *Computer Aided Geometric Design*), `γ_δ(t)` for a cubic Bézier is generally an **algebraic curve of degree 10** whose arc-length derivative involves a square root `‖γ′(t)‖`. It cannot be represented exactly as a single cubic Bézier spline.

Furthermore, whenever the signed curvature `κ(t)` of a concave segment satisfies `κ(t) = -1 / δ` (i.e., `δ` exceeds the local radius of curvature `R(t)`, crossing the curve's evolute), the exact offset curve `γ_δ(t)` develops a **cusp singularity**, reverses tangent direction, and forms a self-intersecting "swallowtail" loop.

Classical CAD and font-engineering offset algorithms handle these two properties via **adaptive subdivision and topological clipping**:
- **Tiller & Hanson (1984, *"Offsets of Two-Dimensional Profiles"*, *IEEE CG&A*)**: Offsets the control polygon lines and recursively subdivides the Bézier curve at `t = 0.5` wherever the radial deviation from the true offset exceeds tolerance.
- **Hoschek (1985, *"Offset curves in the plane"*, *CAD*)** and **Elber, Lee & Kim (1997, *"Comparing Offset Curve Approximation Methods"*, *IEEE CG&A*)**: Perform least-squares cubic spline fitting with adaptive knot insertion.
- **Levien (2018–2024, `kurbo::offset` / *"Offsetting cubic Béziers"*)**: Analyzes curvature extrema and cusps, subdividing cubics at inflection and maximum-curvature points to maintain high geometric accuracy.

While adaptive subdivision is ideal for generating a *static* font outline, it is **incompatible with variable font master synthesis**: running an adaptive offsetter at `δ = -24`, `δ = 0`, and `δ = +26` subdivides each master at different parameter values `t`, producing different numbers of cubic segments per contour across masters.

### 4.2 Fixed-Topology Control-Polygon Offset ([`_grade_contour`](scripts/make_source.py))
To preserve a strict 1-to-1 bijection of `GSNode` sequences across `GRAD 100`, `400`, and `700`, [`_grade_contour`](scripts/make_source.py) operates as a **fixed-topology vertex-and-handle deformation** on the `GRAD 400` control graph, augmented with four geometric safeguards against cusp inversion and opposite-wall collision.

#### Step 1: Category-Specific Displacement (`effective_delta`) & Minor-Axis Counter Clamping
- **Category A (`silhouette`)**:
  `effective_delta = +δ` (`-24.0` UPM at `GRAD 100`, `+26.0` UPM at `GRAD 700`).
- **Category B (`counter`)**:
  `effective_delta = -0.65 × δ` (`+15.6` UPM at `GRAD 100`, `-16.9` UPM at `GRAD 700`).
  When contracting a counter (`effective_delta < 0` in `GRAD 700`), [`_grade_contour`](scripts/make_source.py) computes the counter's minor bounding-box dimension `minor_dim = min(bbox_width, bbox_height)` and clamps:
  ```
  |effective_delta| ≤ 0.34 × minor_dim   (_COUNTER_MINOR_AXIS_CLAMP_RATIO = 0.34)
  ```
  This global-per-contour cap prevents narrow elongated slits from collapsing more than `68%` (`2 × 34%`) of their minor width before local per-vertex raycast clamping even engages.
- **Category C (`accent`)**:
  Small isolated contours are transformed via an affine similarity map around their centroid `(cx, cy)` with radial scale `s = clamp(1.0 + δ / 400.0, 0.55, 1.45)` and a radial pull `pull = -0.15 × δ` toward the glyph center `(500, 300)` so interior dots track the surrounding contour shift without distorting or vanishing.

#### Step 2: On-Curve Vertex Miter Bisectors & Turn-Angle Clamping
At each on-curve vertex `Vᵢ` joining incoming segment `Sᵢ₋₁` and outgoing segment `Sᵢ`:
1. The unit incoming tangent `t_in` is evaluated from `Vᵢ − C₂(Sᵢ₋₁)` (falling back to the chord `Vᵢ − Vᵢ₋₁` if `‖Vᵢ − C₂(Sᵢ₋₁)‖ < 10⁻³` UPM).
2. The unit outgoing tangent `t_out` is evaluated from `C₁(Sᵢ) − Vᵢ` (falling back to the chord `Vᵢ₊₁ − Vᵢ`).
3. Rotating a unit tangent `(tx, ty)` by `-90°` (`(ty, -tx)`) yields the right-hand unit normal `n_in` and `n_out`. Because outer silhouettes wind CCW and inner counters wind CW, `(ty, -tx)` points *outward* from black ink on silhouettes and *inward* into the cutout hole on counters.
4. By Tiller–Hanson control-polygon intersection, the exact offset lines of adjacent tangents intersect along the unit normal bisector:
   ```
   bᵢ = normalize(n_in + n_out)
   miter_scale = 1 / dot(bᵢ, n_out) = 1 / cos(θᵢ / 2)
   ```
   where `θᵢ = arccos(dot(t_in, t_out))` is the exterior turn angle at `Vᵢ`.
5. **Miter limit**: On acute corners (`θᵢ > 135°`, or interior corner angle `< 45°`, `_MIN_CORNER_ANGLE_RAD = π / 4`) such as Queen coronet spikes or Knight ear tips, `1 / cos(θᵢ / 2)` blows up toward infinity. We clamp `miter_scale ≤ 1.45` (`_MAX_MITER_SCALE = 1.45`), preventing spikes from shooting out of the em-box at `GRAD 700`.

#### Step 3: Opposing-Wall Raycast Clearance Clamping (Directional Local Feature Size)
In computational geometry, the **Medial Axis** (Blum, 1967) of a shape `Ω` is the locus of points having more than one closest point on the boundary `∂Ω`, and the directional thickness or **Shape Diameter Function** (Shapira, Shamir & Cohen-Or, 2008; applied to font analysis as "feeler rays" by Simon Cozens) measures the distance from a boundary point `Vᵢ` along its normal cone to the opposing boundary wall.

Whenever an offset displacement exceeds half the directional distance to an opposing contour wall, the two walls cross over the medial axis and invert the local winding number. In `cburnett` and `kmar-meridian`, `1.5px` strokes measure `~33.3` UPM wide at `GRAD 400`, whereas `|δ| = 24.0` UPM at `GRAD 100` would move the two walls toward each other by `24.0 + 15.6 = 39.6` UPM (`> 33.3` UPM).

To prevent medial-axis crossover without altering contour topology:
1. [`_build_clearance_segments`](scripts/make_source.py) linearizes all contours in the glyph (sampling 4 sub-segments per cubic via `_contour_polygon`) into `ClearanceSegment(p0, p1, normal)` records, where `normal = (ty, -tx)` is the outward unit normal from black ink.
2. For each vertex `Vᵢ` moving in unit direction `uᵢ = sign(effective_delta) × bᵢ`, [`_ray_opposing_clearance`](scripts/make_source.py) casts a 2D ray `R(t) = Vᵢ + t × uᵢ` (`t > 0.5` UPM) against all clearance segments whose outward normal opposes `Vᵢ`'s outward normal:
   ```
   dot(n_outward(Vᵢ), n_seg) < -0.25
   ```
   and finds the minimum ray–segment intersection parameter `d_clear = min(t)`.
3. The vertex displacement magnitude `|Δᵢ|` is then clamped to a safe share (`44%`) of the available clearance beyond a hard minimum floor:
   - **When thinning (`effective_delta < 0`, ray travels through black ink toward the opposite wall of the stroke)**:
     ```
     |Δᵢ| ≤ max(0.0, (d_clear − 5.0) × 0.44)   (_MIN_STROKE_THICKNESS = 5.0 UPM)
     ```
     Even if both opposing walls saturate against this clamp simultaneously (`2 × 0.44 = 0.88 < 1.0`), at least `5.0` UPM of hairline ink remains between them.
   - **When thickening (`effective_delta > 0`, ray travels across white negative space toward an opposing contour wall)**:
     ```
     |Δᵢ| ≤ max(0.0, (d_clear − 4.5) × 0.44)   (_MIN_GAP_CLEARANCE = 4.5 UPM)
     ```
     This prevents adjacent crenellations on the Rook, parallel hatching slits in `kmar-meridian`, or collar gaps from welding shut at `GRAD 700`.

#### Step 4: Short-Chord Cusp / Bowtie Relaxation
Raycasting protects against *opposing* walls colliding, but a single contour can also self-intersect locally when a short segment `Sᵢ` of chord length `Lᵢ = ‖Vᵢ₊₁ − Vᵢ‖` lies in a concave fillet of radius `R < |δ|` (the evolute cusp singularity). When `Vᵢ` and `Vᵢ₊₁` move along converging normals, the displaced chord vector `Cᵢ′ = (Vᵢ₊₁ + Δᵢ₊₁) − (Vᵢ + Δᵢ)` reverses direction relative to the original chord `Cᵢ = Vᵢ₊₁ − Vᵢ`, forming a local bowtie loop.

[`_grade_contour`](scripts/make_source.py) runs two iterative relaxation passes over all adjacent vertex pairs `(Vᵢ, Vᵢ₊₁)`. Whenever the projected displaced chord falls below `25%` of its original length along `Cᵢ`:
```
dot(Cᵢ′, Cᵢ) < 0.25 × ‖Cᵢ‖²
```
both endpoint displacements `Δᵢ` and `Δᵢ₊₁` are damped toward their mean displacement `M = 0.5 × (Δᵢ + Δᵢ₊₁)`:
```
Δᵢ   ← M + k × (Δᵢ   − M)
Δᵢ₊₁ ← M + k × (Δᵢ₊₁ − M)
```
where `k ∈ [0, 1)` is chosen so `dot(Cᵢ′, Cᵢ) = 0.25 × ‖Cᵢ‖²`. This eliminates local cusp inversions while keeping vertex positions smooth.

#### Step 5: Chord-Proportional Cubic Handle Scaling (Hobby / Tiller–Hanson Heuristic)
Once the displaced on-curve endpoints `P₀′ = P₀ + Δᵢ` and `P₃′ = P₃ + Δᵢ₊₁` of a cubic segment `(P₀, P₁, P₂, P₃)` are fixed, placing the off-curve control points `P₁′` and `P₂′` requires preserving both endpoint G¹ tangent continuity and approximate curvature scaling:
1. If `P₁` and `P₂` are merely translated by their endpoint deltas (`P₁ + Δᵢ`, `P₂ + Δᵢ₊₁`), a concave curve whose chord `‖P₃′ − P₀′‖` shrinks by `50%` retains its full original handle lengths `‖P₁ − P₀‖` and `‖P₂ − P₃‖`. In Bernstein form, when `‖P₁ − P₀‖ + ‖P₂ − P₃‖ > ‖P₃′ − P₀′‖`, the off-curve handles cross over each other and introduce an unwanted inflection or loop inside the cubic span (Hobby, 1986, *"Smooth, easy to compute interpolating splines"*).
2. Instead, [`_grade_contour`](scripts/make_source.py) scales each handle vector `h₁ = P₁ − P₀` and `h₂ = P₂ − P₃` proportionally to the endpoint chord ratio `s_chord`:
   ```
   s_chord = clamp(‖P₃′ − P₀′‖ / ‖P₃ − P₀‖, 0.35, 1.55)
   P₁′ = P₀′ + s_chord × (P₁ − P₀)
   P₂′ = P₃′ + s_chord × (P₂ − P₃)
   ```
   Because `P₁′ − P₀′` is a positive scalar multiple of `P₁ − P₀`, the tangent direction at `P₀′` (and symmetrically at `P₃′`) is strictly preserved, while handle velocity scales linearly with arc length—matching the analytical offset scaling `R′ / R = (R ± δ) / R` of circular arcs.

---

## 5. Component Inheritance for Rotated Chess Symbols (`U+1FA06`–`U+1FA46`)

The 44 rotated and turned chess pieces in the Unicode **Chess Symbols** block (`U+1FA06`–`U+1FA46`) are generated by [`_make_component`](scripts/make_source.py) as `GSComponent` references (`ref = uni2654`–`uni265F`) rotated clockwise by `cw_degrees ∈ {45°, 90°, 135°, 180°, 225°, 270°, 315°}` around the glyph optical center `(cx, cy) = (500, 300)`.

In a `+Y`-up coordinate system, a clockwise rotation by `cw_degrees` corresponds to a counter-clockwise affine rotation angle `θ = -cw_degrees` (normalized to `(-180°, 180°]`). Because Glyphs 3 applies a component's rotation around the origin `(0, 0)` before translating by `pos = (dx, dy)`, centering the rotation at `(cx, cy)` requires:
```
dx = cx − (cx × cos θ − cy × sin θ)
dy = cy − (cx × sin θ + cy × cos θ)
```
Because `(θ, dx, dy)` is invariant across `GRAD 100`, `400`, and `700`, the rotated symbols require zero outline duplication and inherit all `GRAD` outline interpolation directly from the 12 base piece glyphs (`U+2654`–`U+265F`).

---

## Appendix A: Rejected Approaches

During the design of [`scripts/make_source.py`](scripts/make_source.py), five alternative approaches to `GRAD` master synthesis were evaluated and rejected:

### A.1 Independent Per-Master Boolean Buffering (`skia-pathops` / Clipper / Polygon Offsetting)
- **Idea**: Take the resolved `GRAD 400` `pathops.Path`, offset every contour by `±δ` using a general stroke-expansion library (`picosvg` stroke expansion, `ClipperOffset`, or `kurbo` adaptive offset), and run `pathops.simplify()` on each master independently to clean up self-intersections.
- **Why it fails**:
  1. **Topological genus changes**: At `δ = +26`, narrow counters pinch into two separate holes or vanish entirely (`N_contours(700) ≠ N_contours(400)`). At `δ = -24`, thin necks pinch through, splitting one outer silhouette into two islands.
  2. **Adaptive segment count mismatch**: Even when contour count is preserved, adaptive cubic fitting inserts extra on-curve nodes on tight curves at `GRAD 700` that do not exist at `GRAD 400` or `GRAD 100`.
  3. **Start-node drift**: Boolean simplification re-indexes contour start vertices based on sweep-line event order, causing contours to twist by 1–3 segments during interpolation.

### A.2 Centroid-Based Radial Scaling of Outer and Inner Contours
- **Idea**: Scale Category A silhouettes outward around `(500, 300)` by `1 + α` and scale Category B counters inward around their respective bounding-box centroids by `1 − β`.
- **Why it fails**: Radial scaling is only equivalent to normal offsetting on circles centered at the scale origin. On non-convex chess silhouettes (such as the Rook's three battlements, the Knight's concave throat, or curved collar bands that wrap around the piece), scaling a contour around its centroid shifts outer and inner walls in the *same* radial direction on off-center features, making one side of a stroke twice as thick while thinning or inverting the opposite side.

### A.3 Unclamped Tiller–Hanson Control-Polygon Offsetting
- **Idea**: Displace all on-curve vertices by `effective_delta × miter_scale × bᵢ` without raycast clearance clamping or short-chord relaxation.
- **Why it fails**: Works cleanly only for small excursions (`|δ| ≤ 10` UPM). Beyond `δ ≈ -17` UPM, the `33.3`-UPM (`1.5px`) strokes in `cburnett` and `kmar-meridian` invert through each other (`1.65 × 17 = 28.05` UPM, plus miter amplification at corners), producing inside-out loops. Beyond `δ ≈ +16` UPM, narrow mitre and hatching slits (`18–22` UPM wide) cross over and invert into black-on-black artifacts.

### A.4 Post-Offset `pathops.simplify()` Cleanup Pass
- **Idea**: Run fixed-topology vertex offsetting to generate `GRAD 100` and `GRAD 700`, and then pass the resulting contours through `pathops.simplify()` to snip off any local bowtie self-intersections.
- **Why it fails**: Whenever `simplify()` removes a self-intersecting loop, it deletes the 2–4 nodes that formed the loop and merges the crossing segments at a newly created intersection vertex. That immediately changes the contour's node count relative to `GRAD 400`, making the master non-interpolable. Prevention (via raycast clearance clamping and chord relaxation *before* constructing the final nodes) is mandatory because post-hoc topological surgery is impossible in a fixed-node-graph variable font.

### A.5 Medial-Axis / Straight-Skeleton Extraction and Re-Stroking (METAFONT Paradigm)
- **Idea**: Extract a 1D medial axis or straight skeleton (Aichholzer et al., 1995) from the `GRAD 400` ink region, associate a radius function `r(s)` along the skeleton, and reconstruct `GRAD 100` and `GRAD 700` as the envelope of disks of radius `r(s) + δ`.
- **Why it fails**: Unlike uniform-stroke handwriting or simple sans-serif stems, pictorial chess glyphs mix massive variable-width silhouettes (the body of a Knight or Queen) with tiny angular cutouts. Medial axis transforms on complex 2D shapes are notoriously unstable with respect to small boundary perturbations, and reconstructing an envelope from a modified skeleton produces variable numbers of boundary vertices at 3-way branch junctions—again breaking point compatibility with the original `GRAD 400` outline.

---

## Appendix B: Generalizing Beyond Chess — Programmatic Axis Synthesis for Static and Variable Type Families

A natural question for font engineering pipelines is whether this topology-preserving offset + directional clearance architecture is specific to chess symbols, or whether it can programmatically synthesize `GRAD`, `wght`, or other axes for **existing single-weight static families**—or **inject new axes into existing variable font sources**.

### B.1 Why Chess Symbols Are Both Forgiving and Extreme
Chess symbols occupy an unusual corner of type design space:
- **Where chess is more forgiving than text type**:
  1. **Isotropic stroke geometry**: Chess pieces are pictorial illustrations rather than calligraphic letterforms. Unlike Latin text faces—which obey Gerrit Noordzij's translation/expansion contrast principles (*The Stroke of the Pen*, 1985), requiring vertical stems to thicken 2×–4× faster than horizontal hairlines and arches—chess strokes can be offset isotropically (`δ_x = δ_y`) without violating script-specific contrast conventions.
  2. **No typographic alignment zones**: Chess pieces sit centered inside an em-square rather than aligning to a shared baseline, x-height, cap-height, and overshoot grid.
  3. **Naturally monospaced**: Every symbol already occupies a `1000`-UPM square, so locking advance width for `GRAD` causes no inter-character spacing collisions.
- **Where chess is harder than text type**:
  1. **Extreme feature-size dynamic range**: A single glyph (`kmar-meridian` Black Queen or `lichess-merida` Knight) contains 15–25 contours spanning both `600`-UPM solid silhouettes and `18`-UPM interior slits—a `33:1` feature-size ratio rarely seen in text glyphs outside complex CJK ideographs.
  2. **Arbitrary SVG construction**: Unlike clean hand-drawn `.glyphs` sources with extrema points, upstream SVGs contain arbitrary tangent joints, short fillets, and boolean knockouts that stress miter and chord-flip stability.

### B.2 Synthesizing `GRAD` on Single-Weight Static Text Families
Can this pipeline automatically add a `GRAD` axis (e.g., for dark-mode halation compensation or UI active-state bolding without layout shift) to an existing single-weight static font? **Yes—especially over a practical UI `GRAD` range (`±15` to `±25` UPM)—provided three typographic extensions are added to [`_grade_contour`](scripts/make_source.py)**:

1. **Anisotropic Offset Tensor `(δ_x, δ_y)` (Contrast Preservation)**:
   - Instead of scalar displacement `δ × nᵢ`, replace the circular offset metric with an elliptical (Noordzij/RMX) offset tensor:
     ```
     Δ(nᵢ) = (δ_x × nᵢ_x, δ_y × nᵢ_y)   with   δ_y = α × δ_x,  α ∈ [0.30, 0.50]
     ```
   - When a contour tangent is vertical (`|nᵢ_x| ≈ 1`, a vertical stem), the wall moves by the full `δ_x`. When the tangent is horizontal (`|nᵢ_y| ≈ 1`, a crossbar, serif, or arch crown), the wall moves by only `30%–50%` of `δ_x`. This prevents `e`, `a`, `s`, `B`, and `8` counters from clogging when grade increases (Tim Ahrens, *RMX Scaler*, 2007; Linus Romer, `strokeweight`, 2018).
2. **Vertical Metric & Alignment-Zone Pinning**:
   - On outer silhouettes, vertices whose `y`-coordinate lies on horizontal alignment flats (`y ≈ 0` baseline, `y ≈ xHeight`, `y ≈ capHeight`) with a horizontal tangent (`|t_y| < ε`) must have their vertical displacement pinned (`Δ_y = 0`), while overshoot extrema (`o`, `e`, `c`, `S`) scale their vertical displacement by a small overshoot factor (`~0.1 × δ_x`). Without alignment-zone pinning, increasing `GRAD` makes flat-top glyphs (`H`, `E`, `T`, `x`, `z`) grow taller than `capHeight`/`xHeight` and sink below the baseline.
3. **Inter-Glyph Sidebearing Clearance Clamping**:
   - Because `GRAD` locks `advanceWidth`, expanding outer silhouettes by `+δ_x` reduces `LSB` and `RSB` by `δ_x` each. Adding two synthetic vertical clearance walls at `x = 0` and `x = advanceWidth` to [`_build_clearance_segments`](scripts/make_source.py) automatically prevents outer contours from colliding across glyph boundaries in tight glyph pairs (`rn`, `nn`, `ll`, `ii`).

**Best candidates**: Low-to-moderate contrast sans-serifs, geometric grotesks, monospace coding fonts, rounded UI fonts, and icon sets (`Material Symbols`-style).

### B.3 Synthesizing `wght` (Weight) or `opsz` (Optical Size) from a Single Static Font
Extending from `GRAD` to a full `wght` axis on a static family is straightforward for **moderate weight ranges** (e.g., generating a `Light 300` – `Medium 500` – `SemiBold 600` axis from a `Regular 400` static font) by combining the anisotropic offset tensor `(δ_x, δ_y)` above with proportional advance-width expansion:
```
advanceWidth′ = advanceWidth + 2 × κ_spacing × δ_x
```
However, synthesizing **extreme weight ranges (`Thin 100` to `Black 900`)** or **high-contrast serif families** purely by boundary offsetting hits three structural limits of type design:
1. **Diagonal Crotch & Apex Migration (`M`, `W`, `N`, `V`, `v`, `w`, `4`)**:
   - When two diagonal strokes meet at an acute interior crotch (such as the inner vertex of `V` or `W`), moving the inner walls inward along their normals pushes the crotch vertex *upward* by `δ / sin(θ/2)` (`3×–5×` the stem delta). In human type design, the on-curve crotch vertex is deliberately pulled back down (or opened into an ink trap) while the outer apex is widened. Our miter clamp (`_MAX_MITER_SCALE`) prevents a runaway spike, but true `Black 900` weights require sliding vertices *along* the stroke tangent to redistribute mass.
2. **Stroke-Junction Mass Accumulation**:
   - Where a curve branches from a vertical stem (`n`, `h`, `m`, `p`, `b`, `d`), human Bold/Black masters carve deep asymmetric cut-ins at the shoulder junction so the join does not form a dark ink blot. Pure boundary offsetting treats the inner counter uniformly and cannot invent new ink traps where none exist in the `Regular` master.
3. **Design-Space Topology Switching**:
   - Across wide `wght` ranges, many families switch glyph topology (`$` switching from complete to split vertical bars, `a`/`g` bowls opening, or serif brackets merging into slabs), which requires OpenType `rvrn` /FeatureVariations alternates rather than continuous `gvar` deformation.

For **`opsz` (Optical Size)**, however, programmatic synthesis from a single static font is remarkably effective: an `opsz` reduction (e.g. `14pt → 8pt`) consists almost entirely of:
1. Modest positive anisotropic grade on thin strokes (`+δ_y` hairline reinforcement so thin arches and crossbars survive low-DPI rasterization),
2. Slight x-height augmentation (piecewise-linear vertical remap between `baseline`, `xHeight`, and `capHeight`), and
3. Loose tracking (`+ΔLSB`, `+ΔRSB`),
all of which preserve exact contour topology and point compatibility.

### B.4 Injecting New Axes into Existing Variable Font Sources (`.glyphs` / `.designspace`)
Arguably the **highest-leverage production application** of these techniques is not turning static fonts into full `100`–`900` variable fonts from scratch, but **augmenting existing variable font sources**—either fully automatically or as a designer-in-the-loop pre-master generator:

1. **Synthesizing `GRAD` from an Existing `wght` + `wdth` Variable Font (Manifold Projection)**:
   - If a variable family already has human-authored `wght` and `wdth` masters, its `gvar` deltas *already* encode human-designed contrast ratios, crotch migration, ink traps, and alignment-zone pinning.
   - Because increasing `wght` widens glyphs (`∂W / ∂wght > 0`) and decreasing `wdth` narrows them (`∂W / ∂wdth < 0`), a `GRAD` master can be synthesized primarily by projecting along the **iso-advance-width trajectory** in `(wght, wdth)` space (`Δwght > 0, Δwdth < 0` chosen per glyph so `ΔadvanceWidth = 0`), followed by a small residual normal offset (`±3–5` UPM) where needed to equalize stem weight across glyphs of different widths (`i` vs `m`).
2. **Synthesizing `GRAD` from a Single-Axis `wght` Variable Font (Hybrid Vector Decomposition)**:
   - Even when a variable font only has a `wght` axis (no `wdth` axis), the existing `wght` delta vector `ΔV_wght = V_bold − V_reg` at every node provides an exact, designer-authored "ground-truth direction" for how that glyph should gain weight (including zero vertical motion on baselines/cap-heights and proper ink-trap sliding at junctions).
   - To create a `GRAD` master from `ΔV_wght` while keeping `advanceWidth` fixed:
     1. Apply a fraction `λ × ΔV_wght` of the `wght` delta to all nodes (giving the glyph its human-designed thicker strokes and wider advance width `W + ΔW`), and
     2. Apply an affine horizontal compression `x′ = x × (W / (W + ΔW))` combined with a small outward horizontal normal offset `+δ_x × n_x` on vertical stems to restore the `1 / (1 + ΔW/W)` stem thinning caused by the horizontal compression.
   - Because every operation is a smooth function of the existing point-compatible `V_reg` and `V_bold` node arrays, the resulting `GRAD` masters are **100% point-compatible by construction** and inherit the human designer's optical corrections at every junction.
3. **Bootstrapping `opsz` or Dark-Mode Masters for Designer Refinement**:
   - In a production `.glyphs` workflow, adding a new axis (`GRAD` or `opsz`) doubles the number of corner masters a type designer must draw and keep point-compatible. Running the topology-preserving normal offset + raycast clearance pipeline directly on the existing `.glyphs` master layers generates conflict-free, 100% interpolation-compatible starting masters in seconds, allowing the type designer to spend their time on high-level optical refinement (`M`/`W` joins, terminal angles) rather than mechanical contour offsetting and start-node debugging.

---

## References & Further Reading

1. **Ahrens, Tim (2007)**. *Size-specific adjustments to type designs: An investigation of the principles guiding the design of optical sizes*. Master's thesis, University of Reading; implemented in the *Font Remix Tools (RMX Scaler)*.
2. **Aichholzer, Oswin, Franz Aurenhammer, David Alberts, and Bernd Gärtner (1995)**. *"A novel type of skeleton for polygons"*. *Journal of Universal Computer Science*, 1(12), 752–761.
3. **Amenta, Nina, Marshall Bern, and David Eppstein (1998)**. *"The Crust and the β-Skeleton: Combinatorial Curve Reconstruction"*. *Graphical Models and Image Processing*, 60(2), 125–135 (Local Feature Size `LFS(x)`).
4. **Bentley, Jon Louis, and Thomas A. Ottmann (1979)**. *"Algorithms for reporting and counting geometric intersections"*. *IEEE Transactions on Computers*, C-28(9), 643–647.
5. **Blum, Harry (1967)**. *"A transformation for extracting new descriptors of shape"*. In *Models for the Perception of Speech and Visual Form*, MIT Press, 362–380.
6. **Clark, Cary (2012–2024)**. *Skia PathOps: Planar Boolean Operations on Bézier Paths* (`skia-pathops`). Google Inc.
7. **Elber, Gershon, In-Kwon Lee, and Myung-Soo Kim (1997)**. *"Comparing Offset Curve Approximation Methods"*. *IEEE Computer Graphics and Applications*, 17(3), 62–71.
8. **Farin, Gerald (2002)**. *Curves and Surfaces for CAGD: A Practical Guide* (5th ed.). Morgan Kaufmann (Bernstein basis degree elevation and subdivision).
9. **Farouki, Rida T., and C. A. Neff (1990)**. *"Analytic properties of plane offset curves"* & *"Algebraic properties of plane offset curves"*. *Computer Aided Geometric Design*, 7(1–4), 83–114.
10. **Hobby, John D. (1986)**. *"Smooth, easy to compute interpolating splines"*. *Discrete & Computational Geometry*, 1(2), 123–140.
11. **Hoschek, Josef (1985)**. *"Offset curves in the plane"*. *Computer-Aided Design*, 17(2), 77–82.
12. **Knuth, Donald E. (1986)**. *The METAFONTbook*. Addison-Wesley.
13. **Levien, Raph (2018–2024)**. *`kurbo`: 2D Curves Library in Rust* & technical notes on cubic Bézier offsetting and cusp analysis.
14. **Noordzij, Gerrit (1985 / 2005)**. *The Stroke of the Pen: Fundamental Aspects of Western Writing*. Koninklijke Academie van Beeldende Kunsten / Hyphen Press.
15. **Romer, Linus (2018)**. *`strokeweight`: Algorithmic Stroke Weight Modification for FontForge / Python*.
16. **Shapira, Lior, Ariel Shamir, and Daniel Cohen-Or (2008)**. *"Consistent mesh partitioning and skeletonisation using the shape diameter function"*. *The Visual Computer*, 24(4), 249–259.
17. **Smeijers, Fred (1996)**. *Counterpunch: Making Type in the Sixteenth Century, Designing Typefaces Now*. Hyphen Press.
18. **Tiller, Wayne, and Eric G. Hanson (1984)**. *"Offsets of Two-Dimensional Profiles"*. *IEEE Computer Graphics and Applications*, 4(9), 36–46.
19. **Tracy, Walter (1986)**. *Letters of Credit: A View of Type Design*. Gordon Fraser.
20. **Vatti, Bala R. (1992)**. *"A generic solution to polygon clipping"*. *Communications of the ACM*, 35(7), 56–63.
