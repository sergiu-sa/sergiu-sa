"""Draw the koi's tile, its colour key and the scale band for the profile README.

    python scripts/koi_card.py <koi.gif> <snapshot.json> <output dir>

Writes koi-{dark,light}.gif, key-{dark,light}.svg and scales-{dark,light}.svg.
The key and the scales read the same snapshot git-koi paints the koi from, so the
colours on the page always match the fish.
"""

import json
import os
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageColor, ImageDraw, ImageSequence

NATIVE = 256  # git-koi's canvas in koi pixels; its GIF is drawn at twice that.
SCALE = 3  # shown at half size in the README, so the 1.5x tile stays sharp on 2x screens
TILE = NATIVE * SCALE
RADIUS = 12

THEMES = {
    "dark": {"page": (13, 17, 23), "pond": (33, 45, 60), "card": "#151b23", "line": "#3d444d", "ink": "#f0f6fc", "mute": "#9198a1", "scale": "#11161d", "net": "#2d3440"},
    "light": {"page": (255, 255, 255), "pond": (230, 236, 242), "card": "#f6f8fa", "line": "#d1d9e0", "ink": "#1f2328", "mute": "#59636e", "scale": "#eef1f4", "net": "#d8dee4"},
}

# git-koi's colour ramps (src/coat.rs), named for the key: colour name, then shades.
RAMPS = {
    "red": ("red", ["#e43b44", "#f0604f", "#f6757a"]),
    "black": ("black", ["#181425", "#262b44", "#3a4466"]),
    "yellow": ("yellow", ["#d77643", "#feae34", "#fee761"]),
    "orange": ("orange", ["#be4a2f", "#f77622", "#feae34"]),
    "blue": ("blue", ["#3a4466", "#124e89", "#0099db"]),
    "white": ("white", ["#8b9bb4", "#c0cbdc", "#ffffff"]),
    "bright_yellow": ("yellow", ["#feae34", "#fee761", "#fff3b0"]),
    "sky": ("sky blue", ["#124e89", "#0099db", "#2ce8f5"]),
    "rust": ("rust", ["#733e39", "#be4a2f", "#d77643"]),
    "umber": ("umber", ["#181425", "#3e2731", "#733e39"]),
    "sand": ("sand", ["#b86f50", "#e4a672", "#ead4aa"]),
    "clay": ("clay", ["#be4a2f", "#d77643", "#e4a672"]),
    "slate": ("slate", ["#262b44", "#3a4466", "#5a6988"]),
    "metal_red": ("red", ["#f77622", "#feae34", "#ffffff"]),
    "bronze": ("bronze", ["#733e39", "#a06a3a", "#c99a5a"]),
    "platinum": ("platinum", ["#c0cbdc", "#f4f7fb", "#ffffff"]),
    "metal_orange": ("orange", ["#f77622", "#feae34", "#ffffff"]),
    "steel": ("steel", ["#3a4466", "#5a6988", "#c0cbdc"]),
    "gold": ("gold", ["#feae34", "#fee761", "#ffffff"]),
    "copper": ("copper", ["#b86f50", "#e4a672", "#ffffff"]),
    "metal_blue": ("blue", ["#0099db", "#8b9bb4", "#ffffff"]),
    "streak_gold": ("gold", ["#f77622", "#feae34", "#fee761"]),
}
# git-koi breaks equal shares in this order.
TIE_ORDER = ["red", "black", "yellow", "orange", "blue"]


def ramp_for(body, pigment):
    """git-koi's select_pigment_ramp: each body redraws a pigment, swapping any that would vanish."""
    special = {
        ("black", "black"): "white", ("asagi", "blue"): "white",
        ("black", "yellow"): "bright_yellow", ("asagi", "yellow"): "bright_yellow", ("black", "blue"): "sky",
        ("tea", "red"): "rust", ("tea", "black"): "umber", ("tea", "yellow"): "sand", ("tea", "orange"): "clay", ("tea", "blue"): "slate",
        ("gold", "red"): "metal_red", ("gold", "black"): "bronze", ("gold", "yellow"): "platinum",
        ("platinum", "red"): "metal_orange", ("platinum", "black"): "steel", ("platinum", "yellow"): "gold",
        ("gold", "orange"): "copper", ("platinum", "orange"): "copper", ("gold", "blue"): "metal_blue", ("platinum", "blue"): "metal_blue",
    }
    return RAMPS[special.get((body, pigment), pigment)]


def streak_ramp(body):
    return RAMPS["red"] if body in ("asagi", "gold") else RAMPS["streak_gold"]


