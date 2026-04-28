extends SceneTree

var _failures := 0


func _init() -> void:
	_test_old_auth_payload_without_color()
	_test_new_auth_payload_with_color()
	_test_player_info_payload_with_color()

	if _failures > 0:
		quit(1)
	else:
		print("[PacketColorTest] All packet color tests passed")
		quit(0)


func _test_old_auth_payload_without_color() -> void:
	var writer := PacketWriter.new()
	writer.write_header(PacketTypes.Type.CONNECT_AUTH)
	writer.write_string("token")
	writer.write_string("char-1")
	writer.write_string("Player")
	writer.write_u8(AuthPacket.Region.ASIA)
	writer.finalize_header()

	var packet := AuthPacket.from_buffer(writer.get_buffer())
	_assert_eq(packet.character_id, "char-1", "old auth character id")
	_assert_color_close(packet.player_color, Color(0.27, 0.53, 1.0), "old auth default color")


func _test_new_auth_payload_with_color() -> void:
	var color := Color(1.0, 0.2, 0.6)
	var packet := AuthPacket.create("token", "char-2", "PlayerTwo", AuthPacket.Region.US_WEST, color)
	var decoded := AuthPacket.from_buffer(packet.write())

	_assert_eq(decoded.character_name, "PlayerTwo", "new auth character name")
	_assert_color_close(decoded.player_color, Color(1.0, 51.0 / 255.0, 153.0 / 255.0), "new auth color")


func _test_player_info_payload_with_color() -> void:
	var color := Color(0.1, 0.8, 0.3)
	var event := GameEventPacket.create_player_info(42, "ColorPlayer", Vector2(12.5, -6.0), color)
	var decoded := GameEventPacket.from_buffer(event.write())
	var event_data: Dictionary = decoded.event_data

	_assert_eq(decoded.target_id, 42, "player info target")
	_assert_eq(event_data.get("character_name"), "ColorPlayer", "player info name")
	_assert_eq(event_data.get("position"), Vector2(12.5, -6.0), "player info position")
	_assert_color_close(event_data.get("player_color"), Color(26.0 / 255.0, 204.0 / 255.0, 77.0 / 255.0), "player info color")


func _assert_eq(actual: Variant, expected: Variant, label: String) -> void:
	if actual == expected:
		return
	_failures += 1
	push_error("[PacketColorTest] %s expected %s, got %s" % [label, expected, actual])


func _assert_color_close(actual: Color, expected: Color, label: String) -> void:
	if absf(actual.r - expected.r) <= 0.01 \
		and absf(actual.g - expected.g) <= 0.01 \
		and absf(actual.b - expected.b) <= 0.01:
		return
	_failures += 1
	push_error("[PacketColorTest] %s expected %s, got %s" % [label, expected, actual])
