## ProceduralSprites - Generates all game sprites and animations procedurally
## Aesthetic: Cosmic horror painterly - asymmetric organic shapes, bioluminescent cores,
## arterial reds, bruised purples, electric blues, sickly greens
class_name ProceduralSprites
extends RefCounted

# ─── COLOR PALETTE ───

# Player (local) - Electric blue with bioluminescent veins
const PLAYER_CORE := Color(0.27, 0.53, 1.0)       # #4488ff
const PLAYER_GLOW := Color(0.4, 1.0, 0.8)          # #66ffcc
const PLAYER_SHELL := Color(0.08, 0.12, 0.2)       # Dark outer shell

# Player (remote) - Sickly purple with pale glow
const REMOTE_CORE := Color(0.6, 0.27, 0.8)         # #9944cc
const REMOTE_GLOW := Color(0.8, 0.6, 1.0)          # Pale purple glow
const REMOTE_SHELL := Color(0.15, 0.06, 0.18)

# Monster - Arterial red with wrong bioluminescent green
const MONSTER_CORE := Color(0.8, 0.13, 0.13)       # #cc2222
const MONSTER_GLOW := Color(0.27, 1.0, 0.27)       # #44ff44 bioluminescent
const MONSTER_SHELL := Color(0.18, 0.04, 0.04)

# Projectile - Astral energy
const PROJ_CENTER := Color(1.0, 1.0, 1.0)          # White hot
const PROJ_MID := Color(0.27, 0.53, 1.0)           # Electric blue
const PROJ_CORONA := Color(1.0, 0.8, 0.27)         # Gold corona

# Arena
const FLOOR_COLOR := Color(0.06, 0.04, 0.04, 1.0)
const VEIN_COLOR := Color(0.16, 0.08, 0.14, 1.0)
const BORDER_COLOR := Color(0.6, 0.1, 0.1, 1.0)


# ─── PLAYER SPRITE GENERATION ───

## Create SpriteFrames for local player
static func create_player_frames() -> SpriteFrames:
	return _create_entity_frames(PLAYER_CORE, PLAYER_GLOW, PLAYER_SHELL, true)


## Create SpriteFrames for remote player
static func create_remote_player_frames() -> SpriteFrames:
	return _create_entity_frames(REMOTE_CORE, REMOTE_GLOW, REMOTE_SHELL, true)


## Create SpriteFrames for monster
static func create_monster_frames() -> SpriteFrames:
	return _create_entity_frames(MONSTER_CORE, MONSTER_GLOW, MONSTER_SHELL, false, true)


## Create projectile texture
static func create_projectile_texture(size: int = 16) -> ImageTexture:
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)
	var max_r := size / 2.0

	for y in range(size):
		for x in range(size):
			var dist := Vector2(x, y).distance_to(center)
			var norm := dist / max_r

			if norm > 1.0:
				img.set_pixel(x, y, Color(0, 0, 0, 0))
			elif norm < 0.25:
				# White-hot center
				var t := norm / 0.25
				var c := PROJ_CENTER.lerp(PROJ_MID, t * t)
				c.a = 1.0
				img.set_pixel(x, y, c)
			elif norm < 0.6:
				# Blue to gold transition
				var t := (norm - 0.25) / 0.35
				var c := PROJ_MID.lerp(PROJ_CORONA, t)
				c.a = 1.0 - t * 0.3
				img.set_pixel(x, y, c)
			else:
				# Outer corona fade
				var t := (norm - 0.6) / 0.4
				var c := PROJ_CORONA
				c.a = (1.0 - t) * 0.5
				img.set_pixel(x, y, c)

	return ImageTexture.create_from_image(img)


