#!/usr/bin/env python3
"""Pre-generate all 1-2 letter initials PNGs for the BFC API.

Run once locally (requires Pillow), commit the resulting `initials/` directory.
The Docker image ships these static files — no runtime image generation.

Usage:
    pip install Pillow
    python scripts/generate_initials.py
"""
import os
import string
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.abspath(os.path.join(HERE, "..", "initials"))

SIZE = 256
BG = "#f0dd8a"
FG = "#191B1F"
FONT_SIZE = int(SIZE * 0.42)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError(
        "No suitable font found. Install DejaVu Sans Bold or edit FONT_CANDIDATES."
    )


def render(letters, font, out_path):
    img = Image.new("RGB", (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(img)

    # Measure actual glyph ink bounds (not font em-box, which pads with descender space)
    bbox = draw.textbbox((0, 0), letters, font=font, anchor="lt")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (SIZE - text_w) / 2 - bbox[0]
    y = (SIZE - text_h) / 2 - bbox[1]

    draw.text((x, y), letters, font=font, fill=FG, anchor="lt")
    img.save(out_path, "PNG", optimize=True)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    font_path = find_font()
    print(f"Using font: {font_path}")
    font = ImageFont.truetype(font_path, FONT_SIZE)

    count = 0
    # Single-letter (edge case: user with 1-letter first name)
    for c in string.ascii_uppercase:
        render(c, font, os.path.join(OUT_DIR, f"{c}.png"))
        count += 1
    # All 2-letter combos
    for c1 in string.ascii_uppercase:
        for c2 in string.ascii_uppercase:
            render(c1 + c2, font, os.path.join(OUT_DIR, f"{c1}{c2}.png"))
            count += 1

    print(f"Generated {count} PNG files in {OUT_DIR}")


if __name__ == "__main__":
    main()
