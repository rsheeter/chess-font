#!/usr/bin/env python3
"""Builds multi-master Glyphs 3 (.glyphs) sources from vendored chess SVG sets.

Pipeline per SVG set in third_party/glyphs/<set>/:
1. Pre-clean Inkscape/CorelDraw SVG quirks and normalize to flat <path> elements
   via picosvg.
2. Resolve foreground ink vs. background/interior knockouts in paint order using
   skia-pathops (UNION for dark fills, DIFFERENCE for light/white fills).
3. Map coordinates from the SVG viewBox into the 1000-UPM font em-box
   (ascender 800, descender -200) and elevate any quadratic curves to cubics.
4. Classify contours (Category A outer silhouettes, Category B internal counters,
   Category C small accents) and generate interpolation-compatible Thin (200),
   Regular (400), and Thick (600) masters along the duplexed GRAD axis.
5. Write sources/<set>.glyphs via glyphsLib.
"""

import argparse
import math
from pathlib import Path
import re
from typing import Literal, NamedTuple

from fontTools.pens.recordingPen import RecordingPen
from glyphsLib.classes import GSAxis, GSFont, GSFontMaster, GSGlyph, GSLayer
import pathops
from picosvg import svg_pathops
from picosvg.svg import SVG
from picosvg.svg_transform import Affine2D


_UPM = 1000
_ASCENDER = 800
_DESCENDER = -200
_CAP_HEIGHT = 700
_X_HEIGHT = 500
_ADVANCE_WIDTH = 1000

_DEFAULT_GRADE = 400
_GRADE_RANGE = 200

_SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PX_UNIT_RE = re.compile(r"(\d)px\b")
_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Minimum turn angle (45 deg) below which sharp miter projections are clamped.
_MIN_CORNER_ANGLE_RAD = math.radians(45.0)
_MAX_MITER_SCALE = 1.6
# Contours with bounding-box area below this threshold (in font units^2) are
# treated as Category C filigree/accents rather than Category A main silhouettes.
_ACCENT_AREA_THRESHOLD = 4500.0


Point = tuple[float, float]
ContourCategory = Literal["silhouette", "counter", "accent"]


class PieceSpec(NamedTuple):
    """Mapping between a vendored SVG piece stem and its Unicode glyph metadata."""

    stem: str
    glyph_name: str
    codepoint: int
    description: str


class MasterSpec(NamedTuple):
    """Configuration for a single duplexed Grade (GRAD) master."""

    master_id: str
    name: str
    grade_value: int
    # Offset delta in font units (+outward for Thick, -inward for Thin).
    grade_delta: float


class CubicSegment(NamedTuple):
    """A single line or cubic Bezier segment ending at `end`."""

    kind: Literal["line", "curve"]
    c1: Point | None
    c2: Point | None
    end: Point


class Contour(NamedTuple):
    """A closed cubic contour with deterministic start point and segment list."""

    start: Point
    segments: tuple[CubicSegment, ...]


# Standard Unicode Miscellaneous Symbols chess block (U+2654..U+265F).
_PIECES: tuple[PieceSpec, ...] = (
    PieceSpec("wk", "uni2654", 0x2654, "WHITE CHESS KING"),
    PieceSpec("wq", "uni2655", 0x2655, "WHITE CHESS QUEEN"),
    PieceSpec("wr", "uni2656", 0x2656, "WHITE CHESS ROOK"),
    PieceSpec("wb", "uni2657", 0x2657, "WHITE CHESS BISHOP"),
    PieceSpec("wn", "uni2658", 0x2658, "WHITE CHESS KNIGHT"),
    PieceSpec("wp", "uni2659", 0x2659, "WHITE CHESS PAWN"),
    PieceSpec("bk", "uni265A", 0x265A, "BLACK CHESS KING"),
    PieceSpec("bq", "uni265B", 0x265B, "BLACK CHESS QUEEN"),
    PieceSpec("br", "uni265C", 0x265C, "BLACK CHESS ROOK"),
    PieceSpec("bb", "uni265D", 0x265D, "BLACK CHESS BISHOP"),
    PieceSpec("bn", "uni265E", 0x265E, "BLACK CHESS KNIGHT"),
    PieceSpec("bp", "uni265F", 0x265F, "BLACK CHESS PAWN"),
)