## Create a second projectile frame (slightly pulsed)
static func create_projectile_texture_pulse(size: int = 16) -> ImageTexture:
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)
	var max_r := size / 2.0

	for y in range(size):
		for x in range(size):
			var dist := Vector2(x, y).distance_to(center)
			var norm := dist / max_r

			if norm > 1.0:
				img.set_pixel(x, y, Color(0, 0, 0, 0))
			elif norm < 0.35:
				# Expanded white-hot center (pulsed)
				var t := norm / 0.35
				var c := PROJ_CENTER.lerp(PROJ_MID, t * t)
				c.a = 1.0
				img.set_pixel(x, y, c)
			elif norm < 0.65:
				var t := (norm - 0.35) / 0.3
				var c := PROJ_MID.lerp(PROJ_CORONA, t)
				c.a = 1.0 - t * 0.2
				img.set_pixel(x, y, c)
			else:
				var t := (norm - 0.65) / 0.35
				var c := PROJ_CORONA
				c.a = (1.0 - t) * 0.6
				img.set_pixel(x, y, c)

	return ImageTexture.create_from_image(img)


# ─── INTERNAL: Entity Frame Generation ───

static func _create_entity_frames(core_color: Color, glow_color: Color, shell_color: Color, is_humanoid: bool, is_monster: bool = false) -> SpriteFrames:
	var frames := SpriteFrames.new()

	# Remove default animation if present
	if frames.has_animation("default"):
		frames.remove_animation("default")

	# idle: 2 frames (breathing pulse)
	frames.add_animation("idle")
	frames.set_animation_speed("idle", 3.0)
	frames.set_animation_loop("idle", true)
	frames.add_frame("idle", _create_entity_texture(core_color, glow_color, shell_color, is_humanoid, is_monster, 0.0))
	frames.add_frame("idle", _create_entity_texture(core_color, glow_color, shell_color, is_humanoid, is_monster, 0.3))

	# walk: 4 frames (shambling motion)
	frames.add_animation("walk")
	frames.set_animation_speed("walk", 8.0)
	frames.set_animation_loop("walk", true)
	for i in range(4):
		var phase := float(i) / 4.0
		frames.add_frame("walk", _create_walk_texture(core_color, glow_color, shell_color, is_humanoid, is_monster, phase))

	# attack: 3 frames (violent extension + recoil)
	frames.add_animation("attack")
	frames.set_animation_speed("attack", 12.0)
	frames.set_animation_loop("attack", false)
	frames.add_frame("attack", _create_attack_texture(core_color, glow_color, shell_color, is_humanoid, is_monster, 0))
	frames.add_frame("attack", _create_attack_texture(core_color, glow_color, shell_color, is_humanoid, is_monster, 1))
	frames.add_frame("attack", _create_attack_texture(core_color, glow_color, shell_color, is_humanoid, is_monster, 2))

	# hit: 2 frames (damage flash)
	frames.add_animation("hit")
	frames.set_animation_speed("hit", 10.0)
	frames.set_animation_loop("hit", false)
	frames.add_frame("hit", _create_hit_texture(core_color, shell_color, 0))
	frames.add_frame("hit", _create_hit_texture(core_color, shell_color, 1))

	# death: 4 frames (body tears apart)
	frames.add_animation("death")
	frames.set_animation_speed("death", 6.0)
	frames.set_animation_loop("death", false)
	for i in range(4):
		frames.add_frame("death", _create_death_texture(core_color, glow_color, shell_color, is_monster, i))

	# spawn: 3 frames (dimensional tear → coalesce) - monster only but safe for all
	frames.add_animation("spawn")
	frames.set_animation_speed("spawn", 8.0)
	frames.set_animation_loop("spawn", false)
	for i in range(3):
		frames.add_frame("spawn", _create_spawn_texture(core_color, glow_color, shell_color, is_monster, i))

	return frames


# ─── TEXTURE GENERATORS ───

