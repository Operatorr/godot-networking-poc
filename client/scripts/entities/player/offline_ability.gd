## OfflineAbilityPreview — local-only RMB ability visuals for the Sanctuary / offline modes.
##
## The real class abilities are server-authoritative (Mageblast, bibles, charge, …), so RMB does
## nothing in the offline hub except spend mana. This gives RMB visible per-class feedback for
## testing class FEEL in the Sanctuary: it spawns cosmetic visuals only — no damage, no entities,
## no networking. Online, the authoritative ABILITY_EFFECT events drive the real visuals instead.
class_name OfflineAbilityPreview
extends RefCounted

const BIBLE_DURATION := 5.0
const ZONE_DURATION := 5.0
const STEALTH_DURATION := 5.0


## Spawn the class's preview. `world` hosts world-space visuals (burst/zone); orbiting visuals
## attach to `player` so they follow it. `cursor` is the mouse world position.
static func play(world: Node, player: Node2D, class_id: int, cursor: Vector2) -> void:
	if world == null or not is_instance_valid(world) or player == null or not is_instance_valid(player):
		return
	var ppos: Vector2 = player.global_position
	match class_id:
		PacketTypes.PlayerClass.ZEALOT:
			# 3 spinning "bibles" orbiting the player (Vampire-Survivors feel).
			player.add_child(_make_orbit(3, 80.0, BIBLE_DURATION, Color(0.97, 0.9, 0.55)))
		PacketTypes.PlayerClass.MAGE:
			world.add_child(_make_burst(cursor, 144.0, 0.45, Color(0.55, 0.78, 1.0)))
			_play_mageblast_sfx(player)
		PacketTypes.PlayerClass.VOID_HUNTER:
			var dir := _dir(ppos, cursor)
			world.add_child(_make_spread(ppos, dir, 5, deg_to_rad(28.0), 360.0, Color(0.72, 0.97, 0.8)))
		PacketTypes.PlayerClass.ENGINEER:
			# A mine marker that "detonates" into a blast after a short arm delay.
			world.add_child(_make_mine(ppos, 120.0, Color(0.88, 0.34, 0.32)))
		PacketTypes.PlayerClass.PLAGUE_SEER:
			world.add_child(_make_zone(cursor, 100.0, ZONE_DURATION, Color(0.62, 0.32, 0.78)))
		PacketTypes.PlayerClass.WARRIOR:
			var dir := _dir(ppos, cursor)
			world.add_child(_make_burst(ppos + dir * 220.0, 120.0, 0.5, Color(1.0, 0.62, 0.22)))
		PacketTypes.PlayerClass.ROGUE:
			if player.has_method("apply_stealth_preview"):
				player.apply_stealth_preview(STEALTH_DURATION)
		_:
			world.add_child(_make_burst(cursor, 90.0, 0.4, Color.WHITE))


## Play the Mageblast detonation SFX via the AudioManager autoload (offline preview parity with
## the online ABILITY_EFFECT path). Resolved through the tree so this stays a pure static helper.
static func _play_mageblast_sfx(node: Node) -> void:
	if node == null or not is_instance_valid(node):
		return
	var audio := node.get_tree().root.get_node_or_null("AudioManager")
	if audio != null and audio.has_method("play_sfx"):
		audio.play_sfx("mageblast", AudioManager.AudioCategory.SFX_PLAYER)


static func _dir(from: Vector2, to: Vector2) -> Vector2:
	var d := to - from
	return d.normalized() if d.length() > 1.0 else Vector2.RIGHT


static func _make_burst(pos: Vector2, radius: float, duration: float, color: Color) -> Node2D:
	var v := _Vfx.new()
	v.mode = "burst"
	v.global_position = pos
	v.radius = radius
	v.duration = duration
	v.color = color
	return v


static func _make_zone(pos: Vector2, radius: float, duration: float, color: Color) -> Node2D:
	var v := _Vfx.new()
	v.mode = "zone"
	v.global_position = pos
	v.radius = radius
	v.duration = duration
	v.color = color
	return v