def pigment_of(hex_color):
    """git-koi's own rule (select_pigment in src/coat.rs): nearest hue, greys become black."""
    if not hex_color:
        return "black"
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hi, lo = max(r, g, b), min(r, g, b)
    chroma, lightness = hi - lo, (hi + lo) / 2
    if chroma < 0.12 or chroma / (1 - abs(2 * lightness - 1)) < 0.2:
        return "black"
    if hi == r:
        hue = 60 * (((g - b) / chroma) % 6)
    elif hi == g:
        hue = 60 * ((b - r) / chroma + 2)
    else:
        hue = 60 * ((r - g) / chroma + 4)
    if not 18 <= hue < 330:
        return "red"
    if hue < 45:
        return "orange"
    if hue < 160:
        return "yellow"
    return "blue"


def pigment_rows(snapshot):
    """Each public, non-fork repo with a language is one vote, the way git-koi counts."""
    languages = {}
    for repo in snapshot["repositories"]:
        if repo["visibility"] == "public" and not repo["is_fork"] and repo.get("primary_language"):
            languages[repo["repository_id"]] = repo["primary_language"]
    counts = Counter(languages.values())
    colors = snapshot.get("language_colors") or {}
    grouped = {}
    for language, votes in counts.most_common():
        grouped.setdefault(pigment_of(colors.get(language)), []).append((language, votes))
    rows = sorted(grouped.items(), key=lambda item: (-sum(v for _, v in item[1]), TIE_ORDER.index(item[0])))
    return rows, sum(counts.values()), colors


def current_streak(snapshot):
    """Monday-to-Sunday weeks with any activity; the week in progress can't end a streak."""
    history = snapshot.get("contribution_history")
    if not history or not history["days"]:
        return 0
    active = set()
    for day in history["days"]:
        if day["contribution_count"] > 0:
            d = date.fromisoformat(day["date"])
            active.add(d - timedelta(days=d.weekday()))
    observed = date.fromisoformat(history["observed_on"])
    week = observed - timedelta(days=observed.weekday())
    if week not in active:
        week -= timedelta(weeks=1)
    weeks = 0
    while week in active:
        weeks += 1
        week -= timedelta(weeks=1)
    return weeks


def what_it_paints(rank, pigment, top, colour):
    # The top pigment sets the pattern, the second adds sides or spots, the third tints the fins.
    if rank == 0:
        return {"blue": f"the netted {colour} back", "red": f"the {colour} plates", "black": f"the {colour} markings"}.get(pigment, f"the netted {colour} coat")
    if rank == 1:
        sides = top == "blue" and pigment in ("red", "orange", "yellow")
        return f"the {colour} {'sides' if sides else 'spots'}"
    return f"the {colour} at the fin roots"


