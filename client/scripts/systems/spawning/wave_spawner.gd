## WaveSpawner - Offline-mode wave spawner for sandbox / practice.
##
## Drives timed monster waves in OFFLINE practice/sandbox scenes only, where there
## is no authoritative server to mirror. In online play the server owns all spawns
## (the client requests, the server decides) and this node stays disabled — it is a
## local-only training tool, never a source of authoritative state.
##
## Patterns: Strategy (a swappable wave-selection policy: fixed, escalating, endless)
## + Template Method (a fixed spawn loop whose per-wave steps are filled by the
## strategy). Data-driven (GDD: JSON definition -> Factory -> base scene -> configured
## entity): wave composition comes from a wave JSON definition; each monster is built
## by the monster Factory from its JSON def, then placed via SpawnSystem.
##
## Governing docs: docs/gdd/game-modes.md (practice/sandbox), docs/gdd/MONSTERS.md,
## docs/gdd/folder-structure.md.
##
## # TODO:
##   - Define the wave-definition shape (count, types, interval, spawn region).
##   - Implement Strategy hook for choosing the next wave; Template loop to run it.
##   - Drive spawns through SpawnSystem + the monster Factory (no direct instancing).
##   - Gate hard to offline mode; assert it never runs while connected.
class_name WaveSpawner
extends Node


## Begin spawning waves using the configured strategy (offline only).
func start_waves(wave_config: Dictionary) -> void:
	# TODO: load wave defs, init strategy, kick off the template spawn loop.
	pass


## Stop the wave loop and clear any pending timers.
func stop_waves() -> void:
	# TODO: halt loop; cancel timers.
	pass


## Spawn one wave by index (Template step filled by the active Strategy).
func spawn_wave(wave_index: int) -> void:
	# TODO: resolve composition; for each monster -> Factory -> SpawnSystem.
	pass
