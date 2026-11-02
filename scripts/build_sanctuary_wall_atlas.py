#!/usr/bin/env python3
"""Author the native SVG wall atlas. N/E/S/W connectivity bits are 1/2/4/8.

Each nominal 48x64 region contains a 24-unit-wide connected coping, raised 24 units
and shifted 8 units west. Exposed south/east faces descend to the footprint. Connected edges have neither outlines nor end faces.
The runtime coordinate atlas rasterizes at 4x and the layer scales by 1/4.
No source raster is edited. Run --check to verify the committed native assets.
"""
from pathlib import Path
import sys

WALL_HEIGHT = 24
SIDE_DEPTH = 8
REGION_WIDTH = 48
REGION_HEIGHT = 64

ROOT = Path(__file__).resolve().parents[1]
MASKS = []
for mask in range(256):
    if all(not mask & diagonal or mask & adjacent == adjacent
           for diagonal, adjacent in [(16,3),(32,6),(64,12),(128,9)]):
        MASKS.append(mask)
assert len(MASKS) == 47
parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="384" height="384" viewBox="0 0 384 384">']
# Companion surface coordinates: red=cap, green=south face, blue=east face.
# On faces red stores extrusion depth (0..0.5). Runtime material projection
# uses this instead of stretching one horizontal facade around every corner.
surfaces = [parts[0].replace('width="384" height="384"', 'width="1536" height="1536"')]
for index, mask in enumerate(MASKS):
    ox, oy = (index % 8) * REGION_WIDTH, (index // 8) * REGION_HEIGHT
    parts.append(f'<g transform="translate({ox},{oy})">')
    surfaces.append(f'<g transform="translate({ox},{oy})">')
    cells = {(x,y) for x in range(1,7) for y in range(1,7)}
    if mask & 1: cells |= {(x,0) for x in range(1,7)}
    if mask & 2: cells |= {(7,y) for y in range(1,7)}
    if mask & 4: cells |= {(x,7) for x in range(1,7)}
    if mask & 8: cells |= {(0,y) for y in range(1,7)}
    for bit, corner in [(16,(7,0)),(32,(7,7)),(64,(0,7)),(128,(0,0))]:
        if mask & bit: cells.add(corner)
    def connected(x,y):
        if (x,y) in cells: return True
        return ((y == -1 and mask & 1 and ((1 <= x <= 6) or (x == 0 and mask & 128) or (x == 7 and mask & 16)))
                or (x == 8 and mask & 2 and ((1 <= y <= 6) or (y == 0 and mask & 16) or (y == 7 and mask & 32)))
                or (y == 8 and mask & 4 and ((1 <= x <= 6) or (x == 0 and mask & 64) or (x == 7 and mask & 32)))
                or (x == -1 and mask & 8 and ((1 <= y <= 6) or (y == 0 and mask & 128) or (y == 7 and mask & 64))))
    # Extrude only exposed east/south edges, so vertical runs gain a real
    # side face without reintroducing horizontal ledges between connected tiles.
    for x,y in sorted(cells, key=lambda p:(p[1],p[0])):
        for dx,dy in [(1,0),(0,1)]:
            if connected(x+dx,y+dy):
                continue
            sx,sy = ((x+1)*4, y*4) if dx else (x*4, (y+1)*4)
            ex,ey = (sx,sy+4) if dx else (sx+4,sy)
            face = '#343831' if dx else '#45463e'
            parts.append(f'<path d="M{sx} {sy}L{ex} {ey}l{SIDE_DEPTH} {WALL_HEIGHT}L{sx+SIDE_DEPTH} {sy+WALL_HEIGHT}z" fill="{face}"/>')
            gradient=f'depth_{index}_{x}_{y}_{dx}'
            channel='00ff' if dx else 'ff00'
            axis=f'x1="{sx}" y1="0" x2="{sx+SIDE_DEPTH}" y2="0"' if dx else f'x1="0" y1="{sy}" x2="0" y2="{sy+WALL_HEIGHT}"'
            surfaces.append(f'<defs><linearGradient id="{gradient}" gradientUnits="userSpaceOnUse" {axis}><stop offset="0" stop-color="#00{channel}"/><stop offset="1" stop-color="#80{channel}"/></linearGradient></defs>')
            surfaces.append(f'<path d="M{sx} {sy}L{ex} {ey}l{SIDE_DEPTH} {WALL_HEIGHT}L{sx+SIDE_DEPTH} {sy+WALL_HEIGHT}z" fill="url(#{gradient})"/>')
            for row in range(1, WALL_HEIGHT//4):
                depth=row*4
                shift=SIDE_DEPTH*depth/WALL_HEIGHT
                parts.append(f'<path d="M{sx+shift:.3f} {sy+depth}L{ex+shift:.3f} {ey+depth}" stroke="#282e29" stroke-width="0.7"/>')
            parts.append(f'<path d="M{sx+SIDE_DEPTH} {sy+WALL_HEIGHT}L{ex+SIDE_DEPTH} {ey+WALL_HEIGHT}" stroke="#151b1d"/>')
    # Bonded, chipped stone coping. Pixel-space detail remains consistent across
    # neighboring tiles; it is not a rotated full horizontal facade.
    for x,y in sorted(cells):
        sx,sy=x*4,y*4
        color=['#74736a','#7d7b70','#6c7069','#858175'][(x//2+y//2)%4]
        parts.append(f'<rect x="{sx}" y="{sy}" width="4" height="4" fill="{color}"/>')
        surfaces.append(f'<rect x="{sx}" y="{sy}" width="4" height="4" fill="#ff0000"/>')
        if y%2==0:
            parts.append(f'<path d="M{sx} {sy}h4" stroke="#454a45" stroke-width="0.65"/>')
        if (x+(y//2)%2)%3==0:
            parts.append(f'<path d="M{sx} {sy}v4" stroke="#4b5049" stroke-width="0.65"/>')
        if (x*3+y)%5==0:
            parts.append(f'<rect x="{sx+1}" y="{sy+1}" width="1" height="1" fill="#959184"/>')
        for dx,dy,color in [(0,-1,'#b2a995'),(-1,0,'#9a9586'),(0,1,'#3a403b'),(1,0,'#444b43')]:
            if connected(x+dx,y+dy):continue
            if dx:
                ex=sx+(4 if dx==1 else 0);edge=f'M{ex} {sy}v4'
            else:
                ey=sy+(4 if dy==1 else 0);edge=f'M{sx} {ey}h4'
            parts.append(f'<path d="{edge}" stroke="{color}" stroke-width="1"/>')
            # Green/blue on a red cap encode exposed lit/shadow bevels.
            bevel='#ff8000' if dx==-1 or dy==-1 else '#ff0080'
            surfaces.append(f'<path d="{edge}" stroke="{bevel}" stroke-width="1"/>')
    parts.append('</g>')
    surfaces.append('</g>')
parts.append('</svg>')
surfaces.append('</svg>')
text='\n'.join(parts)+'\n'
target=ROOT/'client/assets/tilesets/sanctuary/walls.svg'
if '--check' in sys.argv:
    assert target.read_text()==text, 'Run scripts/build_sanctuary_wall_atlas.py'
else:
    target.write_text(text)
surface_target=ROOT/'client/assets/tilesets/sanctuary/walls-surfaces.svg'
surface_text='\n'.join(surfaces)+'\n'
if '--check' in sys.argv:
    assert surface_target.read_text()==surface_text, 'Wall surface coordinates are stale'
else:
    surface_target.write_text(surface_text)
print('Wall atlas: 47 connected shapes, 192x256 surface regions at 1/4 scale, 24-unit rise')
resource = '''[gd_resource type="TileSet" load_steps=3 format=3]

[ext_resource type="Texture2D" path="res://assets/tilesets/sanctuary/walls-surfaces.svg" id="1"]

[sub_resource type="TileSetAtlasSource" id="Atlas"]
texture = ExtResource("1")
texture_region_size = Vector2i(192, 256)
'''
for index, mask in enumerate(MASKS):
    key=f'{index%8}:{index//8}/0'
    resource+=f'{key} = 0\n{key}/texture_origin = Vector2i(0, 32)\n{key}/custom_data_0 = {mask}\n'
resource+='\n[resource]\ntile_size = Vector2i(128, 128)\ncustom_data_layer_0/name = "connections"\ncustom_data_layer_0/type = 2\nsources/0 = SubResource("Atlas")\n'
resource+=f'metadata/wall_top_offset = Vector2(-{SIDE_DEPTH}, -{WALL_HEIGHT})\n'
target=ROOT/'client/assets/tilesets/sanctuary/walls.tres'
if '--check' in sys.argv:
    assert target.read_text()==resource, 'Wall TileSet is stale'
else:
    target.write_text(resource)
