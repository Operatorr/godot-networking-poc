extends Node


func _ready() -> void:
	for kind in ["health", "mana", "stamina"]:
		var bar: Control = load("res://scenes/ui/hud/%s_bar.tscn" % kind).instantiate()
		add_child(bar)
		await get_tree().process_frame
		var fill: TextureProgressBar = bar.get_node("Fill")
		var trough := Rect2(10, 6, 298, 6) if kind == "stamina" else Rect2(46, 13, 233, 19)
		if not _check(fill.nine_patch_stretch, "%s must stretch its texture to the trough" % kind):
			return
		if not _check(fill.get_rect().is_equal_approx(trough), "%s fill %s exceeds its trough %s" % [kind, fill.get_rect(), trough]):
			return
		# The overlay must leave the whole trough transparent, including its far edge.
		var frame: TextureRect = bar.get_node("Frame")
		var pixels := frame.texture.get_image()
		for point in [trough.position + Vector2.ONE, trough.end - Vector2.ONE]:
			if not _check(pixels.get_pixelv(Vector2i(point)).a < 0.01, "%s frame obscures fill at %s" % [kind, point]):
				return
		for current in [-20, 0, 40, 100, 150]:
			if kind == "health":
				bar.update_hp(current, 100)
			else:
				bar.update_value(current, 100)
			if not _check(is_equal_approx(fill.value, clampf(current / 100.0, 0, 1)), "%s incorrect fill at %d" % [kind, current]):
				return
			if not _check(fill.get_rect().is_equal_approx(trough), "%s trough changed with value" % kind):
				return
		bar.queue_free()
	print("[HUDBarRegression] PASS: all three bars; complete trough geometry, transparent frames, clamped values")
	get_tree().quit(0)


func _check(ok: bool, message: String) -> bool:
	if not ok:
		push_error(message)
		get_tree().quit(1)
	return ok
