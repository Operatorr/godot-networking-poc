## BaseEntity - abstract base for every rendered, network-visible entity.
##
## Responsibility: the shared client-side spine for anything the server can
## replicate to us — a stable entity id, a coarse "kind" tag (player / monster /
## projectile / world-effect, mirroring the protocol kind byte), and the single
## seam where interpolation/prediction writes the visual transform each frame.
## It renders STATE; it never decides state. Governing rule:
## **the client requests, the server decides** — this node is display only.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. BaseEntity is the "base scene" rung: a Factory hands a
## parsed definition to configure(), which stamps id/kind and any per-kind
## visuals, yielding a configured live entity. Composition over inheritance —
## behaviour (health, AI, patterns) attaches as child components/strategies,
## NOT via deep subclass trees. Live entities (Player, Monster, Projectile)
## predate this base and are not reparented onto it; new entities should be.
##
## Governing docs: docs/gdd/folder-structure.md, docs/gdd/classes/index.md,
## docs/server/contract.md (protocol kinds & id bands).
##
## TODO:
## - Add `entity_id: int` / `kind: int` and validate against the id-band
##   invariants (players 1-999, projectiles 10000-29999, monsters 30000-39999,
##   world-effects 40000-49999).
## - Implement apply_snapshot()/interpolate() as the one render-write seam so
##   InterpolationController and PredictionController never poke the transform
##   directly.
## - Define configure(definition) as the Factory entry point.
class_name BaseEntity
extends Node2D

## Stable server-assigned id; -1 until configured. (See contract.md id bands.)
var entity_id: int = -1

## Protocol kind tag (0 player / 1 monster / 2 projectile / 3 world-effect).
var kind: int = -1


## Factory entry point: stamp identity + per-kind visuals from a parsed
## JSON definition Dictionary. The Factory calls this right after instancing.
# TODO: read id/kind/appearance and configure child components.
func configure(_definition: Dictionary) -> void:
	pass


## Render-write seam: apply one authoritative snapshot for this entity.
# TODO: store from/to keyframes for interpolate().
func apply_snapshot(_snapshot: Dictionary) -> void:
	pass


## Render-write seam: advance the visual transform toward the latest snapshot.
## `t` is the 0..1 blend factor for the current frame.
# TODO: lerp position/rotation; this is the ONLY place the transform is written.
func interpolate(_t: float) -> void:
	pass
