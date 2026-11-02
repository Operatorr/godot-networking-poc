# Sanctuary material atlas

`materials.png`: generated with the built-in imagegen tool, 2026-11-02, for this project.
User-provided grimdark city and close-up art informed the palette; no source-image pixels
were copied. No separate third-party asset license was supplied.

Prompt: 4×4 full-bleed atlas of sixteen independently usable material squares: navy water,
worn cobble, dead grass, flagstones; ashlar, coping, red shingles, slate; planks, portcullis,
ritual pavement, stairs; amber gothic window, closed arched door, crimson banner, moss paving.
Detailed grimdark pixel art, upper-left lighting, desaturated stone and rust palette, no text.

Atlas cell boundaries and scene import inspected. The generated materials have visible
repetition; they are an initial art pass, not a claim of final close-up reference fidelity.

`interiors.png`: replacement built-in imagegen generation, 2026-11-02, for the user's
steeper top-down reference. All sixteen slots share an overhead camera target (65–70°
above the ground), dominant top surfaces, shallow front faces, and upper-left lighting.
Objects: column, basin, altar, carpet, bed, dining set, chest, bookcase, stairs, desk,
potion counter, bank counter, bowl brazier, bench, low cabinet and barrels.
The full generation prompt is preserved in `topdown-props-prompt.txt`.

The source PNG is 1254×1254 RGBA, with alpha 0..255 and 838,093 fully transparent pixels.
`interiors-regions.json` records padded alpha-content bounds for each grid cell.
`scripts/inspect_sanctuary_prop_atlas.py` generates/checks this metadata without changing
pixels (Pillow required). Every sprite has isolated cell margins. Godot consumes the bounds
through AtlasTexture, uniformly fits props to their display boxes, and uses nearest filtering.
Only the flat carpet is intentionally stretched to fit its floor footprint. The Temple
column display box is now 52×56 instead of the tall 56×90 version. Doorway lights use the
matching low brazier sprite plus the existing glow.

Verification: alpha/cell-boundary QA, all sixteen props rendered in the Godot preview gallery,
and windowed inspection of Temple, housing and service interiors. Furnishings remain cosmetic
except the existing authoritative column bases. Unused stair art does not imply floor switching.
The former frontal prop sheet and rejected whole-building sheet are no longer used.

## Gothic wall material

`wall-materials.png` was generated with the built-in imagegen tool on 2026-11-02.
The user's grimdark cathedral references informed its charcoal stone, worn bevels,
soot-black joints and blind pointed-arch carving. The source PNG is 1254×1254 RGB,
fully opaque; wall silhouettes supply transparency separately. No supplied reference
pixels were copied and no third-party stock asset or separate license was introduced.
The exact prompt is in `wall-materials-prompt.txt`.

The four quadrants contain capstones, ashlar, carved frieze and molding (the last
is reserved). `masonry.gdshader` projects the first three onto connected wall tiles:
continuous capstone coordinates, independent south/east face coordinates, and
directional shading. Building walls use the frieze; quays use plain ashlar.
Material detail is sampled on a half-world-unit grid to suit the nearby floor art.

`scripts/build_sanctuary_wall_atlas.py` preserves the 47 connection masks and emits
`walls-surfaces.svg`: a 1536×1536 coordinate/alpha atlas, 192×256 regions, 128×128
logical cells. Wall layers scale by 1/4, retaining 32-unit cells, 24-unit rise,
8-unit lateral projection and the previous ground-footprint sort origins. The old
`walls.svg` is a geometric diagnostic output, not the runtime wall appearance.
Do not apply the coordinate atlas without its masonry ShaderMaterial.

Verification: import/shader compilation, the 47-shape windowed gallery, Temple
close-up, corners/junctions, housing and quay overview, roof checks, rendered depth
regressions, generator consistency and shared-geometry bake checks. This replaces
the flat placeholder material; it does not reproduce the references' entire scene
lighting, wall height, architectural silhouettes or decorative placement.
