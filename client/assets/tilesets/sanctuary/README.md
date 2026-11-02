# Connected Sanctuary walls

Native SVG art and TileSet authored by `scripts/build_sanctuary_wall_atlas.py`.
Run it after editing the geometry/palette; `--check` verifies all generated outputs.
No raster-generation/editing pipeline is used for these exact geometric joins.

47 atlas tiles cover all valid cardinal connections plus filled diagonal corners.
Connectivity bits are N=1, E=2, S=4, W=8, NE=16, SE=32, SW=64, NW=128. A diagonal
bit is present only when both adjacent cardinal walls and the diagonal wall exist.
Each tile stores its mask in the integer custom-data field `connections`.

The runtime surface-coordinate atlas uses 192×256 regions on a 128×128 tile grid,
rendered at quarter scale to retain 32×32 world cells. Coping is 24 world units
wide and raised 24 units, with an 8-unit westward offset. Exposed south and east
faces descend to the ground footprint. Texture origin (0,32) and the larger art
region position the coping at (-8,-24) relative to the world cell. TileSet metadata
`wall_top_offset` supplies this same projection to roofs.
Vertical runs have continuous side faces, with no per-cell front ledges or end-cap
outlines. Filled corners close seams in thicker wall blocks without filling the
notch of an L-shaped wall. The coordinate atlas uses linear filtering; the shared
masonry shader samples generated stone materials with nearest filtering on a
half-world-unit art grid. `walls.svg` remains a geometry diagnostic; the runtime
TileSet consumes `walls-surfaces.svg` with the masonry ShaderMaterial.

Masonry and the shoreline quay both select variants from their own neighbour sets.
Walls use carved Gothic faces; the quay uses plain ashlar from the same material
family. Visual projection does not change the shared authoritative collision.

The windowed Sanctuary preview captures the southeast Temple corner and northern
junctions. Its regression checks real map atlas diversity, fixed Temple corner/T
connections, and registration of all 47 shapes, alongside the existing roof checks.