# Grade (GRAD) axis masters: https://fonts.google.com/knowledge/glossary/grade_axis
#
# Unlike Weight (wght), the Grade (GRAD) axis adjusts perceived stroke thickness
# ("typographic color") without altering advance widths or horizontal metrics,
# preventing layout shift / text reflow across:
# - UI interaction states (e.g. hover/active emphasis in move tables or boards)
# - Background contrast / dark-mode halation compensation (negative grade on
#   dark backgrounds, positive grade on low-contrast or small sizes)
#
# We place the unmodified upstream SVG vectors at 400 (matching Regular weight)
# and span +/- 200 units across three duplexed masters (200, 400, 600), all
# locked to `_ADVANCE_WIDTH` (1000 UPM).
_MASTERS: tuple[MasterSpec, ...] = (
    MasterSpec(
        master_id="master-thin",
        name="Thin Grade",
        grade_value=_DEFAULT_GRADE - _GRADE_RANGE,
        grade_delta=-12.0,
    ),
    MasterSpec(
        master_id="master-regular",
        name="Regular Grade",
        grade_value=_DEFAULT_GRADE,
        grade_delta=0.0,
    ),
    MasterSpec(
        master_id="master-thick",
        name="Thick Grade",
        grade_value=_DEFAULT_GRADE + _GRADE_RANGE,
        grade_delta=12.0,
    ),
)


def _color_luminance(color_str: str | None) -> float:
    """Returns relative luminance in [0.0, 1.0]; defaults to 0.0 (black ink)."""
    if not color_str:
        return 0.0
    val = color_str.strip().lower()
    if val in ("none", "transparent", "white"):
        return 1.0
    if val == "black":
        return 0.0
    m = _HEX_COLOR_RE.match(val)
    if not m:
        return 0.0
    hex_digits = m.group(1)
    if len(hex_digits) == 3:
        r = int(hex_digits[0] * 2, 16) / 255.0
        g = int(hex_digits[1] * 2, 16) / 255.0
        b = int(hex_digits[2] * 2, 16) / 255.0
    else:
        r = int(hex_digits[0:2], 16) / 255.0
        g = int(hex_digits[2:4], 16) / 255.0
        b = int(hex_digits[4:6], 16) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _resolve_shape_fill(pico_svg: SVG, fill: str) -> str:
    """Resolves `fill`, looking up the first <stop> color if `fill` is `url(#...)`."""
    if not fill.startswith("url("):
        return fill
    grad_el = pico_svg.resolve_url(fill, "*")
    for stop_el in grad_el:
        stop_color = stop_el.attrib.get("stop-color")
        if stop_color:
            return stop_color
    return "#ffffff"


def _svg_to_ink_path(svg_path: Path) -> pathops.Path:
    """Normalizes `svg_path` via picosvg and resolves monochrome ink via pathops."""
    # Strip trailing 'px' unit suffixes (used in kmar-* Inkscape SVGs on width,
    # height, and stroke-width) before handing off to picosvg.
    raw_svg = _PX_UNIT_RE.sub(r"\1", svg_path.read_text(encoding="utf-8-sig"))
    pico_svg = SVG.fromstring(raw_svg).topicosvg()

    vbox = pico_svg.view_box()
    if vbox is None:
        raise ValueError(f"Could not determine viewBox for {svg_path}")

    # Map SVG viewBox (vbox.x..vbox.x+vbox.w, vbox.y..vbox.y+vbox.h with +Y down)
    # into font em-box (0..1000, _DESCENDER.._ASCENDER with +Y up).
    sx = _ADVANCE_WIDTH / vbox.w
    sy = -_UPM / vbox.h
    dx = -vbox.x * sx
    dy = _ASCENDER - vbox.y * sy
    svg_to_font = Affine2D(sx, 0.0, 0.0, sy, dx, dy)

    ink = pathops.Path()
    for shape in pico_svg.shapes():
        fill = _resolve_shape_fill(pico_svg, shape.fill)
        transformed = shape.apply_transform(svg_to_font)
        subpath = svg_pathops.skia_path(transformed.as_cmd_seq(), transformed.fill_rule)
        op = (
            pathops.PathOp.UNION
            if _color_luminance(fill) < 0.5
            else pathops.PathOp.DIFFERENCE
        )
        ink = pathops.op(ink, subpath, op, fix_winding=True)

    ink.simplify(fix_winding=True, keep_starting_points=True)
    return ink


