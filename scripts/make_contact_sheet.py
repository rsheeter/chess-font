#!/usr/bin/env python3
"""Render a transparent-background Grade (GRAD) contact sheet SVG from sources/*.glyphs."""

from __future__ import annotations

import argparse
import html
from pathlib import Path
import subprocess

import glyphsLib


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "sources"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "grade-contact-sheet.svg"

BASE_GLYPHS: tuple[tuple[str, str], ...] = (
    ("uni2654", "2654 ♔"),
    ("uni2655", "2655 ♕"),
    ("uni2656", "2656 ♖"),
    ("uni2657", "2657 ♗"),
    ("uni2658", "2658 ♘"),
    ("uni2659", "2659 ♙"),
    ("uni265A", "265A ♚"),
    ("uni265B", "265B ♛"),
    ("uni265C", "265C ♜"),
    ("uni265D", "265D ♝"),
    ("uni265E", "265E ♞"),
    ("uni265F", "265F ♟"),
)


def _layer_to_svg_d(layer: glyphsLib.classes.GSLayer) -> str:
    """Convert a GSLayer's cubic/line contours into an SVG path data string."""
    parts: list[str] = []
    for path in layer.paths:
        nodes = list(path.nodes)
        if not nodes:
            continue
        on_indices = [i for i, n in enumerate(nodes) if n.type != "offcurve"]
        if not on_indices:
            continue
        start = on_indices[0]
        ordered = nodes[start:] + nodes[:start]
        parts.append(f"M {ordered[0].position.x:.1f} {ordered[0].position.y:.1f}")
        i = 1
        n_len = len(ordered)
        while i < n_len:
            node = ordered[i]
            if node.type == "offcurve":
                c1 = node.position
                c2 = ordered[i + 1].position
                end = ordered[(i + 2) % n_len].position
                parts.append(
                    f"C {c1.x:.1f} {c1.y:.1f} {c2.x:.1f} {c2.y:.1f} {end.x:.1f} {end.y:.1f}"
                )
                i += 3
            else:
                p = node.position
                parts.append(f"L {p.x:.1f} {p.y:.1f}")
                i += 1
        parts.append("Z")
    return " ".join(parts)


def generate_contact_sheet_svg(sources_dir: Path) -> str:
    """Build the SVG contact sheet string across all .glyphs sources and GRAD masters."""
    glyphs_files = sorted(sources_dir.glob("*.glyphs"))
    if not glyphs_files:
        raise FileNotFoundError(f"No .glyphs files found in {sources_dir}")

    col_w = 85
    row_h = 92
    left_margin = 185
    top_margin = 52
    set_gap = 12

    num_sets = len(glyphs_files)
    total_rows = num_sets * 3
    width = left_margin + len(BASE_GLYPHS) * col_w + 15
    height = top_margin + total_rows * row_h + (num_sets - 1) * set_gap + 12

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        "  <style>",
        "    :root {",
        "      color-scheme: light dark;",
        "      color: #1f2328;",
        "    }",
        "    @media (prefers-color-scheme: dark) {",
        "      :root {",
        "        color: #e6edf3;",
        "      }",
        "    }",
        "    .label {",
        "      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;",
        "      fill: currentColor;",
        "    }",
        "    .label-muted {",
        "      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;",
        "      fill: currentColor;",
        "      fill-opacity: 0.72;",
        "    }",
        "    .piece {",
        "      fill: currentColor;",
        "    }",
        "    .divider {",
        "      stroke: currentColor;",
        "      stroke-opacity: 0.22;",
        "      stroke-width: 1;",
        "    }",
        "  </style>",
    ]

    for col_idx, (_, col_label) in enumerate(BASE_GLYPHS):
        cx = left_margin + col_idx * col_w + col_w * 0.42
        escaped_label = html.escape(col_label, quote=True)
        lines.append(
            f'  <text x="{cx:.1f}" y="30" text-anchor="middle" font-size="13" font-weight="bold" class="label">{escaped_label}</text>'
        )

    y_cursor = top_margin
    for glyphs_path in glyphs_files:
        set_name = html.escape(glyphs_path.stem, quote=True)
        font = glyphsLib.GSFont(str(glyphs_path))
        lines.append(
            f'  <line x1="12" y1="{y_cursor - 8}" x2="{width - 12}" y2="{y_cursor - 8}" class="divider"/>'
        )
        for master in font.masters:
            grad_val = int(round(master.axes[0])) if master.axes else 400
            lines.append(
                f'  <text x="14" y="{y_cursor + 44}" font-size="13" font-weight="bold" class="label">{set_name}</text>'
            )
            lines.append(
                f'  <text x="14" y="{y_cursor + 62}" font-size="12" class="label-muted">GRAD {grad_val}</text>'
            )
            for col_idx, (glyph_name, _) in enumerate(BASE_GLYPHS):
                glyph = font.glyphs[glyph_name]
                layer = glyph.layers[master.id]
                d = _layer_to_svg_d(layer)
                gx = left_margin + col_idx * col_w
                gy = y_cursor + 74
                lines.append(
                    f'  <g transform="translate({gx}, {gy}) scale(0.072, -0.072)">'
                    f'<path d="{d}" class="piece"/>'
                    f"</g>"
                )
            y_cursor += row_h
        y_cursor += set_gap

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a transparent-background Grade (GRAD) contact sheet SVG."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination SVG path (default: docs/grade-contact-sheet.svg).",
    )
    parser.add_argument(
        "--png",
        action="store_true",
        help="Also rasterize a PNG preview next to the SVG via macOS qlmanage.",
    )
    args = parser.parse_args()

    out_path = args.output.resolve()
    repo_root = REPO_ROOT.resolve()
    if not out_path.is_relative_to(repo_root):
        raise ValueError(f"Output path {out_path} must be inside {repo_root}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    svg_text = generate_contact_sheet_svg(SOURCES_DIR)
    out_path.write_text(svg_text, encoding="utf-8")
    print(f"Wrote {out_path.relative_to(repo_root)}")

    if args.png:
        subprocess.run(
            ["qlmanage", "-t", "-s", "2400", "-o", str(out_path.parent), str(out_path)],
            check=True,
        )
        print(f"Wrote {out_path.name}.png")


if __name__ == "__main__":
    main()
