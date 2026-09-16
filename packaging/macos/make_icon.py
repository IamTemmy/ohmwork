"""Generates the source artwork for Ohmwork.app's icon (a 1024x1024 PNG).
Not part of the ohmwork package — a one-off build tool, run via
build_app.sh, not something the project depends on at runtime. Needs
Pillow, which isn't (and shouldn't become) a project dependency; install it
somewhere separate from the project's own .venv, e.g.:

    python3 -m pip install --user pillow
"""

import sys

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024


def main(out_path: str) -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Full-bleed square background -- macOS applies its own rounded-squircle
    # mask and drop shadow automatically (since Big Sur), so icon artwork
    # should fill the whole canvas edge-to-edge rather than pre-rounding.
    draw.rectangle([0, 0, SIZE, SIZE], fill=(17, 18, 23, 255))

    # Subtle accent ring, inset enough to survive the OS's own mask/shadow.
    draw.rounded_rectangle(
        [70, 70, SIZE - 70, SIZE - 70], radius=170, outline=(90, 130, 255, 70), width=12
    )

    # Ohm symbol, centered.
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 600)
    text = "Ω"
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - w) / 2 - bbox[0]
    y = (SIZE - h) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=(120, 160, 255, 255))

    img.save(out_path)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png")
