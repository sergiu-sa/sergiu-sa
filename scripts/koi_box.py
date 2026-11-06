"""Bake a DevTools box-model highlight around the nightly koi GIF.

    python scripts/koi_box.py <koi.gif> <output dir>

Writes koi-dark.gif and koi-light.gif. GIF pixels are either opaque or fully transparent, so the translucent overlay is flattened onto GitHub's page colour, once per theme.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

SCALE = 2  # git-koi draws at twice its pixel size, so the box matches.
MARGIN, BORDER, PADDING, CONTENT = (n * SCALE for n in (24, 1, 16, 256))
INSET = MARGIN + BORDER + PADDING
SIZE = CONTENT + 2 * INSET

# GitHub's page colour in each theme.
PAGES = {"dark": (13, 17, 23), "light": (255, 255, 255)}

# Chrome's own highlight colours, at the opacities used in the header SVG.
MARGIN_TINT = (246, 178, 107, 41)
HATCH = (246, 178, 107, 179)
BORDER_LINE = (255, 229, 153, 230)
PADDING_TINT = (147, 196, 125, 77)
CONTENT_TINT = (111, 168, 220, 51)


def ring_mask(outer, inner=None):
    mask = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((outer, outer, SIZE - 1 - outer, SIZE - 1 - outer), fill=255)
    if inner is not None:
        draw.rectangle((inner, inner, SIZE - 1 - inner, SIZE - 1 - inner), fill=0)
    return mask


def tint(base, colour, mask):
    layer = Image.new("RGBA", (SIZE, SIZE), colour)
    layer.putalpha(Image.eval(mask, lambda m: m * colour[3] // 255))
    base.alpha_composite(layer)


def backdrop(page):
    base = Image.new("RGBA", (SIZE, SIZE), page + (255,))
    margin = ring_mask(0, MARGIN)
    tint(base, MARGIN_TINT, margin)

    hatch = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(hatch)
    step = round(7 * 1.414 * SCALE)  # the SVG pattern is 7 px wide, rotated 45 degrees
    for offset in range(-SIZE, SIZE, step):
        draw.line((offset, SIZE, offset + SIZE, 0), fill=HATCH, width=2 * SCALE)
    clipped = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    clipped.paste(hatch, (0, 0), margin)
    base.alpha_composite(clipped)

    tint(base, PADDING_TINT, ring_mask(MARGIN + BORDER, INSET))
    tint(base, CONTENT_TINT, ring_mask(INSET))
    draw = ImageDraw.Draw(base)
    draw.rectangle((MARGIN, MARGIN, SIZE - 1 - MARGIN, SIZE - 1 - MARGIN), outline=BORDER_LINE, width=BORDER)
    return base


def bake(koi_path, out_dir):
    koi = Image.open(koi_path)
    if koi.size != (CONTENT, CONTENT):
        sys.exit(f"expected a {CONTENT}x{CONTENT} koi, got {koi.size[0]}x{koi.size[1]}")
    # Pillow hands back each frame already composited, so frames can be pasted whole.
    frames = [(frame.convert("RGBA"), frame.info.get("duration", 67)) for frame in ImageSequence.Iterator(koi)]

    for name, page in PAGES.items():
        base = backdrop(page)
        rgb = []
        for frame, _ in frames:
            canvas = base.copy()
            canvas.alpha_composite(frame, (INSET, INSET))
            rgb.append(canvas.convert("RGB"))
        # One shared palette keeps colours from flickering between frames.
        palette = rgb[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        out = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in rgb]
        out[0].save(
            out_dir / f"koi-{name}.gif",
            save_all=True,
            append_images=out[1:],
            duration=[d for _, d in frames],
            loop=0,
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    bake(Path(sys.argv[1]), out_dir)