def _quad_to_cubic(p0: Point, q1: Point, p1: Point) -> tuple[Point, Point]:
    """Elevates a quadratic Bezier (p0, q1, p1) to cubic control points (c1, c2)."""
    c1 = (p0[0] + (2.0 / 3.0) * (q1[0] - p0[0]), p0[1] + (2.0 / 3.0) * (q1[1] - p0[1]))
    c2 = (p1[0] + (2.0 / 3.0) * (q1[0] - p1[0]), p1[1] + (2.0 / 3.0) * (q1[1] - p1[1]))
    return c1, c2


def _extract_cubic_contours(ink: pathops.Path) -> list[Contour]:
    """Extracts closed cubic contours from `ink`, elevating any quadratics."""
    rec = RecordingPen()
    ink.draw(rec)

    contours: list[Contour] = []
    start_pt: Point | None = None
    curr_pt: Point | None = None
    segments: list[CubicSegment] = []

    for op, pts in rec.value:
        if op == "moveTo":
            start_pt = pts[0]
            curr_pt = start_pt
            segments = []
        elif op == "lineTo":
            assert curr_pt is not None
            end_pt = pts[0]
            if math.hypot(end_pt[0] - curr_pt[0], end_pt[1] - curr_pt[1]) > 1e-4:
                segments.append(CubicSegment("line", None, None, end_pt))
                curr_pt = end_pt
        elif op == "qCurveTo":
            assert curr_pt is not None
            # Decompose implied on-curve midpoints if multiple off-curve points exist.
            off_pts = pts[:-1]
            final_pt = pts[-1]
            for idx, q_pt in enumerate(off_pts):
                if idx + 1 < len(off_pts):
                    next_q = off_pts[idx + 1]
                    seg_end = ((q_pt[0] + next_q[0]) * 0.5, (q_pt[1] + next_q[1]) * 0.5)
                else:
                    seg_end = final_pt
                c1, c2 = _quad_to_cubic(curr_pt, q_pt, seg_end)
                segments.append(CubicSegment("curve", c1, c2, seg_end))
                curr_pt = seg_end
        elif op == "curveTo":
            assert curr_pt is not None
            c1, c2, end_pt = pts[0], pts[1], pts[2]
            segments.append(CubicSegment("curve", c1, c2, end_pt))
            curr_pt = end_pt
        elif op in ("closePath", "endPath"):
            if start_pt is not None and curr_pt is not None and segments:
                if math.hypot(start_pt[0] - curr_pt[0], start_pt[1] - curr_pt[1]) > 1e-4:
                    segments.append(CubicSegment("line", None, None, start_pt))
                else:
                    last = segments[-1]
                    segments[-1] = CubicSegment(last.kind, last.c1, last.c2, start_pt)
                if len(segments) >= 2:
                    contours.append(Contour(start=start_pt, segments=tuple(segments)))
            start_pt = None
            curr_pt = None
            segments = []

    return contours


def _contour_polygon(contour: Contour) -> list[Point]:
    """Samples points along `contour` for signed-area and containment tests."""
    pts: list[Point] = []
    p0 = contour.start
    for seg in contour.segments:
        if seg.kind == "line" or seg.c1 is None or seg.c2 is None:
            pts.append(p0)
        else:
            c1, c2, p1 = seg.c1, seg.c2, seg.end
            for step in range(4):
                t = step / 4.0
                mt = 1.0 - t
                x = (
                    mt**3 * p0[0]
                    + 3 * mt**2 * t * c1[0]
                    + 3 * mt * t**2 * c2[0]
                    + t**3 * p1[0]
                )
                y = (
                    mt**3 * p0[1]
                    + 3 * mt**2 * t * c1[1]
                    + 3 * mt * t**2 * c2[1]
                    + t**3 * p1[1]
                )
                pts.append((x, y))
        p0 = seg.end
    return pts


def _signed_area(poly: list[Point]) -> float:
    """Returns signed polygon area (+CCW, -CW in +Y-up font coordinates)."""
    area = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return 0.5 * area