static func _make_orbit(count: int, orbit_radius: float, duration: float, color: Color) -> Node2D:
	var v := _Vfx.new()
	v.mode = "orbit"
	v.count = count
	v.orbit_radius = orbit_radius
	v.duration = duration
	v.color = color
	return v


static func _make_spread(pos: Vector2, dir: Vector2, count: int, spread: float, length: float, color: Color) -> Node2D:
	var v := _Vfx.new()
	v.mode = "spread"
	v.global_position = pos
	v.count = count
	v.spread = spread
	v.radius = length
	v.dir_angle = dir.angle()
	v.duration = 0.35
	v.color = color
	return v


static func _make_mine(pos: Vector2, blast_radius: float, color: Color) -> Node2D:
	var v := _Vfx.new()
	v.mode = "mine"
	v.global_position = pos
	v.radius = blast_radius
	v.duration = 1.2          # arm (0.8) then a 0.4 s blast
	v.color = color
	return v


## Generic cosmetic visual: expanding burst / fading zone / orbiting dots / spread tracers /
## mine-then-blast. Self-frees after `duration`.
class _Vfx extends Node2D:
	var mode := "burst"
	var radius := 100.0
	var duration := 0.45
	var color := Color.WHITE
	var count := 3
	var orbit_radius := 80.0
	var spread := 0.0
	var dir_angle := 0.0
	var _t := 0.0

	func _ready() -> void:
		z_index = 50
		set_process(true)

	func _process(delta: float) -> void:
		_t += delta
		if _t >= duration:
			queue_free()
			return
		queue_redraw()

	func _draw() -> void:
		var p := clampf(_t / maxf(duration, 0.001), 0.0, 1.0)
		match mode:
			"burst":
				var a := 1.0 - p
				draw_arc(Vector2.ZERO, radius * p, 0.0, TAU, 40, Color(color.r, color.g, color.b, a), 3.0)
				draw_circle(Vector2.ZERO, radius * p, Color(color.r, color.g, color.b, a * 0.18))
			"zone":
				var fade := 0.30 * (1.0 if p < 0.85 else (1.0 - (p - 0.85) / 0.15))
				draw_circle(Vector2.ZERO, radius, Color(color.r, color.g, color.b, fade))
				draw_arc(Vector2.ZERO, radius, 0.0, TAU, 48, Color(color.r, color.g, color.b, 0.6), 2.0)
			"orbit":
				for i in count:
					var ang := TAU * float(i) / float(maxi(count, 1)) + _t * 3.0
					var pos := Vector2(cos(ang), sin(ang)) * orbit_radius
					draw_circle(pos, 7.0, color)
					draw_arc(pos, 7.0, 0.0, TAU, 12, Color(1, 1, 1, 0.6), 1.5)
			"spread":
				var a := 1.0 - p
				var reach := radius * clampf(p * 1.5, 0.0, 1.0)
				for i in count:
					var t := (float(i) / float(maxi(count - 1, 1))) - 0.5
					var ang := dir_angle + t * spread
					var d := Vector2(cos(ang), sin(ang))
					draw_line(d * 12.0, d * reach, Color(color.r, color.g, color.b, a), 2.5)
			"mine":
				if _t < 0.8:
					# Armed marker: a small blinking dark-red disc.
					var blink := 0.5 + 0.5 * sin(_t * 18.0)
					draw_circle(Vector2.ZERO, 8.0, Color(color.r, color.g, color.b, 0.5 + 0.4 * blink))
				else:
					var bp := (_t - 0.8) / 0.4
					var a := 1.0 - bp
					draw_arc(Vector2.ZERO, radius * bp, 0.0, TAU, 40, Color(color.r, color.g, color.b, a), 3.0)
					draw_circle(Vector2.ZERO, radius * bp, Color(color.r, color.g, color.b, a * 0.2))