def key_svg(rows, total, colors, streak, body, theme):
    t = THEMES[theme]
    font = 'font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans, Helvetica, Arial, sans-serif"'
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 384" width="400" height="384" role="img" aria-labelledby="t">',
        '<title id="t">Colour key: each language I write and the colour it paints on the koi</title>',
        f'<rect x="0.5" y="0.5" width="399" height="383" rx="6" fill="{t["card"]}" stroke="{t["line"]}"/>',
        f'<text x="24" y="44" {font} font-size="17" font-weight="600" fill="{t["ink"]}">Painted with my languages</text>',
        f'<text x="24" y="67" {font} font-size="13" fill="{t["mute"]}">Every colour on this koi comes from a language I write.</text>',
    ]
    entries = []
    top = rows[0][0] if rows else None
    for rank, (pigment, languages) in enumerate(rows[:3]):
        names = languages[0][0] + (f" +{len(languages) - 1}" if len(languages) > 1 else "")
        share = 100 * sum(v for _, v in languages) / total
        colour, swatch = ramp_for(body, pigment)
        entries.append((colors.get(languages[0][0]) or "#8b949e", names, f"{share:.0f}%", swatch, what_it_paints(rank, pigment, top, colour)))
    if streak:
        colour, swatch = streak_ramp(body)
        entries.append((None, f"{streak}-week streak", "", swatch, f"the {colour} on its fin tips"))
    for i, (dot, name, share, swatch, paints) in enumerate(entries):
        y = 120 + i * 62
        if i:
            parts.append(f'<line x1="24" y1="{y - 31}" x2="376" y2="{y - 31}" stroke="{t["line"]}"/>')
        if dot:
            parts.append(f'<circle cx="30" cy="{y}" r="6" fill="{dot}"/>')
        else:
            parts.append(f'<path d="M30 {y - 7} l2 5 5 .5 -4 3.5 1.3 5 -4.3 -2.7 -4.3 2.7 1.3 -5 -4 -3.5 5 -.5 Z" fill="#feae34"/>')
        parts.append(f'<text x="46" y="{y + 5}" {font} font-size="14" font-weight="600" fill="{t["ink"]}">{escape(name[:16])}</text>')
        if share:
            parts.append(f'<text x="150" y="{y + 5}" {font} font-size="14" fill="{t["mute"]}">{share}</text>')
        # The two lit shades; a ramp's darkest step is shadow and reads as grey on its own.
        for k, color in enumerate(swatch[-2:]):
            parts.append(f'<rect x="{200 + k * 17}" y="{y - 7}" width="14" height="14" fill="{color}"/>')
        parts.append(f'<text x="242" y="{y + 5}" {font} font-size="13" fill="{t["ink"]}" fill-opacity="0.85">{escape(paints)}</text>')
    parts.append(f'<text x="24" y="360" {font} font-size="12" fill="{t["mute"]}">From {total} public repos. Redrawn every night at 00:20 UTC.</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def scales_svg(rows, total, body, theme):
    """The koi's net of scales; about a third are lit, in each pigment's real share."""
    t = THEMES[theme]
    weights = [(ramp_for(body, pigment)[1], sum(v for _, v in languages) / total) for pigment, languages in rows]
    rng = random.Random(7)  # fixed, so the band only changes when the languages do

    def lit_color():
        x, acc = rng.random(), 0.0
        for swatch, weight in weights:
            acc += weight
            if x < acc:
                return rng.choice(swatch[-2:])
        return rng.choice(weights[-1][0][-2:])

    w, h = 22, 14
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 56" width="880" height="56" role="img" aria-label="Koi scales in my language colours">']
    for row in range(5):
        y = 6 + row * h * 0.72
        x = -w + (w / 2 if row % 2 else 0)
        while x < 880 + w:
            fill = lit_color() if weights and rng.random() < 0.34 else t["scale"]
            parts.append(f'<path d="M{x:.1f} {y + h:.1f} A {w / 2} {h} 0 0 1 {x + w:.1f} {y + h:.1f} Z" fill="{fill}" stroke="{t["net"]}" stroke-width="1.3"/>')
            x += w
    parts.append("</svg>")
    return "\n".join(parts)


def koi_tiles(koi_path, out_dir):
    koi = Image.open(koi_path)
    if koi.size != (2 * NATIVE, 2 * NATIVE):
        sys.exit(f"expected a {2 * NATIVE}x{2 * NATIVE} koi, got {koi.size[0]}x{koi.size[1]}")

    def koi_pixels(frame):
        # Back to one image pixel per koi pixel, then up again, so every koi pixel is an even square.
        native = frame.convert("RGBA").resize((NATIVE, NATIVE), Image.Resampling.NEAREST)
        return native.resize((TILE, TILE), Image.Resampling.NEAREST)

    # Pillow hands back each frame already composited, so frames can be pasted whole.
    frames = [(koi_pixels(frame), frame.info.get("duration", 67)) for frame in ImageSequence.Iterator(koi)]
    for name, t in THEMES.items():
        base = Image.new("RGBA", (TILE, TILE), t["page"] + (255,))
        ImageDraw.Draw(base).rounded_rectangle((0, 0, TILE - 1, TILE - 1), radius=RADIUS, fill=t["pond"] + (255,), outline=ImageColor.getrgb(t["line"]), width=2)
        rgb = []
        for frame, _ in frames:
            canvas = base.copy()
            canvas.alpha_composite(frame)
            rgb.append(canvas.convert("RGB"))
        # One shared palette keeps colours from flickering between frames.
        palette = rgb[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        out = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in rgb]
        out[0].save(out_dir / f"koi-{name}.gif", save_all=True, append_images=out[1:], duration=[d for _, d in frames], loop=0)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    out_dir = Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = json.loads(Path(sys.argv[2]).read_text())
    body = os.environ.get("KOI_BODY", "white")  # the same body git-koi drew, so the swatches match
    rows, total, colors = pigment_rows(snapshot)
    streak = current_streak(snapshot)
    for theme in THEMES:
        (out_dir / f"key-{theme}.svg").write_text(key_svg(rows, total, colors, streak, body, theme))
        (out_dir / f"scales-{theme}.svg").write_text(scales_svg(rows, total, body, theme))
    koi_tiles(Path(sys.argv[1]), out_dir)