static func _create_entity_texture(core_color: Color, glow_color: Color, shell_color: Color, is_humanoid: bool, is_monster: bool, pulse: float) -> ImageTexture:
	var size := 32
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)

	# Draw the base organic shape
	for y in range(size):
		for x in range(size):
			var pos := Vector2(x, y)
			var dist := pos.distance_to(center)
			var angle := (pos - center).angle()

			# Organic radius with asymmetric wobble
			var base_r := 12.0 + pulse * 1.5
			var wobble := sin(angle * 3.0 + 0.7) * 2.0 + sin(angle * 5.0 - 0.3) * 1.0
			if is_monster:
				# Spikier, more angular
				wobble += sin(angle * 7.0 + 1.2) * 2.5 + abs(sin(angle * 4.0)) * 1.5
			var radius := base_r + wobble

			if dist > radius + 2.0:
				img.set_pixel(x, y, Color(0, 0, 0, 0))
			elif dist > radius:
				# Edge glow
				var edge_t := (dist - radius) / 2.0
				var c := glow_color
				c.a = (1.0 - edge_t) * 0.6
				img.set_pixel(x, y, c)
			elif dist > radius * 0.7:
				# Shell
				var t := (dist - radius * 0.7) / (radius * 0.3)
				var c := shell_color.lerp(glow_color, t * 0.2)
				c.a = 1.0
				img.set_pixel(x, y, c)
			elif dist > radius * 0.35:
				# Inner body
				var t := (dist - radius * 0.35) / (radius * 0.35)
				var c := core_color.lerp(shell_color, t * 0.6)
				c.a = 1.0
				img.set_pixel(x, y, c)
			else:
				# Bioluminescent core
				var t := dist / (radius * 0.35)
				var c := glow_color.lerp(core_color, t)
				c.a = 1.0
				img.set_pixel(x, y, c)

	# Add directional indicator for humanoids (facing right)
	if is_humanoid:
		_draw_direction_indicator(img, center, core_color)

	# Add asymmetric eyes for monsters
	if is_monster:
		_draw_monster_eyes(img, center, glow_color)

	return ImageTexture.create_from_image(img)


static func _draw_direction_indicator(img: Image, center: Vector2, color: Color) -> void:
	# Small bright triangle pointing right from center
	var tip := Vector2i(int(center.x) + 14, int(center.y))
	var base_top := Vector2i(int(center.x) + 8, int(center.y) - 3)
	var base_bot := Vector2i(int(center.x) + 8, int(center.y) + 3)

	# Fill triangle pixels
	for py in range(base_top.y, base_bot.y + 1):
		var t := float(py - base_top.y) / float(base_bot.y - base_top.y) if base_bot.y != base_top.y else 0.5
		var x_start := base_top.x
		# Simple: draw from base_x to interpolated tip
		var row_end := int(lerpf(float(base_top.x), float(tip.x), 1.0 - abs(t * 2.0 - 1.0)))
		for px in range(x_start, mini(row_end + 1, 32)):
			if px >= 0 and px < 32 and py >= 0 and py < 32:
				var c := color
				c.a = 0.9
				img.set_pixel(px, py, c)


static func _draw_monster_eyes(img: Image, center: Vector2, glow_color: Color) -> void:
	# Asymmetric eyes - deliberately wrong placement
	var eye_positions: Array[Vector2i] = [
		Vector2i(int(center.x) + 3, int(center.y) - 4),
		Vector2i(int(center.x) + 5, int(center.y) - 1),
		Vector2i(int(center.x) + 2, int(center.y) + 3),  # Third eye, unsettling
	]
	for eye_pos in eye_positions:
		for dy in range(-1, 2):
			for dx in range(-1, 2):
				var px: int = eye_pos.x + dx
				var py: int = eye_pos.y + dy
				if px >= 0 and px < 32 and py >= 0 and py < 32:
					var dist := Vector2(dx, dy).length()
					if dist < 1.5:
						var c := glow_color
						c.a = 1.0 - dist * 0.3
						img.set_pixel(px, py, c)


