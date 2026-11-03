# Sanctuary wall-tile town

The red marks in the supplied plan represent **wall tiles**, not solid building sprites.
Sanctuary now uses explicit wall cells, open doorways, interior floors, partitions and
independent roof TileMapLayers. The rejected whole-building sprite atlas is removed.

The primary plan is preserved at `references/sanctuary-plan.png`. Its repeating grid is
approximately 2.91 image pixels per tile. Cell centers map back approximately as
`image = (1.88,1.88) + (cell + (82,72)) * 2.91`; world centers are `(cell + 0.5) * 32`.
Red wall marks were sampled from the plan; label-obscured boundaries, room envelopes and
doorways are reconstructed, not a lossless reproduction. Door openings were widened where
necessary for the 32-unit player diameter. Offshore structures are omitted; water surrounds
the island and exits 1–4 remain sealed.

| Marker | World position | Behavior |
| --- | --- | --- |
| T | (208,272) | Temple arrival; six nearby authoritative spawn anchors |
| C | (496,432) | Arena travel portal inside the same Temple |
| D | (2256,-464) | Bank interior on the east side; transactions remain a stub |
| 10 | (16,-592) | Vendor interior; trading remains a stub |
| — | (528,-144) | Father Aldric, in the Temple chancel; opens the character sacrifice prompt |

There are 57 building records: the Temple, Bank, vendor and 54 housing plots. Every record
has a stable `id`, `kind`, bounds, floor cells, roof cells, doorway, street point and interior
anchor. Housing IDs identify future ownership targets; this change does **not** implement
purchase, rent, permissions, locked doors, furniture storage or ownership persistence.
Do not renumber existing IDs when adding plots.

## Authoring and authority

`client/data/world/sanctuary/layout.json` is the source for visuals and collision. Edit wall
cells and floor/roof ownership together. A doorway is an actual gap in the wall array, not a
visual door pasted over a collider. Room partitions share their building's roof group.
The Temple contains a nave, side chapels and solid column bases. Housing has wooden floors
and sample furniture; larger houses have partitioned rooms. Furnishings are cosmetic, except
Temple column bases which remain solid cells in shared collision. Those eight cells
are excluded from the masonry renderer and its neighbour lookup; column sprites are their
only visible representation, over the same flagstone floor as the hall. There are no usable stairs or extra floors yet.

`SanctuaryTownWorld` builds Ground, Masonry, Quay, SealedGates and one Roof layer per building.
Masonry and Quay use the 47-variant connected wall TileSet in
`client/assets/tilesets/sanctuary/walls.tres`, selecting straight, corner, end and junction
shapes from cardinal/diagonal neighbours. The old repeated horizontal WallCaps layer is gone.
The wall TileSet uses a high-resolution surface-coordinate atlas at quarter scale,
preserving 32-world-unit cells and the existing wall height. A shared masonry shader
projects generated charcoal capstone and Gothic frieze material onto the appropriate
faces, including vertical runs and corners. Quays use a second shared material with
plain ashlar faces. The generated material and prompt record live alongside the
Sanctuary sprite assets. Collision geometry is unaffected by material replacement.
The material atlas supplies floors and roofs; ground uses 4×4 subtiles per material. Roofs render above actors.
Decorative interior art uses a separate transparent 4×4 atlas with a steep overhead view.
Per-prop alpha bounds are stored in `interiors-regions.json`; sprites keep their aspect ratio
when fitted to placement boxes (except the flat carpet). Doorway braziers use the same set. Roof art and furniture can be
replaced without changing wall geometry.

Solid scenery and actors share Z=0 and a nested Y-sort domain: Sanctuary,
EntityContainer, TownWorld and the wall/gate TileMapLayers all enable Y sorting.
Wall cells sort at the south edge of their ground footprint. Props sort at the
bottom of their cropped art, with a sprite offset preserving the visible placement.
Entity roots keep their existing simulation positions and sort their visual children
as one unit. Floors, carpets and ground glows stay below this domain; labels and
roofs stay above it. Fixed prop-versus-wall Z bands would defeat this ordering.

