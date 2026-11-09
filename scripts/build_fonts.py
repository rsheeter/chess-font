#!/usr/bin/env python3
"""Downloads the latest googlefonts/fontc release binary and compiles sources/*.glyphs.

Caches the downloaded fontc binary under build/fontc/<tag_name>/ so subsequent
runs reuse the existing binary without hitting the network if already cached.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen
import zipfile


_FONTC_LATEST_RELEASE_URL = "https://api.github.com/repos/googlefonts/fontc/releases/latest"
_ALLOWED_DOWNLOAD_PREFIXES = (
    "https://api.github.com/repos/googlefonts/fontc/releases/assets/",
    "https://github.com/googlefonts/fontc/releases/download/",
)
_SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Maps (platform.system().lower(), normalized_machine) -> fontc release asset name.
_FONTC_ASSETS: dict[tuple[str, str], str] = {
    ("darwin", "arm64"): "fontc-aarch64-apple-darwin.tar.gz",
    ("darwin", "x86_64"): "fontc-x86_64-apple-darwin.tar.gz",
    ("linux", "arm64"): "fontc-aarch64-unknown-linux-gnu.tar.gz",
    ("linux", "x86_64"): "fontc-x86_64-unknown-linux-gnu.tar.gz",
    ("windows", "x86_64"): "fontc-x86_64-pc-windows-msvc.zip",
}


def _detect_asset_name() -> str:
    sys_name = platform.system().lower()
    machine_raw = platform.machine().lower()
    if machine_raw in ("arm64", "aarch64"):
        machine = "arm64"
    elif machine_raw in ("x86_64", "amd64"):
        machine = "x86_64"
    else:
        machine = machine_raw

    asset_name = _FONTC_ASSETS.get((sys_name, machine))
    if not asset_name:
        raise RuntimeError(
            f"Unsupported platform/architecture for prebuilt fontc: {sys_name}/{machine_raw}"
        )
    return asset_name


def _fetch_latest_release_metadata() -> dict:
    req = Request(
        _FONTC_LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "chess-font-builder",
        },
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_and_verify(url: str, expected_sha256: str | None, dest_file: Path) -> None:
    if not url.startswith(_ALLOWED_DOWNLOAD_PREFIXES):
        raise ValueError(f"Refusing to download from unexpected URL: {url!r}")

    req = Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "chess-font-builder",
        },
    )
    hasher = hashlib.sha256()
    with urlopen(req, timeout=120) as resp, dest_file.open("wb") as out:
        while chunk := resp.read(65536):
            out.write(chunk)
            hasher.update(chunk)

    actual_sha256 = hasher.hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(
            f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual_sha256}"
        )


def _extract_fontc_binary(archive_path: Path, target_bin: Path, temp_root: Path) -> None:
    exe_name = "fontc.exe" if platform.system().lower() == "windows" else "fontc"
    with tempfile.TemporaryDirectory(prefix="fontc_extract_", dir=temp_root) as tmp:
        extract_dir = Path(tmp)
        if archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(extract_dir, filter="data")
        elif archive_path.name.endswith(".zip"):
            resolved_extract = extract_dir.resolve()
            with zipfile.ZipFile(archive_path, "r") as zf:
                for member in zf.infolist():
                    dest = (extract_dir / member.filename).resolve()
                    if resolved_extract not in dest.parents and dest != resolved_extract:
                        raise ValueError(f"Unsafe zip member path: {member.filename!r}")
                zf.extractall(extract_dir)
        else:
            raise ValueError(f"Unsupported archive format: {archive_path.name!r}")

        matches = [p for p in extract_dir.rglob(exe_name) if p.is_file()]
        if not matches:
            raise FileNotFoundError(
                f"Could not find {exe_name!r} inside archive {archive_path.name}"
            )

        target_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(matches[0], target_bin)
        target_bin.chmod(target_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_latest_fontc(cache_root: Path) -> Path:
    """Returns path to the latest release `fontc` binary, downloading if needed."""
    cache_root.mkdir(parents=True, exist_ok=True)
    resolved_cache_root = cache_root.resolve()

    asset_name = _detect_asset_name()
    release = _fetch_latest_release_metadata()
    tag_name = release.get("tag_name", "")
    if not _SAFE_TAG_RE.match(tag_name):
        raise ValueError(f"Unsafe release tag_name: {tag_name!r}")

    exe_name = "fontc.exe" if platform.system().lower() == "windows" else "fontc"
    cached_bin = (resolved_cache_root / tag_name / exe_name).resolve()
    if resolved_cache_root not in cached_bin.parents:
        raise ValueError(f"Cache path {cached_bin} escapes {cache_root}")

    if cached_bin.is_file():
        print(f"Using cached fontc ({tag_name}): {cached_bin}")
        return cached_bin

    asset_info = next(
        (a for a in release.get("assets", []) if a.get("name") == asset_name),
        None,
    )
    if asset_info is None:
        raise RuntimeError(f"Asset {asset_name!r} not found in release {tag_name}")

    download_url = asset_info.get("url") or asset_info["browser_download_url"]
    digest = asset_info.get("digest", "")
    expected_sha256 = (
        digest.removeprefix("sha256:") if digest.startswith("sha256:") else None
    )

    print(f"Downloading {asset_name} ({tag_name}) from {download_url}...")
    with tempfile.TemporaryDirectory(prefix="fontc_dl_", dir=resolved_cache_root) as tmp:
        archive_path = Path(tmp) / asset_name
        _download_and_verify(download_url, expected_sha256, archive_path)
        _extract_fontc_binary(archive_path, cached_bin, resolved_cache_root)

    print(f"Installed fontc ({tag_name}) -> {cached_bin}")
    return cached_bin


def build_all_fonts(
    sources_dir: Path,
    dest_dir: Path,
    cache_dir: Path,
    fontc_bin: Path | None = None,
    selected_names: set[str] | None = None,
) -> None:
    if not sources_dir.exists():
        raise FileNotFoundError(
            f"Sources directory {sources_dir} does not exist; run scripts/make_source.py first."
        )

    glyphs_files = [
        p
        for p in sorted(sources_dir.iterdir())
        if p.is_file()
        and p.suffix == ".glyphs"
        and (selected_names is None or p.stem in selected_names)
    ]
    if not glyphs_files:
        raise ValueError(
            f"No matching .glyphs sources found in {sources_dir} for {selected_names!r}"
        )

    resolved_fontc = fontc_bin.resolve() if fontc_bin else ensure_latest_fontc(cache_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    resolved_dest = dest_dir.resolve()

    for glyphs_path in glyphs_files:
        set_name = glyphs_path.stem
        if not _SAFE_NAME_RE.match(set_name):
            raise ValueError(f"Unsafe source stem: {set_name!r}")

        out_ttf = (dest_dir / f"{set_name}.ttf").resolve()
        build_work_dir = (cache_dir / "work" / set_name).resolve()
        if resolved_dest not in out_ttf.parents:
            raise ValueError(f"Output path {out_ttf} escapes {dest_dir}")
        if cache_dir.resolve() not in build_work_dir.parents:
            raise ValueError(f"Work dir {build_work_dir} escapes {cache_dir}")

        build_work_dir.mkdir(parents=True, exist_ok=True)
        print(f"Compiling {glyphs_path} -> {out_ttf} with fontc...")
        subprocess.run(
            [
                str(resolved_fontc),
                str(glyphs_path),
                "--build-dir",
                str(build_work_dir),
                "--output-file",
                str(out_ttf),
            ],
            check=True,
        )
        print(f"  -> Built {out_ttf} ({out_ttf.stat().st_size:,} bytes)")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        type=Path,
        default=repo_root / "sources",
        help="Input directory containing .glyphs source files (default: sources)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=repo_root / "build" / "fonts",
        help="Output directory for compiled .ttf files (default: build/fonts)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=repo_root / "build" / "fontc",
        help="Cache directory for downloaded fontc binaries (default: build/fontc)",
    )
    parser.add_argument(
        "--fontc",
        type=Path,
        default=None,
        help="Optional path to a local fontc binary (skips GitHub release download)",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional subset of set names to compile",
    )
    args = parser.parse_args()
    selected = set(args.only) if args.only else None
    build_all_fonts(args.src, args.dest, args.cache_dir, args.fontc, selected)


if __name__ == "__main__":
    main()