static func _create_walk_texture(core_color: Color, glow_color: Color, shell_color: Color, is_humanoid: bool, is_monster: bool, phase: float) -> ImageTexture:
	# Walking = base shape with limb-shift wobble
	var size := 32
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)
	var bob_y := sin(phase * TAU) * 1.5
	var bob_x := cos(phase * TAU) * 0.8
	var shifted_center := center + Vector2(bob_x, bob_y)

	for y in range(size):
		for x in range(size):
			var pos := Vector2(x, y)
			var dist := pos.distance_to(shifted_center)
			var angle := (pos - shifted_center).angle()

			var base_r := 12.0
			var wobble := sin(angle * 3.0 + phase * TAU) * 2.5 + sin(angle * 5.0 - 0.3) * 1.0
			if is_monster:
				wobble += sin(angle * 7.0 + phase * TAU + 1.2) * 2.5
			var radius := base_r + wobble

			if dist > radius + 2.0:
				img.set_pixel(x, y, Color(0, 0, 0, 0))
			elif dist > radius:
				var c := glow_color
				c.a = (1.0 - (dist - radius) / 2.0) * 0.6
				img.set_pixel(x, y, c)
			elif dist > radius * 0.7:
				var t := (dist - radius * 0.7) / (radius * 0.3)
				var c := shell_color.lerp(glow_color, t * 0.2)
				c.a = 1.0
				img.set_pixel(x, y, c)
			elif dist > radius * 0.35:
				var t := (dist - radius * 0.35) / (radius * 0.35)
				var c := core_color.lerp(shell_color, t * 0.6)
				c.a = 1.0
				img.set_pixel(x, y, c)
			else:
				var t := dist / (radius * 0.35)
				var c := glow_color.lerp(core_color, t)
				c.a = 1.0
				img.set_pixel(x, y, c)

	if is_humanoid:
		_draw_direction_indicator(img, center, core_color)
	if is_monster:
		_draw_monster_eyes(img, shifted_center, glow_color)

	return ImageTexture.create_from_image(img)


static func _create_attack_texture(core_color: Color, glow_color: Color, _shell_color: Color, is_humanoid: bool, is_monster: bool, frame: int) -> ImageTexture:
	var size := 32
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)

	# Frame 0: extension (stretch right), Frame 1: energy flash, Frame 2: recoil
	var stretch_x: float = [3.0, 0.0, -2.0][frame]
	var flash_alpha: float = [0.0, 0.8, 0.2][frame]

	for y in range(size):
		for x in range(size):
			var adjusted := Vector2(x - stretch_x * 0.5, y)
			var dist := adjusted.distance_to(center)
			var angle := (adjusted - center).angle()

			var base_r: float = 12.0 + stretch_x * 0.3
			var wobble := sin(angle * 3.0 + 0.7) * 2.0 + sin(angle * 5.0) * 1.5
			if is_monster:
				wobble += sin(angle * 7.0 + 1.2) * 2.0
			var radius: float = base_r + wobble

			if dist > radius + 2.0:
				# Energy discharge on frame 1
				if frame == 1 and dist < radius + 6.0:
					var c := glow_color
					c.a = (1.0 - (dist - radius) / 6.0) * 0.4
					img.set_pixel(x, y, c)
				else:
					img.set_pixel(x, y, Color(0, 0, 0, 0))
			elif dist > radius:
				var c := glow_color
				c.a = (1.0 - (dist - radius) / 2.0) * 0.8
				img.set_pixel(x, y, c)
			else:
				var t: float = dist / radius
				var c := glow_color.lerp(core_color, t)
				# Flash overlay
				c = c.lerp(Color.WHITE, flash_alpha * (1.0 - t))
				c.a = 1.0
				img.set_pixel(x, y, c)

	if is_humanoid:
		_draw_direction_indicator(img, center, core_color)

	return ImageTexture.create_from_image(img)


static func _create_hit_texture(core_color: Color, shell_color: Color, frame: int) -> ImageTexture:
	var size := 32
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)

	# Frame 0: bright white flash, Frame 1: red overlay returning
	var flash := Color.WHITE if frame == 0 else Color(1.0, 0.2, 0.1)
	var flash_strength := 0.9 if frame == 0 else 0.4

	for y in range(size):
		for x in range(size):
			var pos := Vector2(x, y)
			var dist := pos.distance_to(center)
			var angle := (pos - center).angle()

			var radius := 12.0 + sin(angle * 3.0 + 0.7) * 2.0 + sin(angle * 5.0 - 0.3) * 1.0

			if dist > radius + 2.0:
				img.set_pixel(x, y, Color(0, 0, 0, 0))
			elif dist > radius:
				var c := flash
				c.a = (1.0 - (dist - radius) / 2.0) * 0.5
				img.set_pixel(x, y, c)
			else:
				var t := dist / radius
				var base_c := core_color.lerp(shell_color, t)
				var c := base_c.lerp(flash, flash_strength * (1.0 - t * 0.5))
				c.a = 1.0
				img.set_pixel(x, y, c)

	return ImageTexture.create_from_image(img)


