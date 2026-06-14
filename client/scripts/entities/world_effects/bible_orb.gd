## BibleOrb - client view of a Zealot's Spinning Bible (world-effect subtype 3).
##
## Responsibility: render one of the Zealot's orbiting orbs — protocol kind 3,
## subtype **3**, id band **47500–49999**. Server-side 3 orbs orbit the caster
## for 5 s and sweep-damage what they pass through (with re-hit gating); the
## client renders each orb at its server-reported orbit position. This is a
## DEFERRED class effect (the Zealot class is deferred per the GDD); the stub
## keeps the entity taxonomy complete. Governing rule:
## **the client requests, the server decides** — the orbit math that matters,
## the sweep hits, and the lifetime are server-authoritative; this draws the orb.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The WorldEffectFactory instances this subclass for ids in
## the 47500–49999 sub-band. Each orb is a separate world-effect entity in the
## snapshot stream, so the client just renders positions it is given — no local
## orbit simulation is authoritative.
##
## Governing docs: docs/systems/abilities.md (Zealot — Spinning Bibles row),
## docs/server/contract.md (world-effect band), docs/gdd/classes/zealot.md.
##
## TODO (DEFERRED — Zealot class):
## - override configure() to set the orb sprite + trail VFX.
## - the orb position comes from snapshots (apply_snapshot in WorldEffect); any
##   client-side spin is cosmetic only, never authoritative.
class_name BibleOrb
extends WorldEffect

## Cosmetic visual spin rate (radians/sec); purely decorative, not authority.
var visual_spin_rate: float = 0.0
