#!/usr/bin/env python3
"""Generate Omega Realm HUD sprites from the design guide palette."""

from __future__ import annotations

from pathlib import Path
from random import Random

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "client" / "assets" / "ui" / "hud"
ABILITY_SLOTS_WIDTH = 36 * 6 + 4 * 5

PALETTE = {
    "abyss": (5, 7, 6, 255),
    "ash": (85, 88, 82, 255),
    "iron": (37, 41, 40, 255),
    "blood": (74, 21, 18, 255),
    "rust": (138, 38, 31, 255),
    "umber": (58, 33, 26, 255),
    "gold": (155, 116, 40, 255),
    "bone": (216, 208, 188, 255),
    "sulfur": (198, 154, 46, 255),
    "violet": (91, 58, 142, 255),
    "purple": (43, 24, 61, 255),
    "magenta": (138, 45, 85, 255),
    "blue": (29, 53, 87, 255),
    "teal": (28, 108, 115, 255),
}


def rgba(color: tuple[int, int, int, int], alpha: int | None = None) -> tuple[int, int, int, int]:
    if alpha is None:
        return color
    return (color[0], color[1], color[2], alpha)


def jitter(color: tuple[int, int, int, int], amount: int, rng: Random) -> tuple[int, int, int, int]:
    return (
        max(0, min(255, color[0] + rng.randint(-amount, amount))),
        max(0, min(255, color[1] + rng.randint(-amount, amount))),
        max(0, min(255, color[2] + rng.randint(-amount, amount))),
        color[3],
    )


def draw_iron_line(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = xy
    draw.rectangle((x0, y0, x1, y1), outline=PALETTE["abyss"])
    draw.line((x0 + 1, y0 + 1, x1 - 1, y0 + 1), fill=rgba(PALETTE["ash"], 190))
    draw.line((x0 + 1, y1 - 1, x1 - 1, y1 - 1), fill=rgba(PALETTE["umber"], 230))
    draw.line((x0 + 1, y0 + 1, x0 + 1, y1 - 1), fill=rgba(PALETTE["ash"], 120))
    draw.line((x1 - 1, y0 + 1, x1 - 1, y1 - 1), fill=rgba(PALETTE["umber"], 210))


def draw_rivets(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]]) -> None:
    for x, y in points:
        draw.point((x, y), fill=PALETTE["gold"])
        draw.point((x + 1, y), fill=PALETTE["abyss"])
        draw.point((x, y + 1), fill=PALETTE["abyss"])


