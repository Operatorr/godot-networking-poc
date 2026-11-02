#!/usr/bin/env python3
"""Validate the 4x4 prop sheet and write region metadata, without changing pixels.
Requires Pillow. --check validates the existing metadata instead of writing it.
"""
import json
import sys
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
folder = root / 'client/assets/sprites/environment/sanctuary'
image = Image.open(folder / 'interiors.png').convert('RGBA')
alpha = image.getchannel('A')
assert alpha.getextrema() == (0, 255), 'Require fully transparent background and opaque objects'
names = ['column', 'basin', 'altar', 'carpet', 'bed', 'dining_table', 'chest',
         'bookcase', 'stairs', 'desk', 'potion_counter', 'bank_counter', 'brazier',
         'bench', 'storage_cabinet', 'barrels']
regions = []
for index, name in enumerate(names):
    col, row = index % 4, index // 4
    bounds = (round(col*image.width/4), round(row*image.height/4),
              round((col+1)*image.width/4), round((row+1)*image.height/4))
    cell_alpha = alpha.crop(bounds)
    # Ignore near-invisible antialiasing when finding useful sprite extents.
    box = cell_alpha.point(lambda a: 255 if a > 16 else 0).getbbox()
    assert box, f'{name}: empty cell'
    assert box[0] >= 2 and box[1] >= 2 and box[2] <= cell_alpha.width-2 and box[3] <= cell_alpha.height-2, f'{name}: touches cell edge'
    padding = 2
    rect = [bounds[0]+box[0]-padding, bounds[1]+box[1]-padding,
            box[2]-box[0]+padding*2, box[3]-box[1]+padding*2]
    regions.append({'name':name,'rect':rect})
manifest = {'texture_size':list(image.size), 'regions':regions}
target = folder / 'interiors-regions.json'
if '--check' in sys.argv:
    assert json.loads(target.read_text()) == manifest, 'Prop region metadata is stale'
else:
    target.write_text(json.dumps(manifest, indent=2)+'\n')
print('16 isolated prop regions validated; pixels unchanged')
