#!/usr/bin/env python3
"""Vendors upstream chess piece vector/font assets into third_party/glyphs/.

Uses shallow blob-filtered git sparse-checkouts at pinned commit SHAs so even
massive repositories (like lichess-org/lila) download in a couple of seconds.
"""

import argparse
from collections import defaultdict
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import NamedTuple


class GlyphSource(NamedTuple):
    """Configuration for a single vendored glyph asset set."""

    name: str
    repo_url: str
    commit: str
    paths: tuple[str, ...]
    author: str
    license_name: str
    license_url: str


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Central manifest of upstream glyph sources to vendor into third_party/glyphs/<name>.
_GLYPH_SOURCES: tuple[GlyphSource, ...] = (
    # --- Included Sources ---
    GlyphSource(
        name="cburnett",
        repo_url="https://github.com/lichess-org/lila.git",
        commit="a1590345c9c3a31b6f9c6705eefeeb7dab32a78e",
        paths=("public/piece/cburnett",),
        author="Colin M.L. Burnett",
        license_name="CC BY-SA 3.0 / GPLv2+ (dual-licensed; BSD/GFDL/CC-BY-SA on Wikimedia)",
        license_url="https://github.com/lichess-org/lila/blob/a1590345c9c3a31b6f9c6705eefeeb7dab32a78e/COPYING.md",
    ),
    GlyphSource(
        name="kmar-livius",
        repo_url="https://github.com/kmar/chess_svg_piece_sets.git",
        commit="af40ea51e87eddee1ae7ee35ae312893a1271233",
        paths=("livius",),
        author="Martin Sedlák (kmar)",
        license_name="CC0 1.0 / Public Domain",
        license_url="https://github.com/kmar/chess_svg_piece_sets/blob/af40ea51e87eddee1ae7ee35ae312893a1271233/livius/LICENSE",
    ),
    GlyphSource(
        name="kmar-meridian",
        repo_url="https://github.com/kmar/chess_svg_piece_sets.git",
        commit="af40ea51e87eddee1ae7ee35ae312893a1271233",
        paths=("meridian",),
        author="Martin Sedlák (kmar)",
        license_name="CC0 1.0 / Public Domain",
        license_url="https://github.com/kmar/chess_svg_piece_sets/blob/af40ea51e87eddee1ae7ee35ae312893a1271233/meridian/LICENSE",
    ),
    GlyphSource(
        name="lichess-merida",
        repo_url="https://github.com/lichess-org/lila.git",
        commit="a1590345c9c3a31b6f9c6705eefeeb7dab32a78e",
        paths=("public/piece/merida",),
        author="Armando Hernandez Marroquin (vectorized by Lichess)",
        license_name="GPLv2+",
        license_url="https://github.com/lichess-org/lila/blob/a1590345c9c3a31b6f9c6705eefeeb7dab32a78e/COPYING.md",
    ),
    # --- Excluded Sources (intentionally not vendored) ---
    #
    # * kmar/chess_svg_piece_sets ("meridian_shaded"):
    #   Identical geometry to kmar-meridian, but adds SVG <linearGradient> fills
    #   that cannot be represented in monochrome outline font tables (glyf/CFF).
    #
    # * joshwalters/open-chess-font:
    #   Output glyphs (output_svg_tiles/) are degraded potrace bitmap auto-traces
    #   of Cburnett (vector -> 2000x2000 PNG -> potrace). Input tiles are just
    #   Cburnett SVGs modified with a 5px white outline stroke. Superseded by
    #   clean "cburnett" vectors above.
    #
    # * samboy/OpenChessFontFairy:
    #   FontForge .sfd derived directly from open-chess-font's potrace-traced
    #   outlines, plus rotated Bishop/Knight glyphs and a Wikimedia compound
    #   rook+knight glyph mapped to non-Unicode ASCII slots.
    #
    # * vasiliyaltunin/chess-merida-font & xeyownt/chess_merida_unicode:
    #   Binary .ttf / webfont distributions of the 1998 Chess Merida font.
    #   Excluded because "lichess-merida" already provides clean standalone SVG
    #   vectors for the Merida piece set.
    #
    # * greenchess.net:
    #   Distributed as unversioned web zip downloads rather than a Git repository,
    #   and its standard piece set duplicates Cburnett.
    #
    # * lichess-org/lila non-commercial / no-derivatives / freeware sets
    #   (e.g. alpha, californian, cardinal, chess7, companion, dubrovny, fresca,
    #   horsey, icpieces, leipzig, maestro, shahi-ivory-brown, staunty, tatiana):
    #   Excluded due to CC BY-NC-SA, non-derivative, or personal-use-only licenses
    #   documented in lila's COPYING.md.
)


def _validate_source(source: GlyphSource) -> None:
    if not _SAFE_NAME_RE.match(source.name):
        raise ValueError(f"Unsafe target directory name: {source.name!r}")
    if not source.repo_url.startswith("https://"):
        raise ValueError(f"Only https:// repo URLs are allowed: {source.repo_url!r}")
    if not _COMMIT_RE.match(source.commit):
        raise ValueError(f"Expected 40-char hex commit SHA, got: {source.commit!r}")
    for rel_path in source.paths:
        p = Path(rel_path)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"Unsafe repo-relative path: {rel_path!r}")