def _point_in_polygon(pt: Point, poly: list[Point]) -> bool:
    """Ray-casting point-in-polygon check."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            x_intersect = (x1 - x0) * (y - y0) / (y1 - y0 + 1e-12) + x0
            if x < x_intersect:
                inside = not inside
    return inside


def _reverse_contour(contour: Contour) -> Contour:
    """Reverses contour direction while keeping `contour.start` fixed."""
    pairs: list[tuple[Point, CubicSegment]] = []
    curr = contour.start
    for seg in contour.segments:
        pairs.append((curr, seg))
        curr = seg.end
    reversed_segs: list[CubicSegment] = []
    for seg_start, seg in reversed(pairs):
        if seg.kind == "line":
            reversed_segs.append(CubicSegment("line", None, None, seg_start))
        else:
            reversed_segs.append(CubicSegment("curve", seg.c2, seg.c1, seg_start))
    return Contour(start=contour.start, segments=tuple(reversed_segs))


def _normalize_and_classify_contours(
    contours: list[Contour],
) -> list[tuple[Contour, ContourCategory]]:
    """Enforces PostScript winding (CW outer, CCW counter) and classifies contours."""
    polys = [_contour_polygon(c) for c in contours]
    areas = [_signed_area(p) for p in polys]

    result: list[tuple[Contour, ContourCategory]] = []
    for idx, contour in enumerate(contours):
        sample_pt = polys[idx][0]
        # Count how many other contours strictly enclose `sample_pt`.
        depth = 0
        for other_idx, other_poly in enumerate(polys):
            if other_idx == idx:
                continue
            if abs(areas[other_idx]) <= abs(areas[idx]):
                continue
            if _point_in_polygon(sample_pt, other_poly):
                depth += 1

        is_counter = (depth % 2) == 1
        signed_a = areas[idx]
        # PostScript / Glyphs winding rule (+Y up):
        # - Outer contours must be clockwise (signed_area < 0).
        # - Inner counters must be counter-clockwise (signed_area > 0).
        if not is_counter and signed_a > 0:
            contour = _reverse_contour(contour)
        elif is_counter and signed_a < 0:
            contour = _reverse_contour(contour)

        xs = [p[0] for p in polys[idx]]
        ys = [p[1] for p in polys[idx]]
        bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys))

        if is_counter:
            category: ContourCategory = "counter"
        elif bbox_area < _ACCENT_AREA_THRESHOLD:
            category = "accent"
        else:
            category = "silhouette"

        result.append((contour, category))

    return result


def _unit_vec(dx: float, dy: float) -> Point:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _outgoing_tangent(p0: Point, seg: CubicSegment) -> Point:
    if seg.kind == "curve" and seg.c1 is not None:
        t = _unit_vec(seg.c1[0] - p0[0], seg.c1[1] - p0[1])
        if t != (0.0, 0.0):
            return t
        if seg.c2 is not None:
            t = _unit_vec(seg.c2[0] - p0[0], seg.c2[1] - p0[1])
            if t != (0.0, 0.0):
                return t
    return _unit_vec(seg.end[0] - p0[0], seg.end[1] - p0[1])


def _incoming_tangent(p0: Point, seg: CubicSegment) -> Point:
    if seg.kind == "curve" and seg.c2 is not None:
        t = _unit_vec(seg.end[0] - seg.c2[0], seg.end[1] - seg.c2[1])
        if t != (0.0, 0.0):
            return t
        if seg.c1 is not None:
            t = _unit_vec(seg.end[0] - seg.c1[0], seg.end[1] - seg.c1[1])
            if t != (0.0, 0.0):
                return t
    return _unit_vec(seg.end[0] - p0[0], seg.end[1] - p0[1])


def _grade_contour(
    contour: Contour,
    category: ContourCategory,
    grade_delta: float,
    glyph_center: Point,
) -> Contour:
    """Applies the Section 5 hybrid parametric Grade transformation to `contour`.

    Guarantees identical segment count, node types, and start node ordering
    across all Grade masters so variable font interpolation never mismatches.
    """
    if abs(grade_delta) < 1e-6:
        return contour

    n = len(contour.segments)
    # On-curve anchors: anchors[0] == contour.start, anchors[k] == segments[k-1].end.
    anchors: list[Point] = [contour.start] + [seg.end for seg in contour.segments[:-1]]

    # Compute outward-pointing normal at each on-curve anchor.
    # For a clockwise outer contour in +Y-up coordinates, the left-hand normal
    # (-ty, tx) points outward from the filled black ink region.
    # For a counter-clockwise inner counter, (-ty, tx) points inward into the
    # hole (which also thickens the surrounding black stroke when grade_delta > 0).
    shifted_anchors: list[Point] = []
    for i, anchor in enumerate(anchors):
        prev_anchor = anchors[(i - 1) % n]
        prev_seg = contour.segments[(i - 1) % n]
        next_seg = contour.segments[i]

        t_in = _incoming_tangent(prev_anchor, prev_seg)
        t_out = _outgoing_tangent(anchor, next_seg)

        n_in = (-t_in[1], t_in[0])
        n_out = (-t_out[1], t_out[0])

        avg_nx = n_in[0] + n_out[0]
        avg_ny = n_in[1] + n_out[1]
        norm_len = math.hypot(avg_nx, avg_ny)
        if norm_len < 1e-6:
            nx, ny = n_out
        else:
            nx, ny = avg_nx / norm_len, avg_ny / norm_len

        # Angle cap clipping (Section 5C): clamp miter projection on sharp corners.
        dot = max(-1.0, min(1.0, t_in[0] * t_out[0] + t_in[1] * t_out[1]))
        turn_angle = math.pi - math.acos(dot)
        if turn_angle < _MIN_CORNER_ANGLE_RAD:
            miter_scale = 0.65
        else:
            half_sin = math.sin(0.5 * turn_angle)
            miter_scale = min(_MAX_MITER_SCALE, 1.0 / max(half_sin, 0.5))

        if category == "silhouette":
            # Category A: Asymmetric offset (+X horizontal, +0.5X vertical).
            dx = grade_delta * miter_scale * nx
            dy = 0.5 * grade_delta * miter_scale * ny
        elif category == "counter":
            # Category B: Suppress offset on internal counters so holes don't choke.
            dx = 0.35 * grade_delta * miter_scale * nx
            dy = 0.35 * grade_delta * miter_scale * ny
        else:
            # Category C: Minimal dilation + slight radial translation from center.
            radial_x, radial_y = _unit_vec(
                anchor[0] - glyph_center[0], anchor[1] - glyph_center[1]
            )
            dx = 0.25 * grade_delta * nx + 0.15 * grade_delta * radial_x
            dy = 0.25 * grade_delta * ny + 0.15 * grade_delta * radial_y

        shifted_anchors.append((anchor[0] + dx, anchor[1] + dy))

    # Rebuild segments with Handle Ratio Preservation (Section 5C).
    new_segments: list[CubicSegment] = []
    for i, seg in enumerate(contour.segments):
        p0_old = anchors[i]
        p1_old = anchors[(i + 1) % n]
        p0_new = shifted_anchors[i]
        p1_new = shifted_anchors[(i + 1) % n]

        if seg.kind == "line" or seg.c1 is None or seg.c2 is None:
            new_segments.append(CubicSegment("line", None, None, p1_new))
        else:
            old_chord = math.hypot(p1_old[0] - p0_old[0], p1_old[1] - p0_old[1])
            new_chord = math.hypot(p1_new[0] - p0_new[0], p1_new[1] - p0_new[1])
            if old_chord > 1e-4:
                ratio = max(0.5, min(1.5, new_chord / old_chord))
            else:
                ratio = 1.0

            c1_new = (
                p0_new[0] + (seg.c1[0] - p0_old[0]) * ratio,
                p0_new[1] + (seg.c1[1] - p0_old[1]) * ratio,
            )
            c2_new = (
                p1_new[0] + (seg.c2[0] - p1_old[0]) * ratio,
                p1_new[1] + (seg.c2[1] - p1_old[1]) * ratio,
            )
            new_segments.append(CubicSegment("curve", c1_new, c2_new, p1_new))

    return Contour(start=shifted_anchors[0], segments=tuple(new_segments))


def _draw_contours_to_layer(contours: list[Contour], layer: GSLayer) -> None:
    """Draws `contours` into `layer` via glyphsLib's SegmentPen."""
    pen = layer.getPen()
    for contour in contours:
        pen.moveTo((round(contour.start[0], 2), round(contour.start[1], 2)))
        for seg in contour.segments:
            end_pt = (round(seg.end[0], 2), round(seg.end[1], 2))
            if seg.kind == "line" or seg.c1 is None or seg.c2 is None:
                pen.lineTo(end_pt)
            else:
                c1_pt = (round(seg.c1[0], 2), round(seg.c1[1], 2))
                c2_pt = (round(seg.c2[0], 2), round(seg.c2[1], 2))
                pen.curveTo(c1_pt, c2_pt, end_pt)
        pen.closePath()


