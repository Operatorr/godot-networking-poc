---
name: create-game-assets
description: Create coherent Omega Realm pixel-art sprites, tiles, props, effects, and UI art. Use for asset briefs, visual families, generation/edit handoff, alpha/grid validation, contact sheets, and source records.
license: Apache-2.0
---

# Create Omega Realm game assets

Read [base art direction](../../../docs/design/BASE_DESIGN_GUIDE.md), [style guide](../../../docs/design/STYLEGUIDE.md), and the relevant biome/town guide. Preserve the 3/4 top-down oblique view, grimdark palette, and gameplay readability. Target the Godot 4.7 client.

## Workflow

1. Inspect the current asset family, scene, import settings, and `client/scripts/systems/visuals/sheet_library.gd`. Confirm actual frame dimensions, directions, pivot, filtering, and display scale before generating replacements.
2. Use the [brief template](assets/art-direction-brief.md) to lock silhouette, palette roles, light direction, pixel grid, transparency, frame count, baseline, and intended game-scale size. Avoid a broad visual redesign unless requested.
3. Establish one representative visual target at native scale. When the user delegated art choices, choose and record the strongest viable direction; do not introduce a separate approval gate.
4. Generate or edit related assets as a family with the same reference and technical constraints. Use the available `imagegen` skill/tool for raster creation and editing; inspect edit inputs first and request real transparency when needed. Follow its tool rules for any transformations.
5. Validate dimensions, alpha, frame boundaries, seams, and pivots. The scripts below inspect inputs or make diagnostic previews; they are not a substitute image-editing pipeline.
6. Import using the existing [Resource](../godot-resources/SKILL.md), [animation](../godot-animation/SKILL.md), and [TileMapLayer](../godot-tilemap/SKILL.md) conventions. Keep gameplay collision under shared geometry ownership.
7. Compare a contact sheet, animation playback, and the real scene at native scale. Check projectile contrast, silhouette stability, foot placement, atlas bleeding, and crowded-scene texture cost.
8. Record source/tool, license, reference/prompt record, and verification status using the [manifest template](assets/asset-manifest.json). Template paths and sizes are placeholders; replace them for the actual asset.

## Raster QA

Helpers require Python 3.10+ and [Pillow](scripts/requirements.txt). Use an existing compatible environment or an isolated environment; avoid changing project dependencies for asset inspection.

Run from this skill directory, supplying actual asset paths:

```bash
python3 scripts/asset_report.py /path/to/sprite.png --expect-size 64x64 --require-alpha --max-colors 48 --json
python3 scripts/build_preview_sheet.py /path/to/sprite.png --out /tmp/omega-assets-preview.png
```

`asset_report.py` exits 1 for failed constraints; `--require-alpha` rejects fully opaque images, including opaque RGBA. A preview checkerboard is diagnostic and must not be shipped as transparency. Use a separate output path so contact sheets cannot overwrite source art.

## References

Read [art direction](references/art-direction.md), [raster pipeline](references/raster-pipeline.md), or [provenance](references/provenance.md) as needed. The retained [3D pipeline](references/three-d-pipeline.md) is only for an explicitly requested 3D source/render task. Audio production uses [audio design](../audio-design/SKILL.md).

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/create-game-assets) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
