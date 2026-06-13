#!/usr/bin/env python3
"""Build a class spritesheet set from an extracted PixelLab character zip.

The character download zip stores one folder per animate_character CALL
(e.g. cardinals and diagonals of the same animation land in "running" and
"running-fccf70ce"). This script merges folders by PREFIX into logical
animations, then drives assemble_pixellab_sheets.py.

usage:
  assemble_character.py <extract_dir> <char_folder> <out_dir> <map_json>

map_json example:
  {"idle":  {"prefix": "animating", "fps": 8,  "loop": true},
   "run":   {"prefix": "running",   "fps": 12, "loop": true},
   "death": {"prefix": "falling_backward", "fps": 10, "loop": false}}
"""

import json
import pathlib
import subprocess
import sys

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


def main() -> int:
    extract_dir, char_folder, out_dir, map_json = sys.argv[1:5]
    anim_map = json.loads(pathlib.Path(map_json).read_text())
    anim_root = pathlib.Path(extract_dir) / char_folder / "animations"

    spec_anims = {}
    for anim, info in anim_map.items():
        prefix = info["prefix"]
        dirs: dict[str, list[str]] = {}
        for folder in sorted(anim_root.iterdir()):
            if not folder.name.startswith(prefix):
                continue
            for dir_path in folder.iterdir():
                if not dir_path.is_dir():
                    continue
                frames = [str(p) for p in sorted(dir_path.glob("frame_*.png"))]
                if not frames:
                    continue
                if dir_path.name in dirs:
                    raise SystemExit(
                        f"{anim}: direction {dir_path.name} present in multiple "
                        f"'{prefix}*' folders — refusing to guess"
                    )
                dirs[dir_path.name] = frames
        missing = [d for d in DIR_ORDER if d not in dirs]
        if missing:
            raise SystemExit(f"{anim} (prefix '{prefix}'): missing directions {missing}")
        # v3 animations store a reference frame as frame_000; counts must match
        # across directions, which the sheet assembler verifies.
        spec_anims[anim] = {
            "fps": info.get("fps", 10),
            "loop": info.get("loop", True),
            "dirs": dirs,
        }

    spec = {
        "name": pathlib.Path(out_dir).name,
        "out_dir": out_dir,
        "directional": True,
        "anims": spec_anims,
    }
    spec_path = pathlib.Path(extract_dir) / "sheet_spec.json"
    spec_path.write_text(json.dumps(spec))
    assembler = pathlib.Path(__file__).parent / "assemble_pixellab_sheets.py"
    return subprocess.run([sys.executable, str(assembler), str(spec_path)]).returncode


if __name__ == "__main__":
    sys.exit(main())
