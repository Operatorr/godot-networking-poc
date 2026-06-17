## BlastEffect — transient AoE detonation VFX for an ability blast (Warrior Charge
## impact, Mage Mageblast, …). Cosmetic only; the server owns the real damage.
##
## Plays a one-shot PixelLab sprite animation (SheetLibrary effect sheet, single
## non-directional "blast" row) scaled to the blast radius, then self-frees on
## animation_finished. When the sprite sheet is absent it falls back to the old
## procedural expanding ring so the effect always renders (and the game still
## runs before the art is assembled).
##
## Used by the online ABILITY_EFFECT path (arena_base) and the offline RMB
## preview (offline_ability) so both show the same detonation art.
class_name BlastEffect
extends Node2D

## Visual radius (world units) the blast art is scaled to cover.
var radius: float = 80.0
## SheetLibrary effect key ("charge_blast", "mageblast"); "" forces the ring fallback.
var effect_key: String = ""
## Ring-fallback colours (also a sensible flash tint), used when no sheet exists.
var fill_color: Color = Color(1.0, 0.6, 0.2)
var ring_color: Color = Color(1.0, 0.8, 0.4)

## Sprite art is authored a little larger than the gameplay radius so the fiery
## edge reaches the AoE rim rather than stopping short of it.
const SPRITE_COVER := 1.2
const RING_DURATION := 0.4

var _ring_t := 0.0
var _is_ring := false


## Build a detonation at `world_pos`. `key` selects the sprite sheet; pass "" (or
## a key with no assembled sheet) to use the procedural ring with the given colours.
static func create(
	key: String, world_pos: Vector2, target_radius: float,
	fill: Color = Color(1.0, 0.6, 0.2), ring: Color = Color(1.0, 0.8, 0.4)
) -> BlastEffect:
	var b := BlastEffect.new()
	b.effect_key = key
	b.position = world_pos
	b.radius = maxf(target_radius, 8.0)
	b.fill_color = fill
	b.ring_color = ring
	return b


func _ready() -> void:
	# Render the detonation BELOW the player/entities (a charge blast goes off at
	# the warrior's feet — keep the character visible on top, reading as a ground
	# shockwave). z stays at 0 (NOT negative — that would drop it under the arena's
	# own _draw() floor, see arena_base.gd); being first in the parent's children
	# puts it under the (later-drawn) entities while staying above the floor.
	z_index = 0
	var parent := get_parent()
	if parent != null:
		parent.move_child(self, 0)
	var frames: SpriteFrames = null
	if not effect_key.is_empty():
		frames = SheetLibrary.effect_frames(effect_key)
	if frames != null and frames.has_animation("blast"):
		_build_sprite(frames)
	else:
		_is_ring = true
		set_process(true)


func _build_sprite(frames: SpriteFrames) -> void:
	var spr := AnimatedSprite2D.new()
	spr.sprite_frames = frames
	spr.animation = "blast"
	spr.centered = true
	var tex := frames.get_frame_texture("blast", 0)
	var frame_px := 64.0
	if tex != null:
		frame_px = maxf(tex.get_size().x, tex.get_size().y)
	spr.scale = Vector2.ONE * (2.0 * radius * SPRITE_COVER / maxf(frame_px, 1.0))
	add_child(spr)
	spr.play("blast")
	spr.animation_finished.connect(func() -> void:
		if is_instance_valid(self):
			queue_free()
	)
	# Safety free in case animation_finished is missed (e.g. a looping alias).
	var dur := float(frames.get_frame_count("blast")) / maxf(frames.get_animation_speed("blast"), 1.0)
	var tree := get_tree()
	if tree != null:
		tree.create_timer(dur + 0.25).timeout.connect(func() -> void:
			if is_instance_valid(self):
				queue_free()
		)


## Procedural fallback: an expanding twin-ring + fading fill, self-frees after RING_DURATION.
func _process(delta: float) -> void:
	if not _is_ring:
		return
	_ring_t += delta
	if _ring_t >= RING_DURATION:
		queue_free()
		return
	queue_redraw()


func _draw() -> void:
	if not _is_ring:
		return
	var t := clampf(_ring_t / RING_DURATION, 0.0, 1.0)
	var alpha := 1.0 - t
	var r := radius * (0.2 + 0.8 * t)
	var fill := fill_color
	fill.a = 0.30 * alpha
	var ring := ring_color
	ring.a = 0.9 * alpha
	draw_circle(Vector2.ZERO, r, fill)
	draw_arc(Vector2.ZERO, r, 0.0, TAU, 48, ring, 3.0)
	var inner := ring
	inner.a = 0.5 * alpha
	draw_arc(Vector2.ZERO, r * 0.6, 0.0, TAU, 36, inner, 2.0)
