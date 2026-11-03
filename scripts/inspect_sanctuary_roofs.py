#!/usr/bin/env python3
"""Make diagnostic City Map / roof-on / roof-off tour sheets (Pillow required).

Run the windowed sanctuary_roof_audit.tscn first. This only assembles QA evidence;
it does not edit source images or game assets.
"""
import json
import shutil
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = Path('/tmp/sanctuary_roof_audit')
OUT = ROOT / 'output/sanctuary/roof-audit'
layout = json.loads((ROOT / 'client/data/world/sanctuary/layout.json').read_text())
report = json.loads((CAPTURES / 'report.json').read_text())
assert {b['id'] for b in report['buildings']} == {b['id'] for b in layout['buildings']}
assert all(b['rendered'] and b['alignment'] == b['entry'] == b['exit'] == 'pass'
           for b in report['buildings']), 'Run the windowed audit before assembling evidence'
source = Image.open(ROOT / layout['source']).convert('RGB')
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy(CAPTURES / 'report.json', OUT / 'report.json')
for page in range((len(layout['buildings']) + 7) // 8):
    buildings = layout['buildings'][page * 8:(page + 1) * 8]
    sheet = Image.new('RGB', (1440, 220 * ((len(buildings) + 1) // 2)), '#101316')
    draw = ImageDraw.Draw(sheet)
    for index, building in enumerate(buildings):
        ox, oy = index % 2 * 720, index // 2 * 220
        draw.text((ox + 8, oy + 5), building['id'] + '   CITY MAP | ROOF ON | ENTERED / ROOF OFF', fill='white')
        x, y, width, height = building['bounds']
        # The original trace sampled cell centers at 1.88 + cell*2.91 pixels.
        sx, sy = 1.88 + (x + 82 - .5) * 2.91, 1.88 + (y + 72 - .5) * 2.91
        pad = 7
        crop = source.crop((int(sx-pad), int(sy-pad), int(sx+width*2.91+pad), int(sy+height*2.91+pad)))
        ImageDraw.Draw(crop).rectangle((pad, pad, pad+width*2.91, pad+height*2.91), outline='cyan', width=1)
        crop.thumbnail((136, 190), Image.Resampling.NEAREST)
        sheet.paste(crop, (ox + 4, oy + 25))
        for column, state in enumerate(['outside', 'inside']):
            image = Image.open(CAPTURES / f"{building['id']}-{state}.png").convert('RGB')
            image.thumbnail((280, 190), Image.Resampling.LANCZOS)
            sheet.paste(image, (ox + 145 + column * 285, oy + 25))
    sheet.save(OUT / f'tour-{page+1:02d}.jpg', quality=92)
for building_id in ['house_001', 'house_003', 'house_027', 'house_041', 'temple']:
    for state in ['outside', 'inside']:
        name = f'{building_id}-{state}.png'
        shutil.copy(CAPTURES / name, OUT / name)
print(f"Roof audit sheets: {len(report['buildings'])} buildings, {report['wall_cells_checked']} rendered wall cells")