def _format_family_name(set_name: str) -> str:
    words = [w.capitalize() for w in re.split(r"[-_]+", set_name) if w]
    return f"Chess {' '.join(words)}"


def _find_piece_svg(set_dir: Path, stem: str) -> Path:
    for item in sorted(set_dir.iterdir()):
        if item.is_file() and item.suffix.lower() == ".svg" and item.stem.lower() == stem:
            return item
    raise FileNotFoundError(f"Missing SVG for piece {stem!r} in {set_dir}")


def build_source_for_set(set_dir: Path, out_path: Path) -> None:
    """Compiles all 12 piece SVGs in `set_dir` into a Glyphs 3 file at `out_path`."""
    set_name = set_dir.name
    if not _SAFE_NAME_RE.match(set_name):
        raise ValueError(f"Unsafe set name: {set_name!r}")

    font = GSFont()
    font.format_version = 3
    font.family_name = _format_family_name(set_name)
    font.units_per_em = _UPM

    grad_axis = GSAxis(name="Grade", axis_tag="GRAD", hidden=False)
    font.axes.append(grad_axis)

    for master_spec in _MASTERS:
        master = GSFontMaster()
        master.id = master_spec.master_id
        master.name = master_spec.name
        master.axes_values = [master_spec.grade_value]
        master.ascender = _ASCENDER
        master.descender = _DESCENDER
        master.cap_height = _CAP_HEIGHT
        master.x_height = _X_HEIGHT
        font.masters.append(master)

    # Always include .notdef as the first glyph with locked advance width.
    notdef = GSGlyph(".notdef")
    for master_spec in _MASTERS:
        layer = GSLayer()
        layer.layer_id = master_spec.master_id
        layer.associated_master_id = master_spec.master_id
        layer.width = _ADVANCE_WIDTH
        notdef.layers.append(layer)
    font.glyphs.append(notdef)

    glyph_center: Point = (_ADVANCE_WIDTH * 0.5, (_ASCENDER + _DESCENDER) * 0.5)

    for piece in _PIECES:
        svg_path = _find_piece_svg(set_dir, piece.stem)
        ink = _svg_to_ink_path(svg_path)
        raw_contours = _extract_cubic_contours(ink)
        classified = _normalize_and_classify_contours(raw_contours)

        glyph = GSGlyph(piece.glyph_name)
        glyph.unicode = f"{piece.codepoint:04X}"

        for master_spec in _MASTERS:
            layer = GSLayer()
            layer.layer_id = master_spec.master_id
            layer.associated_master_id = master_spec.master_id
            layer.width = _ADVANCE_WIDTH

            graded_contours = [
                _grade_contour(contour, category, master_spec.grade_delta, glyph_center)
                for contour, category in classified
            ]
            _draw_contours_to_layer(graded_contours, layer)
            glyph.layers.append(layer)

        font.glyphs.append(glyph)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(out_path))


