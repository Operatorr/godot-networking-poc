#!/usr/bin/env python3
"""Assemble PixelLab per-frame PNGs into grid spritesheets + meta.json.

Input spec (JSON):
{
  "name": "zealot",
  "out_dir": "client/assets/sprites/players/zealot",
  "directional": true,            # false for 1-direction objects (slime, projectiles)
  "anims": {
    "idle": {"fps": 8, "loop": true,  "dirs": {"south": ["<url-or-path>", ...], ...}},
    "run":  {"fps": 12, "loop": true, "dirs": {...}}
  }
}

For directional sheets, each animation becomes <anim>.png with one row per
direction in DIR_ORDER (missing directions are an error) and frame columns.
For 1-direction assets, "dirs" must hold the single key "unknown" -> one row.

meta.json written next to the sheets:
{
  "canvas": [w, h],
  "directional": true,
  "dir_order": [...DIR_ORDER],
  "anims": {"idle": {"frames": 8, "fps": 8, "loop": true, "png": "idle.png"}, ...}
}

All frames of one asset must share identical dimensions; the script verifies.
Frames may be http(s) URLs (downloaded with urllib) or local file paths.
"""

import io
import json
import pathlib
import sys
import urllib.request

from PIL import Image

DIR_ORDER = [
    "south",
    "south-east",
    "east",
    "north-east",
    "north",
    "north-west",
    "west",
    "south-west",
]


def fetch(src: str) -> Image.Image:
    if src.startswith("http://") or src.startswith("https://"):
        for attempt in range(3):
            try:
                with urllib.request.urlopen(src, timeout=30) as r:
                    return Image.open(io.BytesIO(r.read())).convert("RGBA")
            except Exception:
                if attempt == 2:
                    raise
    return Image.open(src).convert("RGBA")


def assemble(spec_path: str) -> None:
    spec = json.loads(pathlib.Path(spec_path).read_text())
    out_dir = pathlib.Path(spec["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    directional = spec.get("directional", True)
    rows = DIR_ORDER if directional else ["unknown"]

    canvas = None
    meta_anims = {}
    for anim, info in spec["anims"].items():
        dirs = info["dirs"]
        missing = [d for d in rows if d not in dirs]
        if missing:
            raise SystemExit(f"{spec['name']}/{anim}: missing directions {missing}")
        counts = {len(v) for v in dirs.values()}
        if len(counts) != 1:
            raise SystemExit(f"{spec['name']}/{anim}: uneven frame counts {counts}")
        n_frames = counts.pop()

        grid = None
        for row_i, d in enumerate(rows):
            for col_i, src in enumerate(dirs[d]):
                frame = fetch(src)
                if canvas is None:
                    canvas = frame.size
                if frame.size != tuple(canvas):
                    raise SystemExit(
                        f"{spec['name']}/{anim}/{d}[{col_i}]: size {frame.size} != canvas {canvas}"
                    )
                if grid is None:
                    grid = Image.new(
                        "RGBA", (canvas[0] * n_frames, canvas[1] * len(rows)), (0, 0, 0, 0)
                    )
                grid.paste(frame, (col_i * canvas[0], row_i * canvas[1]))
        png_name = f"{anim}.png"
        grid.save(out_dir / png_name)
        meta_anims[anim] = {
            "frames": n_frames,
            "fps": info.get("fps", 10),
            "loop": info.get("loop", True),
            "png": png_name,
        }
        print(f"  {spec['name']}/{png_name}: {n_frames}f x {len(rows)} rows @ {canvas}")

    meta = {
        "canvas": list(canvas),
        "directional": directional,
        "dir_order": rows if directional else [],
        "anims": meta_anims,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"  wrote {out_dir / 'meta.json'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: assemble_pixellab_sheets.py <spec.json> [<spec.json> ...]")
    for p in sys.argv[1:]:
        assemble(p)
