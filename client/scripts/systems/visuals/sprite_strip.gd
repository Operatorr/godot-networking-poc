## SpriteStrip - builds looping SpriteFrames from a horizontal spritesheet
## strip (frame width = sheet width / frame count, frame height = sheet
## height). Used for the PixelLab idle animations (fountain, portal).
class_name SpriteStrip
extends RefCounted


static func make_frames(texture: Texture2D, frame_count: int, fps: float) -> SpriteFrames:
	var frames := SpriteFrames.new()
	frames.remove_animation("default")
	frames.add_animation("idle")
	frames.set_animation_speed("idle", fps)
	frames.set_animation_loop("idle", true)

	@warning_ignore("integer_division")  # horizontal strip: frames divide the width evenly
	var frame_width := texture.get_width() / frame_count
	for i in frame_count:
		var atlas := AtlasTexture.new()
		atlas.atlas = texture
		atlas.region = Rect2(i * frame_width, 0, frame_width, texture.get_height())
		frames.add_frame("idle", atlas)
	return frames