def make_all_sources(
    src_root: Path,
    dest_dir: Path,
    selected_names: set[str] | None = None,
) -> None:
    if not src_root.exists():
        raise FileNotFoundError(
            f"Source directory {src_root} does not exist; run scripts/vendor_glyphs.py first."
        )

    set_dirs = [
        d
        for d in sorted(src_root.iterdir())
        if d.is_dir() and (selected_names is None or d.name in selected_names)
    ]
    if not set_dirs:
        raise ValueError(f"No matching SVG sets found in {src_root} for {selected_names!r}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    resolved_dest = dest_dir.resolve()

    for set_dir in set_dirs:
        if not _SAFE_NAME_RE.match(set_dir.name):
            raise ValueError(f"Unsafe set directory name: {set_dir.name!r}")
        out_path = (dest_dir / f"{set_dir.name}.glyphs").resolve()
        if resolved_dest not in out_path.parents:
            raise ValueError(f"Output path {out_path} escapes {dest_dir}")

        print(f"Building {out_path} from {set_dir}...")
        build_source_for_set(set_dir, out_path)
        print(f"  -> Wrote {out_path} ({len(_PIECES)} piece glyphs, {len(_MASTERS)} GRAD masters)")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        type=Path,
        default=repo_root / "third_party" / "glyphs",
        help="Input directory containing vendored SVG sets (default: third_party/glyphs)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=repo_root / "sources",
        help="Output directory for generated .glyphs files (default: sources)",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional subset of set names to build",
    )
    args = parser.parse_args()
    selected = set(args.only) if args.only else None
    make_all_sources(args.src, args.dest, selected)


if __name__ == "__main__":
    main()