def _sparse_checkout(
    repo_url: str,
    commit: str,
    paths: list[str],
    checkout_dir: Path,
) -> None:
    """Fetches only the requested paths at the pinned commit into checkout_dir."""
    checkout_dir.mkdir(parents=True, exist_ok=True)
    run_git = lambda *args: subprocess.run(
        ["git", "-C", str(checkout_dir), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    run_git("init", "--quiet")
    run_git("remote", "add", "origin", repo_url)
    # Use --no-cone so both directory paths and individual file paths work.
    run_git("sparse-checkout", "init", "--no-cone")
    run_git("sparse-checkout", "set", "--", *paths)
    run_git("fetch", "--quiet", "--depth", "1", "--filter=blob:none", "origin", commit)
    run_git("checkout", "--quiet", "FETCH_HEAD")


def _export_source(
    source: GlyphSource,
    checkout_dir: Path,
    dest_root: Path,
) -> None:
    """Copies only .svg files for a single GlyphSource into dest_root/<source.name>."""
    dest_dir = (dest_root / source.name).resolve()
    if dest_root.resolve() not in dest_dir.parents:
        raise ValueError(f"Destination {dest_dir} escapes {dest_root}")

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for rel_path in source.paths:
        src_path = (checkout_dir / rel_path).resolve()
        if checkout_dir.resolve() not in src_path.parents:
            raise ValueError(f"Source path {src_path} escapes {checkout_dir}")
        if not src_path.exists():
            raise FileNotFoundError(
                f"Path {rel_path!r} not found in {source.repo_url}@{source.commit}"
            )

        if src_path.is_dir():
            # Flatten directory contents directly into dest_dir, keeping only SVGs.
            for item in sorted(src_path.iterdir()):
                if item.is_file() and item.suffix.lower() == ".svg":
                    shutil.copy2(item, dest_dir / item.name)
        elif src_path.suffix.lower() == ".svg":
            shutil.copy2(src_path, dest_dir / src_path.name)


def _write_third_party_readme(dest_root: Path) -> None:
    """Writes third_party/README.md documenting provenance and licensing."""
    third_party_dir = dest_root.parent
    readme_path = third_party_dir / "README.md"

    lines = [
        "# Third-Party Chess Glyph Assets",
        "",
        "All files under `third_party/glyphs/` are vendored SVG assets obtained by running:",
        "",
        "```bash",
        "python3 scripts/vendor_glyphs.py",
        "```",
        "",
        "Do not edit the vendored `.svg` files manually; update `_GLYPH_SOURCES` in",
        "[`scripts/vendor_glyphs.py`](../scripts/vendor_glyphs.py) and re-run the script.",
        "",
        "## Directory Licenses & Provenance",
        "",
        "| Directory | Author | License | Upstream Source & Pinned Commit |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for src in _GLYPH_SOURCES:
        repo_web = src.repo_url.removesuffix(".git")
        source_path = src.paths[0]
        tree_url = f"{repo_web}/tree/{src.commit}/{source_path}"
        short_sha = src.commit[:12]
        lines.append(
            f"| [`glyphs/{src.name}`](glyphs/{src.name}) "
            f"| {src.author} "
            f"| [{src.license_name}]({src.license_url}) "
            f"| [`{source_path}` @ `{short_sha}`]({tree_url}) |"
        )

    lines.append("")
    readme_path.write_text("\n".join(lines), encoding="utf-8")


def vendor_all(dest_root: Path, selected_names: set[str] | None = None) -> None:
    sources = [
        s
        for s in _GLYPH_SOURCES
        if selected_names is None or s.name in selected_names
    ]
    if not sources:
        raise ValueError(f"No matching glyph sources found for {selected_names!r}")

    for source in sources:
        _validate_source(source)

    # Remove any stale subdirectories in dest_root when running a full vendor pass.
    if selected_names is None and dest_root.exists():
        expected_names = {s.name for s in sources}
        for existing in dest_root.iterdir():
            if existing.is_dir() and existing.name not in expected_names:
                shutil.rmtree(existing)

    # Group by (repo_url, commit) so shared repos are fetched only once.
    grouped: dict[tuple[str, str], list[GlyphSource]] = defaultdict(list)
    for source in sources:
        grouped[(source.repo_url, source.commit)].append(source)

    dest_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="chess_font_vendor_") as tmp:
        tmp_root = Path(tmp)
        for idx, ((repo_url, commit), repo_sources) in enumerate(grouped.items()):
            combined_paths = sorted(
                {path for src in repo_sources for path in src.paths}
            )
            checkout_dir = tmp_root / f"repo_{idx}"
            print(f"Fetching {repo_url} @ {commit[:12]} ({len(combined_paths)} paths)...")
            _sparse_checkout(repo_url, commit, combined_paths, checkout_dir)

            for source in repo_sources:
                _export_source(source, checkout_dir, dest_root)
                exported_count = len(list((dest_root / source.name).iterdir()))
                print(
                    f"  -> {dest_root / source.name} ({exported_count} SVGs, {source.license_name})"
                )

    _write_third_party_readme(dest_root)
    print(f"Wrote {dest_root.parent / 'README.md'}")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=repo_root / "third_party" / "glyphs",
        help="Destination directory for vendored glyph sets (default: third_party/glyphs)",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional subset of source names to vendor",
    )
    args = parser.parse_args()
    selected = set(args.only) if args.only else None
    vendor_all(args.dest, selected)


if __name__ == "__main__":
    main()