def make_bar_frame(path: Path, width: int, height: int, accent: str, medallion: bool) -> None:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent_color = PALETTE[accent]

    left = 32 if medallion else 4
    right = width - 5
    y0 = 4
    y1 = height - 5

    # Outer chipped iron silhouette.
    draw.polygon(
        [
            (left + 4, y0),
            (right - 12, y0),
            (right - 2, height // 2),
            (right - 12, y1),
            (left + 4, y1),
            (left, height // 2),
        ],
        fill=PALETTE["abyss"],
    )
    draw.polygon(
        [
            (left + 6, y0 + 2),
            (right - 14, y0 + 2),
            (right - 5, height // 2),
            (right - 14, y1 - 2),
            (left + 6, y1 - 2),
            (left + 3, height // 2),
        ],
        outline=PALETTE["ash"],
        fill=PALETTE["iron"],
    )
    draw.line((left + 9, y0 + 4, right - 17, y0 + 4), fill=rgba(PALETTE["gold"], 150))
    draw.line((left + 9, y1 - 4, right - 17, y1 - 4), fill=rgba(PALETTE["umber"], 220))

    # Transparent resource trough; the game layers track and fill textures behind it.
    trough = (left + 8, 9, right - 17, height - 10)
    draw.rectangle(trough, fill=(0, 0, 0, 0))
    draw.rectangle(trough, outline=PALETTE["abyss"])
    draw.line((trough[0] + 1, trough[1] + 1, trough[2] - 1, trough[1] + 1), fill=rgba(accent_color, 150))
    draw.line((trough[0] + 1, trough[3] - 1, trough[2] - 1, trough[3] - 1), fill=PALETTE["abyss"])

    # Right cap and small gothic hardware.
    draw.line((right - 15, y0 + 4, right - 7, height // 2), fill=rgba(PALETTE["gold"], 180))
    draw.line((right - 7, height // 2, right - 15, y1 - 4), fill=rgba(PALETTE["gold"], 120))
    draw_rivets(draw, [(left + 9, y0 + 5), (right - 18, y0 + 5), (left + 9, y1 - 6), (right - 18, y1 - 6)])

    if medallion:
        cx = 18
        cy = height // 2
        draw.ellipse((2, cy - 15, 32, cy + 15), fill=PALETTE["abyss"], outline=PALETTE["ash"])
        draw.ellipse((5, cy - 12, 29, cy + 12), fill=PALETTE["iron"], outline=PALETTE["gold"])
        if accent == "blood":
            # Skull motif for HP.
            draw.rectangle((12, cy - 6, 24, cy + 5), fill=PALETTE["bone"])
            draw.rectangle((14, cy + 4, 22, cy + 10), fill=PALETTE["bone"])
            draw.rectangle((14, cy - 3, 16, cy - 1), fill=PALETTE["abyss"])
            draw.rectangle((20, cy - 3, 22, cy - 1), fill=PALETTE["abyss"])
            draw.point((18, cy + 1), fill=PALETTE["abyss"])
            draw.line((14, cy + 8, 22, cy + 8), fill=PALETTE["abyss"])
        else:
            # Arcane gem motif for mana.
            draw.polygon(
                [(18, cy - 9), (25, cy - 1), (21, cy + 9), (15, cy + 9), (11, cy - 1)],
                fill=accent_color,
                outline=PALETTE["bone"],
            )
            draw.point((18, cy - 3), fill=rgba(PALETTE["bone"], 220))

    img.save(path)


def make_fill(path: Path, width: int, height: int, base: str, highlight: str) -> None:
    rng = Random(path.name)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        shade = 1.15 - t * 0.45
        color = PALETTE[base]
        row = (
            max(0, min(255, int(color[0] * shade))),
            max(0, min(255, int(color[1] * shade))),
            max(0, min(255, int(color[2] * shade))),
            255,
        )
        draw.line((0, y, width, y), fill=jitter(row, 4, rng))
    draw.line((0, 1, width, 1), fill=rgba(PALETTE[highlight], 190))
    draw.line((0, height - 2, width, height - 2), fill=rgba(PALETTE["abyss"], 180))
    for x in range(0, width, 11):
        draw.point((x, height // 2), fill=rgba(PALETTE[highlight], 120))
    img.save(path)


def make_track(path: Path, width: int, height: int, accent: str) -> None:
    rng = Random(path.name)
    img = Image.new("RGBA", (width, height), rgba(PALETTE["abyss"], 245))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        base = PALETTE["umber"] if y < height // 2 else PALETTE["abyss"]
        draw.line((0, y, width, y), fill=jitter(rgba(base, 230), 3, rng))
    draw.line((0, 1, width, 1), fill=rgba(PALETTE[accent], 70))
    draw.line((0, height - 2, width, height - 2), fill=rgba(PALETTE["abyss"], 220))
    img.save(path)


def make_stamina_frame(path: Path, width: int, height: int) -> None:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_iron_line(draw, (0, 2, width - 1, height - 3))
    draw.rectangle((5, 5, width - 6, height - 6), fill=(0, 0, 0, 0))
    draw.rectangle((5, 5, width - 6, height - 6), outline=rgba(PALETTE["abyss"], 230))
    draw.line((6, 6, width - 7, 6), fill=rgba(PALETTE["sulfur"], 125))
    draw_rivets(draw, [(5, 3), (width // 2, 3), (width - 7, 3), (5, height - 5), (width - 7, height - 5)])
    img.save(path)


def make_minimap_frame(path: Path, size: int = 180) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    outer = (0, 0, size - 1, size - 1)
    inner = (18, 18, size - 19, size - 19)
    draw_iron_line(draw, outer)
    draw_iron_line(draw, (5, 5, size - 6, size - 6))
    draw.rectangle(inner, outline=rgba(PALETTE["gold"], 145))
    draw.rectangle((inner[0] + 2, inner[1] + 2, inner[2] - 2, inner[3] - 2), outline=rgba(PALETTE["abyss"], 220))

    # Corner clamps.
    for x in (0, size - 26):
        for y in (0, size - 26):
            draw.rectangle((x + 4, y + 4, x + 24, y + 24), outline=PALETTE["ash"], fill=rgba(PALETTE["iron"], 235))
            draw.line((x + 8, y + 14, x + 20, y + 14), fill=PALETTE["gold"])
            draw.line((x + 14, y + 8, x + 14, y + 20), fill=PALETTE["gold"])
            draw.point((x + 14, y + 14), fill=PALETTE["bone"])

    # Compass ornaments.
    for text_y in (9, size - 14):
        draw.ellipse((size // 2 - 7, text_y - 5, size // 2 + 7, text_y + 9), outline=PALETTE["gold"], fill=rgba(PALETTE["abyss"], 230))
        draw.point((size // 2, text_y + 2), fill=PALETTE["bone"])
    draw_rivets(draw, [(size // 2, 4), (size // 2, size - 7), (4, size // 2), (size - 7, size // 2)])
    img.save(path)


def make_ability_slot_frame(path: Path, size: int = 36) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((1, 1, size - 2, size - 2), fill=PALETTE["abyss"], outline=PALETTE["ash"])
    draw.rectangle((4, 4, size - 5, size - 5), fill=PALETTE["iron"], outline=rgba(PALETTE["gold"], 170))
    draw.rectangle((8, 8, size - 9, size - 9), fill=rgba(PALETTE["abyss"], 235), outline=rgba(PALETTE["umber"], 230))
    draw.line((6, 5, size - 7, 5), fill=rgba(PALETTE["bone"], 90))
    draw.line((6, size - 6, size - 7, size - 6), fill=rgba(PALETTE["umber"], 230))
    for x, y in [(4, 4), (size - 6, 4), (4, size - 6), (size - 6, size - 6)]:
        draw.point((x, y), fill=PALETTE["gold"])
        draw.point((x + 1, y + 1), fill=PALETTE["abyss"])
    img.save(path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_bar_frame(OUT_DIR / "player_health_bar_frame.png", 300, 36, "blood", True)
    make_bar_frame(OUT_DIR / "player_mana_bar_frame.png", 300, 36, "blue", True)
    make_stamina_frame(OUT_DIR / "player_stamina_bar_frame.png", ABILITY_SLOTS_WIDTH, 18)
    make_fill(OUT_DIR / "player_health_bar_fill.png", 256, 18, "rust", "bone")
    make_fill(OUT_DIR / "player_mana_bar_fill.png", 256, 18, "blue", "teal")
    make_fill(OUT_DIR / "player_stamina_bar_fill.png", 256, 8, "sulfur", "bone")
    make_track(OUT_DIR / "player_health_bar_track.png", 256, 18, "blood")
    make_track(OUT_DIR / "player_mana_bar_track.png", 256, 18, "blue")
    make_track(OUT_DIR / "player_stamina_bar_track.png", 256, 8, "sulfur")
    make_minimap_frame(OUT_DIR / "player_minimap_frame.png")
    make_ability_slot_frame(OUT_DIR / "player_ability_slot_frame.png")


if __name__ == "__main__":
    main()
