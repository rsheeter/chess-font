# Third-Party Chess Glyph Assets

All files under `third_party/glyphs/` are vendored SVG assets obtained by running:

```bash
python3 scripts/vendor_glyphs.py
```

Do not edit the vendored `.svg` files manually; update `_GLYPH_SOURCES` in
[`scripts/vendor_glyphs.py`](../scripts/vendor_glyphs.py) and re-run the script.

## Directory Licenses & Provenance

| Directory | Author | License | Upstream Source & Pinned Commit |
| :--- | :--- | :--- | :--- |
| [`glyphs/cburnett`](glyphs/cburnett) | Colin M.L. Burnett | [CC BY-SA 3.0 / GPLv2+ (dual-licensed; BSD/GFDL/CC-BY-SA on Wikimedia)](https://github.com/lichess-org/lila/blob/a1590345c9c3a31b6f9c6705eefeeb7dab32a78e/COPYING.md) | [`public/piece/cburnett` @ `a1590345c9c3`](https://github.com/lichess-org/lila/tree/a1590345c9c3a31b6f9c6705eefeeb7dab32a78e/public/piece/cburnett) |
| [`glyphs/kmar-livius`](glyphs/kmar-livius) | Martin Sedlák (kmar) | [CC0 1.0 / Public Domain](https://github.com/kmar/chess_svg_piece_sets/blob/af40ea51e87eddee1ae7ee35ae312893a1271233/livius/LICENSE) | [`livius` @ `af40ea51e87e`](https://github.com/kmar/chess_svg_piece_sets/tree/af40ea51e87eddee1ae7ee35ae312893a1271233/livius) |
| [`glyphs/kmar-meridian`](glyphs/kmar-meridian) | Martin Sedlák (kmar) | [CC0 1.0 / Public Domain](https://github.com/kmar/chess_svg_piece_sets/blob/af40ea51e87eddee1ae7ee35ae312893a1271233/meridian/LICENSE) | [`meridian` @ `af40ea51e87e`](https://github.com/kmar/chess_svg_piece_sets/tree/af40ea51e87eddee1ae7ee35ae312893a1271233/meridian) |
| [`glyphs/lichess-merida`](glyphs/lichess-merida) | Armando Hernandez Marroquin (vectorized by Lichess) | [GPLv2+](https://github.com/lichess-org/lila/blob/a1590345c9c3a31b6f9c6705eefeeb7dab32a78e/COPYING.md) | [`public/piece/merida` @ `a1590345c9c3`](https://github.com/lichess-org/lila/tree/a1590345c9c3a31b6f9c6705eefeeb7dab32a78e/public/piece/merida) |