static func _create_death_texture(core_color: Color, glow_color: Color, _shell_color: Color, is_monster: bool, frame: int) -> ImageTexture:
	var size := 32
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)

	# Frame 0: intact + flash, 1: fragmenting, 2: scattered, 3: fading
	var scale_factor: float = [1.0, 0.8, 0.5, 0.2][frame]
	var alpha_mult: float = [1.0, 0.9, 0.6, 0.2][frame]
	var fragment_spread: float = [0.0, 3.0, 8.0, 14.0][frame]

	if frame == 0:
		# White flash death frame
		for y in range(size):
			for x in range(size):
				var dist := Vector2(x, y).distance_to(center)
				var radius := 13.0
				if dist > radius:
					img.set_pixel(x, y, Color(0, 0, 0, 0))
				else:
					var c := Color.WHITE.lerp(core_color, dist / radius)
					c.a = 1.0
					img.set_pixel(x, y, c)
	else:
		# Fragment into pieces
		var num_frags := 5 if is_monster else 4
		# Use deterministic positions based on frame
		for frag in range(num_frags):
			var frag_angle := float(frag) / num_frags * TAU + 0.5
			var frag_offset: Vector2 = Vector2(cos(frag_angle), sin(frag_angle)) * fragment_spread
			var frag_center: Vector2 = center + frag_offset
			var frag_radius: float = 5.0 * scale_factor

			for y in range(size):
				for x in range(size):
					var dist := Vector2(x, y).distance_to(frag_center)
					if dist < frag_radius:
						var t: float = dist / frag_radius
						var c := core_color.lerp(glow_color, t)
						c.a = (1.0 - t) * alpha_mult
						if c.a > 0.05:
							# Only overwrite if more opaque
							var existing := img.get_pixel(x, y)
							if c.a > existing.a:
								img.set_pixel(x, y, c)

	return ImageTexture.create_from_image(img)


static func _create_spawn_texture(core_color: Color, glow_color: Color, _shell_color: Color, _is_monster: bool, frame: int) -> ImageTexture:
	var size := 32
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size / 2.0, size / 2.0)

	# Frame 0: dimensional tear (thin line), 1: coalescing, 2: nearly solid
	var scale: float = [0.15, 0.6, 0.95][frame]
	var noise_amount: float = [0.8, 0.4, 0.1][frame]

	for y in range(size):
		for x in range(size):
			var pos := Vector2(x, y)
			var dist := pos.distance_to(center)
			var angle := (pos - center).angle()

			var radius: float = 13.0 * scale
			var wobble: float = sin(angle * 5.0 + frame * 2.0) * 3.0 * noise_amount

			if frame == 0:
				# Dimensional tear: thin vertical rift
				var dx: float = abs(pos.x - center.x)
				var dy: float = abs(pos.y - center.y)
				if dx < 2.0 and dy < 10.0:
					var t: float = dy / 10.0
					var c := glow_color.lerp(Color.WHITE, 1.0 - t)
					c.a = 0.8
					img.set_pixel(x, y, c)
				elif dx < 4.0 and dy < 8.0:
					var c := core_color
					c.a = 0.3
					img.set_pixel(x, y, c)
				else:
					img.set_pixel(x, y, Color(0, 0, 0, 0))
			else:
				if dist > radius + wobble + 2.0:
					img.set_pixel(x, y, Color(0, 0, 0, 0))
				elif dist > radius + wobble:
					var c := glow_color
					c.a = (1.0 - (dist - radius - wobble) / 2.0) * 0.5
					img.set_pixel(x, y, c)
				else:
					var t := dist / maxf(radius + wobble, 0.01)
					var c := glow_color.lerp(core_color, t)
					c.a = scale
					img.set_pixel(x, y, c)

	return ImageTexture.create_from_image(img)