The networked shell binds **only the local player** as roof observer. Its current position is
converted with `to_local()` and looked up in the roof-cell ownership map. Entering a building
hides its entire roof; leaving restores it. Direct transfers between buildings restore the
old roof and hide the new one. No physics overlap signals, movement writers, RPCs or ownership
claims are involved. Roof state is presentation-only and is neither replicated nor persisted.
Remote players cannot trigger the local roof state. A freed observer is safely ignored.

Roof art is translated by `wall_top_offset` metadata on the wall TileSet: (-8,-24)
world units. The atlas generator owns this projection alongside the 8-unit lateral
offset and 24-unit rise; roofs and masonry cannot silently acquire independent
offsets. Roof ownership remains in the unshifted ground grid, so walking under an
overhang on the street does not count as entering. All 5,672 roof cells cover the
same 57 building footprints; no housing IDs or service locations changed.

The whole-town doorway audit removed 25 obstructing wall cells and restored four
cells on disused shore-facing doors. `house_001` and `house_041` now have east-facing
approaches on dry land. The bake requires every marked doorway to have player
clearance and a route to its interior anchor without leaving its roof group. Merely
reaching an anchor through a different opening no longer passes validation.

Run `python3 scripts/bake_sanctuary.py` after edits and use `--check` in verification. The bake
checks unique identities, floor/roof consistency, open entrances, every interior/service/spawn
anchor's player-clearance route, and four blocked exits. It emits shared Rust water/wall/gate
rectangles and spawn coordinates. Closed building footprints are **not** collision rectangles.
Exact Sanctuary bounds with the Arena-obstacle flag false select these shared solids; bounds
remain ±3328 × ±3072. Rebuild server and GDExtension together after changing the map.

The server owns movement and spawn selection; client prediction uses the same Rust geometry.
Positions replicate as before. No map, roof or housing state is saved by this change. Arena
travel behavior is retained. The town places the priest, banker and vendor; the priest keeps his
sacrifice flow, while the earlier class trainers, second vendor and generic townsfolk are not placed yet. Stale native extensions can disagree with
the map, so deploying only the GDScript/JSON is insufficient.

## Validation

- Bake checks all interior and service paths with player-radius clearance, plus closed exits.
- Rust tests check spawn/service/interior anchors, water, gates and swept Temple wall collision.
- The Godot preview checks roof entry, exit, direct building-to-building teleport, translated
  town coordinates, and the live local-observer path before rendering overview/interior shots.
- Windowed preview compares rendered pixels at the Temple column/wall overlap and
  checks an actor in the separate entity container both behind and in front of a
  wall and a column. Headless checks do not validate rendered occlusion.
- The windowed wall-material gallery shows all 47 shapes using the production shader.
- `sanctuary_roof_audit.tscn` checks every rendered masonry cell's ground-grid
  alignment, every roof cell's projected position and coverage, then moves a live
  observer from street through doorway to interior and back for all 57 buildings.
  It saves exterior/interior images and a per-building report under
  `/tmp/sanctuary_roof_audit`. `scripts/inspect_sanctuary_roofs.py` assembles these
  beside crops of the original City Map under `output/sanctuary/roof-audit`.
- Workspace tests, clippy, formatting and the native extension build run for the change.
- Connected multi-client travel and crowded-town performance remain playtest work.

Preview: `/Applications/Godot.app/Contents/MacOS/Godot --path client res://scenes/test/sanctuary_preview.tscn`.
Headless mode runs the roof checks without screenshots. Windowed mode captures roofs and
interiors to `/tmp/sanctuary_preview`.

Full roof tour: `/Applications/Godot.app/Contents/MacOS/Godot --path client res://scenes/test/sanctuary_roof_audit.tscn`.
The City Map comparison preserves the existing district/building reconstruction;
it is not a claim of lossless recovery of walls hidden beneath the source labels.
