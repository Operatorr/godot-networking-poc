## SanctuaryProps — code-generated placeholder prop renderer for the redesigned, grim Sanctuary
## town (a dying gothic pilgrim city). One node per prop: set `kind` + `palette`, it draws an
## oblique 3/4 placeholder via _draw(). Every prop is tagged for later art replacement by the
## builder. The 90 _draw_<kind>() bodies were authored against docs/design/sanctuary-layout.md
## (see SanctuaryTownWorld). COLLIDERS/FX drive solid colliders and shader/particle wiring.
##
## Coordinate convention: origin (0,0) is the ground-contact point; the body is built UPWARD
## into negative y (so the wind-sway shader can pin the base). Decals draw flat with low alpha.
class_name SanctuaryProps
extends Node2D

var kind: String = "crate"
var palette: Dictionary = {}


## Grim base palette (redesign spec §8). The builder passes its own copy; this default keeps a
## bare SanctuaryProps (e.g. an offline preview) self-sufficient.
static func default_palette() -> Dictionary:
	var umber := Color("3a211a")
	var ash := Color("555852")
	var iron := Color("252928")
	return {
		"abyss": Color("050706"), "iron": iron, "ash": ash, "umber": umber,
		"blood": Color("4a1512"), "rust": Color("8a261f"), "gold": Color("9b7428"),
		"bone": Color("d8d0bc"), "taupe": Color("7a6253"), "sulfur": Color("c69a2e"),
		"violet": Color("5b3a8e"), "eldritch": Color("2b183d"), "magenta": Color("8a2d55"),
		"vblue": Color("1d3557"), "teal": Color("1c6c73"),
		"wood": umber.lightened(0.12), "wood_dark": umber.darkened(0.25),
		"stone": ash, "stone_dark": iron,
	}


func _ready() -> void:
	if palette.is_empty():
		palette = default_palette()


func _draw() -> void:
	match kind:
		"altar": _draw_altar()
		"anvil": _draw_anvil()
		"armor_pile": _draw_armor_pile()
		"armor_rack": _draw_armor_rack()
		"armor_stand": _draw_armor_stand()
		"ash_brazier": _draw_ash_brazier()
		"ash_pile": _draw_ash_pile()
		"bar_counter": _draw_bar_counter()
		"barrels": _draw_barrels()
		"beggar_bedroll": _draw_beggar_bedroll()
		"blood_sand_patch": _draw_blood_sand_patch()
		"blue_brazier": _draw_blue_brazier()
		"bone_wall": _draw_bone_wall()
		"bookcase": _draw_bookcase()
		"broken_arcade": _draw_broken_arcade()
		"broken_bench": _draw_broken_bench()
		"broken_cart": _draw_broken_cart()
		"broken_portcullis": _draw_broken_portcullis()
		"broken_statue": _draw_broken_statue()
		"broken_table": _draw_broken_table()
		"broken_telescope": _draw_broken_telescope()
		"broken_telescope_large": _draw_broken_telescope_large()
		"candle_cluster": _draw_candle_cluster()
		"catacomb_seal": _draw_catacomb_seal()
		"cauldron": _draw_cauldron()
		"chain_post": _draw_chain_post()
		"chest": _draw_chest()
		"cloister_dead_tree": _draw_cloister_dead_tree()
		"coal_cart": _draw_coal_cart()
		"coal_pile": _draw_coal_pile()
		"coin_scale_table": _draw_coin_scale_table()
		"confession_cell": _draw_confession_cell()
		"corpse_cart": _draw_corpse_cart()
		"counter": _draw_counter()
		"dead_campfire": _draw_dead_campfire()
		"dead_tree_large": _draw_dead_tree_large()
		"dead_tree_small": _draw_dead_tree_small()
		"dry_well": _draw_dry_well()
		"fireplace": _draw_fireplace()
		"floating_stone": _draw_floating_stone()
		"floating_stones": _draw_floating_stones()
		"forbidden_books_crate": _draw_forbidden_books_crate()
		"forge": _draw_forge()
		"forge_smoke_stack": _draw_forge_smoke_stack()
		"gallows": _draw_gallows()
		"glory_shrine": _draw_glory_shrine()
		"grave_marker": _draw_grave_marker()
		"hanging_cage": _draw_hanging_cage()
		"hanging_cloth": _draw_hanging_cloth()
		"hanging_lantern_post": _draw_hanging_lantern_post()
		"hidden_chest": _draw_hidden_chest()
		"kneeling_statue": _draw_kneeling_statue()
		"knife_marks_wall": _draw_knife_marks_wall()
		"knife_table": _draw_knife_table()
		"lantern_post": _draw_lantern_post()
		"ledger_table": _draw_ledger_table()
		"lockbox_stack": _draw_lockbox_stack()
		"map_wall": _draw_map_wall()
		"market_stall": _draw_market_stall()
		"mausoleum": _draw_mausoleum()
		"notice_board": _draw_notice_board()
		"notice_wall": _draw_notice_wall()
		"obelisk": _draw_obelisk()
		"pew_left_01": _draw_pew_left_01()
		"pew_left_02": _draw_pew_left_02()
		"pew_right_01": _draw_pew_right_01()
		"pew_right_02": _draw_pew_right_02()
		"prayer_strip_wall": _draw_prayer_strip_wall()
		"refugee_tent": _draw_refugee_tent()
		"ritual_blood_stain": _draw_ritual_blood_stain()
		"ritual_circle": _draw_ritual_circle()
		"ritual_table": _draw_ritual_table()
		"sewer_grate": _draw_sewer_grate()
		"shelf_potions": _draw_shelf_potions()
		"skull_reliquary": _draw_skull_reliquary()
		"sleeping_roll": _draw_sleeping_roll()
		"table": _draw_table()
		"tavern_sign": _draw_tavern_sign()
		"trade_board": _draw_trade_board()
		"training_dummy": _draw_training_dummy()
		"vault_door": _draw_vault_door()
		"vendor_counter": _draw_vendor_counter()
		"void_crack": _draw_void_crack()
		"void_crack_ground": _draw_void_crack_ground()
		"vomit_stain": _draw_vomit_stain()
		"wanted_posters": _draw_wanted_posters()
		"warning_bell": _draw_warning_bell()
		"warning_sign": _draw_warning_sign()
		"weapon_display": _draw_weapon_display()
		"weapon_rack": _draw_weapon_rack()
		_: _draw_generic()


## Fallback box for any kind without bespoke art.
func _draw_generic() -> void:
	_draw_box(Vector2(28.0, 28.0), 14.0, palette["wood"], palette["wood_dark"])


## Oblique placeholder box: soft shadow + dark south face + lifted sunlit top.
func _draw_box(size: Vector2, h: float, top: Color, face: Color) -> void:
	var half := size * 0.5
	draw_circle(Vector2(0.0, half.y), maxf(half.x, half.y), Color(0, 0, 0, 0.16))
	var top_rect := Rect2(-half.x, -half.y - h, size.x, size.y)
	var face_rect := Rect2(-half.x, half.y - h, size.x, h)
	draw_rect(face_rect, face, true)
	draw_rect(top_rect, top, true)
	draw_rect(Rect2(top_rect.position, Vector2(size.x, 2.0)), top.lightened(0.22), true)
	draw_rect(top_rect, face.darkened(0.1), false, 1.0)


## Filled flattened ellipse (barrel/cauldron lids, pool rims).
func draw_ellipse_top(center: Vector2, rx: float, ry: float, color: Color) -> void:
	var pts := PackedVector2Array()
	for i in range(17):
		var a := TAU * float(i) / 16.0
		pts.append(center + Vector2(cos(a) * rx, sin(a) * ry))
	draw_colored_polygon(pts, color)


func _draw_altar() -> void:
	draw_circle(Vector2(0.0, 4.0), 26.0, Color(0, 0, 0, 0.22))
	# Blood-stained stone slab base.
	_draw_box(Vector2(44.0, 22.0), 16.0, palette["ash"].darkened(0.2), palette["iron"])
	# Dried blood pooled across the top.
	draw_rect(Rect2(-18.0, -30.0, 30.0, 9.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.7), true)
	draw_rect(Rect2(-6.0, -25.0, 16.0, 6.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.5), true)
	# Tarnished gold sacrificial bowl.
	draw_ellipse_top(Vector2(0.0, -29.0), 10.0, 4.0, palette["gold"].darkened(0.1))
	draw_ellipse_top(Vector2(0.0, -30.0), 7.0, 2.5, palette["abyss"])
	# Cracked bone relic and stub candle.
	draw_circle(Vector2(-14.0, -28.0), 4.0, palette["bone"].darkened(0.1))
	draw_rect(Rect2(11.0, -38.0, 4.0, 10.0), palette["bone"], true)
	draw_circle(Vector2(13.0, -40.0), 2.5, palette["sulfur"])
	draw_circle(Vector2(13.0, -40.0), 5.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.22))


func _draw_anvil() -> void:
	draw_circle(Vector2(0.0, 5.0), 16.0, Color(0, 0, 0, 0.22))
	# Rotting wood stump base.
	_draw_box(Vector2(22.0, 16.0), 10.0, palette["umber"].lightened(0.08), palette["umber"].darkened(0.25))
	# Anvil waist (narrow).
	draw_rect(Rect2(-7.0, -22.0, 14.0, 8.0), palette["iron"].darkened(0.2), true)
	# Anvil top body, dark rusted iron.
	draw_rect(Rect2(-15.0, -30.0, 30.0, 9.0), palette["iron"], true)
	# Sunlit worn top edge.
	draw_rect(Rect2(-15.0, -30.0, 30.0, 2.0), palette["ash"], true)
	# Tapered horn jutting out.
	draw_colored_polygon(PackedVector2Array([
		Vector2(15.0, -30.0), Vector2(26.0, -27.0), Vector2(15.0, -21.0)
	]), palette["iron"])
	# Rust bloom + a dried blood streak.
	draw_circle(Vector2(-6.0, -25.0), 3.0, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.5))
	draw_line(Vector2(4.0, -29.0), Vector2(7.0, -22.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.55), 2.0)


func _draw_armor_pile() -> void:
	draw_circle(Vector2(0.0, 4.0), 20.0, Color(0, 0, 0, 0.22))
	# Heap of discarded rusted plate and mail.
	draw_circle(Vector2(0.0, -2.0), 16.0, palette["iron"].darkened(0.2))
	draw_circle(Vector2(-8.0, 2.0), 9.0, palette["ash"].darkened(0.35))
	draw_circle(Vector2(9.0, 1.0), 8.0, palette["iron"])
	# A dented helm tipped on the heap.
	draw_circle(Vector2(-4.0, -6.0), 7.0, palette["ash"].darkened(0.2))
	draw_rect(Rect2(-9.0, -8.0, 10.0, 2.5), palette["abyss"], true)
	# A bent shield slab leaning out.
	draw_colored_polygon(PackedVector2Array([
		Vector2(6.0, -12.0), Vector2(15.0, -6.0), Vector2(11.0, 4.0), Vector2(4.0, -2.0)
	]), palette["iron"].darkened(0.1))
	# Rust corrosion smeared across the metal.
	draw_circle(Vector2(2.0, -3.0), 4.0, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.45))
	draw_circle(Vector2(11.0, 0.0), 3.0, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.4))


func _draw_armor_rack() -> void:
	draw_circle(Vector2(0.0, 5.0), 20.0, Color(0, 0, 0, 0.22))
	# Rotting wooden A-frame post + crossbar (a horizontal armour rail).
	draw_rect(Rect2(-3.0, -46.0, 6.0, 52.0), palette["umber"], true)
	draw_rect(Rect2(-24.0, -44.0, 48.0, 5.0), palette["umber"].lightened(0.06), true)
	# Hanging rusted breastplate.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-13.0, -39.0), Vector2(13.0, -39.0), Vector2(11.0, -16.0),
		Vector2(0.0, -10.0), Vector2(-11.0, -16.0)
	]), palette["iron"])
	# Sunlit shoulder ridge + central seam.
	draw_rect(Rect2(-13.0, -39.0, 26.0, 2.0), palette["ash"], true)
	draw_line(Vector2(0.0, -37.0), Vector2(0.0, -12.0), palette["abyss"], 1.0)
	# Rust corrosion blooms.
	draw_circle(Vector2(-5.0, -24.0), 3.0, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.5))
	draw_circle(Vector2(6.0, -30.0), 2.5, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.45))
	# Pauldrons slung over the crossbar.
	draw_circle(Vector2(-16.0, -40.0), 5.0, palette["iron"].darkened(0.1))
	draw_circle(Vector2(16.0, -40.0), 5.0, palette["iron"].darkened(0.1))


func _draw_armor_stand() -> void:
	draw_circle(Vector2(0.0, 5.0), 16.0, Color(0, 0, 0, 0.22))
	# Iron tripod foot.
	draw_line(Vector2(0.0, -10.0), Vector2(-10.0, 4.0), palette["iron"], 3.0)
	draw_line(Vector2(0.0, -10.0), Vector2(10.0, 4.0), palette["iron"], 3.0)
	draw_line(Vector2(0.0, -10.0), Vector2(0.0, 6.0), palette["iron"], 3.0)
	# Central pole.
	draw_rect(Rect2(-2.0, -44.0, 4.0, 34.0), palette["iron"].darkened(0.1), true)
	# Mounted rusted cuirass torso.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-12.0, -42.0), Vector2(12.0, -42.0), Vector2(10.0, -20.0),
		Vector2(0.0, -14.0), Vector2(-10.0, -20.0)
	]), palette["ash"].darkened(0.2))
	draw_rect(Rect2(-12.0, -42.0, 24.0, 2.0), palette["ash"], true)
	draw_line(Vector2(0.0, -40.0), Vector2(0.0, -16.0), palette["abyss"], 1.0)
	# Helm crowning the stand, dark eye-slit.
	draw_circle(Vector2(0.0, -50.0), 8.0, palette["iron"])
	draw_rect(Rect2(-6.0, -52.0, 12.0, 3.0), palette["abyss"], true)
	# Rust streak down the chest.
	draw_line(Vector2(-5.0, -38.0), Vector2(-6.0, -22.0), Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.5), 2.0)


func _draw_ash_brazier() -> void:
	# A dead, cold brazier choked with grey ash and a few dull embers.
	var metal: Color = palette["iron"]
	var ash_col: Color = palette["ash"]
	draw_circle(Vector2(0.0, 5.0), 15.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Ash dusted flat on the ground around the base.
	draw_circle(Vector2(0.0, 3.0), 13.0, Color(ash_col.r, ash_col.g, ash_col.b, 0.18))
	# Tripod legs, rust-pitted.
	draw_line(Vector2(-8.0, -8.0), Vector2(-11.0, 5.0), metal, 3.0)
	draw_line(Vector2(8.0, -8.0), Vector2(11.0, 5.0), metal, 3.0)
	draw_line(Vector2(0.0, -8.0), Vector2(0.0, 6.0), metal.darkened(0.2), 3.0)
	# Bowl.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-13.0, -18.0), Vector2(13.0, -18.0), Vector2(9.0, -8.0), Vector2(-9.0, -8.0)
	]), metal)
	# Rust streaks on the bowl.
	draw_line(Vector2(-6.0, -16.0), Vector2(-4.0, -9.0), palette["rust"].darkened(0.2), 1.0)
	draw_line(Vector2(7.0, -16.0), Vector2(5.0, -9.0), palette["rust"].darkened(0.2), 1.0)
	# Heaped grey ash filling the bowl.
	draw_ellipse_top(Vector2(0.0, -19.0), 12.0, 4.0, ash_col)
	draw_ellipse_top(Vector2(-2.0, -20.0), 7.0, 2.5, ash_col.lightened(0.15))
	# A couple of dull dying embers.
	draw_circle(Vector2(-3.0, -20.0), 1.0, palette["rust"])
	draw_circle(Vector2(4.0, -19.0), 1.0, palette["sulfur"].darkened(0.3))


func _draw_ash_pile() -> void:
	var a: Color = palette["ash"]
	draw_colored_polygon(PackedVector2Array([
		Vector2(-16.0, 2.0), Vector2(-8.0, -4.0), Vector2(4.0, -2.0),
		Vector2(14.0, 3.0), Vector2(6.0, 7.0), Vector2(-10.0, 6.0)
	]), Color(a.r, a.g, a.b, 0.45))
	draw_circle(Vector2(-2.0, 0.0), 7.0, Color(a.r, a.g, a.b, 0.4))
	draw_circle(Vector2(8.0, 2.0), 5.0, Color(a.r, a.g, a.b, 0.35))
	draw_circle(Vector2(-9.0, 3.0), 4.0, Color(palette["iron"].r, palette["iron"].g, palette["iron"].b, 0.4))
	draw_circle(Vector2(2.0, -2.0), 3.0, Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5))
	draw_circle(Vector2(5.0, 1.0), 1.5, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.3))


func _draw_bar_counter() -> void:
	draw_circle(Vector2(0.0, 4.0), 40.0, Color(0, 0, 0, 0.22))
	# Heavy tavern bar.
	_draw_box(Vector2(78.0, 28.0), 16.0, palette["wood"], palette["wood_dark"])
	# Brass rail along the top edge.
	draw_line(Vector2(-38.0, -28.0), Vector2(38.0, -28.0), palette["gold"].darkened(0.1), 2.0)
	# Tankards / jug on the bar (negative Y).
	draw_rect(Rect2(-30.0, -34.0, 8.0, 8.0), palette["iron"], true)
	draw_rect(Rect2(-30.0, -34.0, 8.0, 2.0), palette["ash"], true)
	draw_rect(Rect2(-14.0, -36.0, 7.0, 10.0), palette["bone"].darkened(0.2), true)
	# Spilled ale stain on top.
	draw_circle(Vector2(16.0, -18.0), 7.0, Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.45))


func _draw_barrels() -> void:
	draw_circle(Vector2(0.0, 4.0), 28.0, Color(0, 0, 0, 0.22))
	# Back barrel, set slightly higher and behind.
	draw_rect(Rect2(2.0, -34.0, 22.0, 30.0), palette["wood"].darkened(0.1), true)
	draw_rect(Rect2(2.0, -28.0, 22.0, 3.0), palette["iron"], true)
	draw_rect(Rect2(2.0, -14.0, 22.0, 3.0), palette["iron"], true)
	draw_ellipse_top(Vector2(13.0, -34.0), 11.0, 4.0, palette["wood_dark"])
	# Front barrel.
	draw_rect(Rect2(-22.0, -28.0, 22.0, 30.0), palette["wood"], true)
	draw_rect(Rect2(-22.0, -22.0, 22.0, 3.0), palette["rust"], true)
	draw_rect(Rect2(-22.0, -8.0, 22.0, 3.0), palette["iron"], true)
	draw_ellipse_top(Vector2(-11.0, -28.0), 11.0, 4.0, palette["wood"].lightened(0.1))
	# Grime stain on the front stave.
	draw_circle(Vector2(-14.0, -14.0), 4.0, Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.4))


func _draw_beggar_bedroll() -> void:
	var cloth: Color = palette["taupe"].darkened(0.25)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-22.0, -8.0), Vector2(20.0, -10.0), Vector2(23.0, 8.0), Vector2(-19.0, 10.0)
	]), Color(cloth.r, cloth.g, cloth.b, 0.8))
	draw_colored_polygon(PackedVector2Array([
		Vector2(-22.0, -8.0), Vector2(-9.0, -9.0), Vector2(-8.0, 9.0), Vector2(-19.0, 10.0)
	]), Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.55))
	draw_line(Vector2(2.0, -9.0), Vector2(3.0, 9.0), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.35), 2.0)
	draw_line(Vector2(-11.0, -8.0), Vector2(-10.0, 9.0), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.3), 1.0)
	draw_circle(Vector2(-15.0, 0.0), 5.0, Color(palette["bone"].r, palette["bone"].g, palette["bone"].b, 0.35))
	draw_circle(Vector2(10.0, 5.0), 2.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.3))


func _draw_blood_sand_patch() -> void:
	var b: Color = palette["blood"]
	draw_colored_polygon(PackedVector2Array([
		Vector2(-18.0, -2.0), Vector2(-6.0, -8.0), Vector2(8.0, -5.0),
		Vector2(17.0, 1.0), Vector2(12.0, 8.0), Vector2(-4.0, 9.0), Vector2(-15.0, 5.0)
	]), Color(b.r, b.g, b.b, 0.42))
	draw_circle(Vector2(0.0, 0.0), 9.0, Color(b.r, b.g, b.b, 0.4))
	draw_circle(Vector2(7.0, -3.0), 5.0, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.35))
	draw_circle(Vector2(-10.0, 4.0), 3.0, Color(b.r, b.g, b.b, 0.5))
	draw_circle(Vector2(13.0, 6.0), 2.0, Color(b.r, b.g, b.b, 0.45))
	draw_circle(Vector2(-16.0, -4.0), 1.5, Color(b.r, b.g, b.b, 0.4))


func _draw_blue_brazier() -> void:
	# An iron brazier burning with cold cosmic blue mage-fire.
	var metal: Color = palette["iron"]
	var flame: Color = palette["vblue"]
	draw_circle(Vector2(0.0, 5.0), 15.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Tripod legs.
	draw_line(Vector2(-8.0, -8.0), Vector2(-11.0, 5.0), metal, 3.0)
	draw_line(Vector2(8.0, -8.0), Vector2(11.0, 5.0), metal, 3.0)
	draw_line(Vector2(0.0, -8.0), Vector2(0.0, 6.0), metal.darkened(0.2), 3.0)
	# Bowl.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-13.0, -18.0), Vector2(13.0, -18.0), Vector2(9.0, -8.0), Vector2(-9.0, -8.0)
	]), metal)
	draw_ellipse_top(Vector2(0.0, -18.0), 13.0, 4.0, metal.darkened(0.25))
	# Cold-fire halo.
	draw_circle(Vector2(0.0, -26.0), 16.0, Color(flame.r, flame.g, flame.b, 0.16))
	# Blue flame tongues licking upward.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-8.0, -18.0), Vector2(0.0, -40.0), Vector2(8.0, -18.0)
	]), flame)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-4.0, -18.0), Vector2(0.0, -34.0), Vector2(5.0, -18.0)
	]), palette["teal"].lightened(0.2))
	# Hot pale core.
	draw_circle(Vector2(0.0, -22.0), 3.0, flame.lightened(0.5))


func _draw_bone_wall() -> void:
	draw_circle(Vector2(0.0, 6.0), 30.0, Color(0, 0, 0, 0.22))
	# Mortared base of dark stone.
	_draw_box(Vector2(58.0, 16.0), 10.0, palette["iron"].lightened(0.1), palette["iron"])
	# Stacked rows of skulls and long bones piled atop.
	var bone: Color = palette["bone"]
	var shade: Color = bone.darkened(0.35)
	for row in range(2):
		var ry := -18.0 - float(row) * 12.0
		for i in range(5):
			var bx := -24.0 + float(i) * 12.0 + (6.0 if row == 1 else 0.0)
			# Long bones laid between the skull row.
			draw_rect(Rect2(bx - 5.0, ry + 5.0, 10.0, 3.0), shade, true)
			# Skull dome.
			draw_circle(Vector2(bx, ry), 5.0, bone)
			# Eye sockets — hollow black.
			draw_circle(Vector2(bx - 2.0, ry - 1.0), 1.4, palette["abyss"])
			draw_circle(Vector2(bx + 2.0, ry - 1.0), 1.4, palette["abyss"])
			draw_rect(Rect2(bx - 1.0, ry + 2.0, 2.0, 3.0), palette["abyss"], true)


func _draw_bookcase() -> void:
	# A tall rotting shelf of mildewed tomes, half-collapsed.
	var wood: Color = palette["umber"]
	var wood_dark: Color = wood.darkened(0.3)
	draw_circle(Vector2(0.0, 5.0), 20.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Cabinet carcass as an oblique box.
	_draw_box(Vector2(38.0, 14.0), 52.0, wood, wood_dark)
	# Inner shadowed cavity (the open front).
	draw_rect(Rect2(-15.0, -62.0, 30.0, 52.0), palette["abyss"].lightened(0.05), true)
	# Three shelf planks.
	for i in range(3):
		var sy := -54.0 + float(i) * 16.0
		draw_rect(Rect2(-15.0, sy, 30.0, 3.0), wood_dark, true)
	# Books crammed on the shelves, filthy spines.
	var spine := [palette["blood"], palette["taupe"], palette["gold"].darkened(0.2), palette["iron"], palette["rust"].darkened(0.2)]
	for i in range(3):
		var sy := -54.0 + float(i) * 16.0
		for j in range(6):
			var bx := -14.0 + float(j) * 4.6
			var bh := 9.0 + float((i * 7 + j * 3) % 4)
			draw_rect(Rect2(bx, sy - bh, 4.0, bh), spine[(i * 6 + j) % spine.size()], true)
	# A toppled book leaning at the top.
	draw_rect(Rect2(2.0, -64.0, 10.0, 3.0), palette["bone"].darkened(0.2), true)


func _draw_broken_arcade() -> void:
	draw_circle(Vector2(0.0, 6.0), 32.0, Color(0, 0, 0, 0.22))
	var stone: Color = palette["ash"]
	var dark: Color = palette["iron"]
	# Left column — tall, intact-ish.
	draw_rect(Rect2(-30.0, -52.0, 12.0, 58.0), dark, true)
	draw_rect(Rect2(-30.0, -52.0, 8.0, 58.0), stone, true)
	# Right column — snapped short.
	draw_rect(Rect2(18.0, -26.0, 12.0, 32.0), dark, true)
	draw_rect(Rect2(18.0, -26.0, 8.0, 32.0), stone, true)
	# Broken jagged top of the right column.
	draw_colored_polygon(PackedVector2Array([
		Vector2(18.0, -26.0), Vector2(24.0, -30.0),
		Vector2(30.0, -24.0)
	]), dark)
	# Half-collapsed arch springing from the left column.
	var arch := PackedVector2Array()
	for i in range(7):
		var a: float = PI - PI * 0.45 * (float(i) / 6.0)
		arch.append(Vector2(-24.0 + cos(a) * -22.0, -52.0 + sin(a) * -18.0) - Vector2(0.0, 0.0))
	for i in range(arch.size() - 1):
		draw_line(arch[i], arch[i + 1], stone, 6.0)
	# Fallen rubble block on the ground.
	draw_rect(Rect2(-6.0, -8.0, 14.0, 10.0), stone, true)
	draw_rect(Rect2(-6.0, -8.0, 14.0, 10.0), dark, false, 1.0)


func _draw_broken_bench() -> void:
	draw_circle(Vector2(0.0, 4.0), 22.0, Color(0, 0, 0, 0.2))
	# Collapsed seat: one end still stands, the other has fallen.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-26.0, -10.0), Vector2(0.0, -12.0), Vector2(8.0, 2.0), Vector2(-22.0, 4.0)
	]), palette["umber"])
	# Sunlit top edge of the standing plank.
	draw_line(Vector2(-26.0, -10.0), Vector2(0.0, -12.0), palette["umber"].lightened(0.15), 2.0)
	# Snapped, splintered break in the middle.
	draw_colored_polygon(PackedVector2Array([
		Vector2(0.0, -12.0), Vector2(6.0, -6.0), Vector2(2.0, -2.0), Vector2(0.0, -8.0)
	]), palette["umber"].darkened(0.45))
	# A loose plank lying flat on the ground (decal-like).
	draw_colored_polygon(PackedVector2Array([
		Vector2(10.0, -2.0), Vector2(30.0, 2.0), Vector2(29.0, 7.0), Vector2(9.0, 3.0)
	]), palette["umber"].darkened(0.2))
	# Standing leg, splintered at the top.
	draw_rect(Rect2(-22.0, -8.0, 5.0, 12.0), palette["umber"].darkened(0.3), true)
	# Ash and old stain over the wreckage.
	draw_circle(Vector2(-4.0, 2.0), 8.0, Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.28))


func _draw_broken_cart() -> void:
	draw_circle(Vector2(0.0, 4.0), 24.0, Color(0, 0, 0, 0.22))
	var w: Color = palette["umber"]
	var wd: Color = w.darkened(0.35)
	# cart bed tipped onto its side, broken
	_draw_box(Vector2(40.0, 16.0), 10.0, w, wd)
	# splintered, missing plank gap
	draw_rect(Rect2(-4.0, -22.0, 7.0, 12.0), palette["abyss"], true)
	draw_line(Vector2(4.0, -22.0), Vector2(8.0, -28.0), wd, 2.0)
	draw_line(Vector2(-4.0, -22.0), Vector2(-9.0, -27.0), wd, 2.0)
	# one wheel still on axle, leaning
	draw_circle(Vector2(-22.0, -2.0), 9.0, palette["iron"])
	draw_circle(Vector2(-22.0, -2.0), 9.0, palette["abyss"], false, 1.5)
	draw_circle(Vector2(-22.0, -2.0), 2.5, palette["rust"])
	draw_line(Vector2(-22.0, -11.0), Vector2(-22.0, 7.0), palette["iron"].lightened(0.1), 1.0)
	draw_line(Vector2(-31.0, -2.0), Vector2(-13.0, -2.0), palette["iron"].lightened(0.1), 1.0)
	# the other wheel fallen flat on the ground (decal-ish, low)
	draw_circle(Vector2(18.0, 8.0), 8.0, palette["iron"].darkened(0.2))
	draw_circle(Vector2(18.0, 8.0), 3.0, palette["abyss"])


func _draw_broken_portcullis() -> void:
	draw_circle(Vector2(0.0, 4.0), 30.0, Color(0, 0, 0, 0.24))
	var s: Color = palette["ash"]
	var sd: Color = palette["iron"]
	# blackened stone gate jambs
	_draw_box(Vector2(12.0, 14.0), 44.0, s, sd)
	draw_rect(Rect2(20.0, -58.0, 12.0, 58.0), sd, true)
	draw_rect(Rect2(20.0, -58.0, 12.0, 2.0), s.lightened(0.15), true)
	# stone lintel across the top
	draw_rect(Rect2(-30.0, -60.0, 62.0, 8.0), sd, true)
	draw_rect(Rect2(-30.0, -60.0, 62.0, 2.0), s.lightened(0.1), true)
	# rusted iron grate, BROKEN: bent and snapped bars
	var r: Color = palette["rust"]
	draw_line(Vector2(-22.0, -52.0), Vector2(-24.0, -20.0), r, 2.5)
	draw_line(Vector2(-12.0, -52.0), Vector2(-11.0, -34.0), r.darkened(0.2), 2.5)
	draw_line(Vector2(-12.0, -34.0), Vector2(-18.0, -22.0), r.darkened(0.2), 2.5)
	draw_line(Vector2(-2.0, -52.0), Vector2(0.0, -16.0), r, 2.5)
	draw_line(Vector2(8.0, -52.0), Vector2(8.0, -40.0), r.darkened(0.2), 2.5)
	draw_line(Vector2(-26.0, -44.0), Vector2(14.0, -44.0), r, 2.0)
	# void-dark gap where the city lies beyond
	draw_colored_polygon(PackedVector2Array([Vector2(-18.0, -16.0), Vector2(18.0, -16.0), Vector2(16.0, -50.0), Vector2(-16.0, -50.0)]), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.6))


func _draw_broken_statue() -> void:
	draw_circle(Vector2(0.0, 6.0), 20.0, Color(0, 0, 0, 0.22))
	# Plinth.
	_draw_box(Vector2(34.0, 22.0), 12.0, palette["ash"], palette["iron"])
	# Shattered legs / lower torso — figure snapped off at the chest.
	var stone: Color = palette["ash"].lightened(0.08)
	var dark: Color = palette["iron"]
	draw_colored_polygon(PackedVector2Array([
		Vector2(-9.0, -22.0), Vector2(9.0, -22.0),
		Vector2(11.0, -44.0), Vector2(-7.0, -46.0)
	]), stone)
	# Jagged break across the top.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-7.0, -46.0), Vector2(0.0, -42.0),
		Vector2(5.0, -47.0), Vector2(11.0, -44.0)
	]), dark)
	# A lone arm fragment fallen on the plinth.
	draw_rect(Rect2(10.0, -24.0, 12.0, 5.0), stone, true)
	draw_rect(Rect2(10.0, -24.0, 12.0, 5.0), dark, false, 1.0)
	# Crack down the standing fragment.
	draw_line(Vector2(0.0, -24.0), Vector2(2.0, -42.0), dark, 1.0)
	# Rubble at the base.
	draw_circle(Vector2(-12.0, -2.0), 3.0, stone)
	draw_circle(Vector2(13.0, 0.0), 3.5, stone)


func _draw_broken_table() -> void:
	draw_circle(Vector2(0.0, 4.0), 30.0, Color(0, 0, 0, 0.22))
	# Collapsed half of a table, tilted.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-28.0, -8.0), Vector2(18.0, -18.0), Vector2(22.0, -6.0), Vector2(-24.0, 4.0)
	]), palette["wood"])
	draw_colored_polygon(PackedVector2Array([
		Vector2(-24.0, 4.0), Vector2(22.0, -6.0), Vector2(22.0, 0.0), Vector2(-24.0, 10.0)
	]), palette["wood_dark"])
	# Snapped, splintered leg sticking up.
	draw_line(Vector2(16.0, -16.0), Vector2(22.0, -38.0), palette["wood_dark"], 4.0)
	draw_colored_polygon(PackedVector2Array([
		Vector2(20.0, -38.0), Vector2(26.0, -44.0), Vector2(24.0, -36.0)
	]), palette["umber"])
	# Scattered broken planks on the ground (flat decals).
	draw_line(Vector2(-30.0, 8.0), Vector2(-12.0, 12.0), palette["wood_dark"], 3.0)
	draw_line(Vector2(-26.0, 14.0), Vector2(-6.0, 10.0), palette["umber"], 2.0)


func _draw_broken_telescope() -> void:
	# A cracked star-gazing telescope on a tripod, tube snapped and drooping.
	var metal: Color = palette["iron"]
	var brass: Color = palette["gold"]
	draw_circle(Vector2(0.0, 4.0), 13.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Tripod legs.
	draw_line(Vector2(0.0, -18.0), Vector2(-10.0, 4.0), metal, 3.0)
	draw_line(Vector2(0.0, -18.0), Vector2(9.0, 4.0), metal, 3.0)
	draw_line(Vector2(0.0, -18.0), Vector2(1.0, 6.0), metal.darkened(0.2), 3.0)
	# Pivot hub.
	draw_circle(Vector2(0.0, -18.0), 4.0, brass.darkened(0.2))
	# Telescope tube, angled up then snapped.
	draw_line(Vector2(0.0, -18.0), Vector2(-14.0, -34.0), brass, 6.0)
	# Broken muzzle end, drooping and dented.
	draw_line(Vector2(-14.0, -34.0), Vector2(-22.0, -30.0), brass.darkened(0.25), 5.0)
	# Cracked lens ring.
	draw_circle(Vector2(-22.0, -30.0), 4.0, metal)
	draw_circle(Vector2(-22.0, -30.0), 2.0, palette["abyss"])
	# Tarnish/rust streak on the tube.
	draw_line(Vector2(-4.0, -22.0), Vector2(-12.0, -31.0), palette["rust"].darkened(0.2), 1.0)


func _draw_broken_telescope_large() -> void:
	# A great observatory telescope on a heavy mount, barrel shattered, leaking cold star-light.
	var metal: Color = palette["iron"]
	var brass: Color = palette["gold"]
	var starlight: Color = palette["vblue"]
	draw_circle(Vector2(0.0, 6.0), 22.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Heavy stone-and-iron base mount.
	_draw_box(Vector2(26.0, 16.0), 10.0, palette["ash"], palette["iron"])
	# Mount pillar.
	draw_rect(Rect2(-5.0, -34.0, 10.0, 22.0), metal, true)
	draw_circle(Vector2(0.0, -34.0), 6.0, brass.darkened(0.2))  # pivot
	# Faint halo from the cracked optics.
	draw_circle(Vector2(-26.0, -54.0), 12.0, Color(starlight.r, starlight.g, starlight.b, 0.18))
	# Large barrel angled to the heavens.
	draw_line(Vector2(0.0, -34.0), Vector2(-20.0, -58.0), brass, 11.0)
	# Snapped end, bent down with jagged break.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-20.0, -58.0), Vector2(-30.0, -52.0), Vector2(-34.0, -56.0), Vector2(-26.0, -64.0)
	]), brass.darkened(0.25))
	# Broken lens hole with cold glow.
	draw_circle(Vector2(-30.0, -56.0), 5.0, metal)
	draw_circle(Vector2(-30.0, -56.0), 2.5, starlight.lightened(0.2))
	# Rust and tarnish along the barrel.
	draw_line(Vector2(-6.0, -40.0), Vector2(-18.0, -56.0), palette["rust"].darkened(0.2), 2.0)
	draw_line(Vector2(-2.0, -36.0), Vector2(-14.0, -52.0), brass.lightened(0.15), 1.0)


func _draw_candle_cluster() -> void:
	draw_circle(Vector2(0.0, 4.0), 14.0, Color(0, 0, 0, 0.2))
	# Pooled, congealed wax base.
	draw_ellipse_top(Vector2(0.0, 0.0), 13.0, 5.0, palette["bone"].darkened(0.25))
	draw_ellipse_top(Vector2(0.0, -1.0), 9.0, 3.5, palette["bone"].darkened(0.1))
	# Uneven melted candle stubs of differing height.
	draw_rect(Rect2(-9.0, -16.0, 4.0, 16.0), palette["bone"], true)
	draw_rect(Rect2(-2.0, -24.0, 4.0, 24.0), palette["bone"].lightened(0.05), true)
	draw_rect(Rect2(5.0, -13.0, 4.0, 13.0), palette["bone"].darkened(0.05), true)
	# Drips down the tallest candle.
	draw_rect(Rect2(-2.0, -8.0, 2.0, 6.0), palette["bone"].darkened(0.15), true)
	# Three small flames with halos.
	draw_circle(Vector2(-7.0, -18.0), 2.0, palette["sulfur"])
	draw_circle(Vector2(0.0, -26.0), 2.5, palette["sulfur"].lightened(0.2))
	draw_circle(Vector2(7.0, -15.0), 2.0, palette["sulfur"])
	draw_circle(Vector2(0.0, -23.0), 11.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.18))


func _draw_catacomb_seal() -> void:
	# Flat trapdoor seal set into the floor — no oblique lift, faint shadow only.
	draw_circle(Vector2(0.0, 2.0), 30.0, Color(0, 0, 0, 0.18))
	# Heavy round iron seal slab.
	draw_circle(Vector2.ZERO, 28.0, palette["iron"])
	draw_circle(Vector2.ZERO, 24.0, palette["ash"].darkened(0.25))
	draw_circle(Vector2.ZERO, 24.0, palette["iron"].lightened(0.1))
	# Inner sunken ring.
	draw_circle(Vector2.ZERO, 18.0, palette["iron"].darkened(0.2))
	# Carved warding cross dividing the seal.
	draw_line(Vector2(-22.0, 0.0), Vector2(22.0, 0.0), palette["abyss"], 3.0)
	draw_line(Vector2(0.0, -22.0), Vector2(0.0, 22.0), palette["abyss"], 3.0)
	# Tarnished gold ritual sigil at center.
	draw_circle(Vector2.ZERO, 7.0, palette["gold"].darkened(0.2))
	draw_circle(Vector2.ZERO, 4.0, palette["eldritch"])
	# Faint cursed light seeping from the seam.
	draw_circle(Vector2.ZERO, 5.0, Color(palette["magenta"].r, palette["magenta"].g, palette["magenta"].b, 0.3))
	# Pull-rings on opposite sides.
	draw_arc(Vector2(-22.0, 0.0), 4.0, 0.0, TAU, 10, palette["rust"], 2.0)
	draw_arc(Vector2(22.0, 0.0), 4.0, 0.0, TAU, 10, palette["rust"], 2.0)


func _draw_cauldron() -> void:
	draw_circle(Vector2(0.0, 5.0), 22.0, Color(0, 0, 0, 0.22))
	# Iron tripod legs straddling cold coals.
	draw_line(Vector2(-12.0, -14.0), Vector2(-15.0, 4.0), palette["iron"], 3.0)
	draw_line(Vector2(12.0, -14.0), Vector2(15.0, 4.0), palette["iron"], 3.0)
	draw_line(Vector2(0.0, -14.0), Vector2(0.0, 6.0), palette["iron"], 3.0)
	# Spent coals beneath, faint embers.
	draw_circle(Vector2(0.0, 2.0), 6.0, palette["abyss"])
	draw_circle(Vector2(0.0, 2.0), 2.0, palette["rust"])
	# Bulbous black cauldron belly.
	draw_circle(Vector2(0.0, -22.0), 18.0, palette["iron"].darkened(0.15))
	draw_circle(Vector2(-6.0, -27.0), 6.0, palette["iron"].lightened(0.1))
	# Heavy rim.
	draw_ellipse_top(Vector2(0.0, -34.0), 18.0, 6.0, palette["iron"].darkened(0.3))
	# Bubbling cursed soul-brew (rare teal glow).
	draw_ellipse_top(Vector2(0.0, -35.0), 14.0, 4.0, palette["teal"])
	draw_circle(Vector2(-4.0, -35.0), 2.5, palette["teal"].lightened(0.3))
	draw_circle(Vector2(5.0, -36.0), 2.0, palette["teal"].lightened(0.2))
	draw_circle(Vector2(0.0, -35.0), 16.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.2))


func _draw_chain_post() -> void:
	draw_circle(Vector2(0.0, 4.0), 12.0, Color(0, 0, 0, 0.22))
	# Squat stone bollard post.
	_draw_box(Vector2(16.0, 14.0), 28.0, palette["stone"], palette["stone_dark"])
	# Rusted iron cap ring.
	draw_circle(Vector2(0.0, -42.0), 5.0, palette["iron"])
	draw_circle(Vector2(0.0, -42.0), 5.0, palette["rust"], false, 1.5)
	# Heavy chain sagging off to one side (sway).
	draw_line(Vector2(0.0, -40.0), Vector2(12.0, -24.0), palette["iron"], 2.5)
	draw_line(Vector2(12.0, -24.0), Vector2(24.0, -32.0), palette["iron"], 2.5)
	draw_circle(Vector2(6.0, -32.0), 2.0, palette["rust"])
	draw_circle(Vector2(18.0, -28.0), 2.0, palette["rust"])


func _draw_chest() -> void:
	draw_circle(Vector2(0.0, 4.0), 24.0, Color(0, 0, 0, 0.22))
	# Chest body.
	_draw_box(Vector2(40.0, 24.0), 12.0, palette["wood"], palette["wood_dark"])
	# Domed iron-banded lid (negative Y).
	draw_colored_polygon(PackedVector2Array([
		Vector2(-20.0, -30.0), Vector2(-14.0, -40.0), Vector2(14.0, -40.0), Vector2(20.0, -30.0)
	]), palette["wood"].lightened(0.1))
	draw_polyline(PackedVector2Array([
		Vector2(-20.0, -30.0), Vector2(-14.0, -40.0), Vector2(14.0, -40.0), Vector2(20.0, -30.0)
	]), palette["iron"], 1.0)
	# Iron bands.
	draw_line(Vector2(-10.0, -40.0), Vector2(-10.0, -2.0), palette["iron"], 2.0)
	draw_line(Vector2(10.0, -40.0), Vector2(10.0, -2.0), palette["iron"], 2.0)
	# Tarnished lock plate.
	draw_rect(Rect2(-3.0, -30.0, 6.0, 7.0), palette["gold"].darkened(0.1), true)


func _draw_cloister_dead_tree() -> void:
	draw_circle(Vector2(0.0, 6.0), 18.0, Color(0, 0, 0, 0.22))
	draw_circle(Vector2(0.0, 2.0), 16.0, palette["iron"].darkened(0.1))
	draw_arc(Vector2(0.0, 2.0), 16.0, 0.0, TAU, 24, palette["ash"].darkened(0.2), 2.0)
	var bark: Color = palette["umber"].darkened(0.18)
	draw_line(Vector2(0.0, -2.0), Vector2(-3.0, -48.0), bark, 8.0)
	draw_line(Vector2(-2.0, -26.0), Vector2(-18.0, -40.0), bark, 4.0)
	draw_line(Vector2(-3.0, -34.0), Vector2(16.0, -46.0), bark, 4.0)
	draw_line(Vector2(-18.0, -40.0), Vector2(-26.0, -52.0), bark.darkened(0.15), 2.0)
	draw_line(Vector2(16.0, -46.0), Vector2(24.0, -58.0), bark.darkened(0.15), 2.0)
	draw_line(Vector2(-3.0, -48.0), Vector2(-8.0, -60.0), bark.darkened(0.15), 2.0)
	draw_circle(Vector2(7.0, -8.0), 4.0, palette["magenta"].darkened(0.2))
	draw_circle(Vector2(-6.0, -16.0), 3.0, palette["magenta"].darkened(0.25))


func _draw_coal_cart() -> void:
	draw_circle(Vector2(0.0, 4.0), 28.0, Color(0, 0, 0, 0.22))
	var w: Color = palette["umber"]
	var wd: Color = w.darkened(0.4)
	# squat tipper bin
	_draw_box(Vector2(46.0, 24.0), 12.0, w, wd)
	# iron-banded rim
	draw_rect(Rect2(-23.0, -36.0, 46.0, 3.0), palette["iron"], true)
	# heaped coal mound (abyss lumps with faint sulfur ember)
	draw_circle(Vector2(-8.0, -34.0), 8.0, palette["abyss"].lightened(0.1))
	draw_circle(Vector2(5.0, -36.0), 9.0, palette["abyss"])
	draw_circle(Vector2(14.0, -32.0), 6.0, palette["iron"].darkened(0.3))
	draw_circle(Vector2(-2.0, -38.0), 5.0, palette["abyss"].lightened(0.05))
	# a single dull ember glow
	draw_circle(Vector2(2.0, -34.0), 2.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.4))
	# wheel
	draw_circle(Vector2(-21.0, 0.0), 10.0, palette["iron"])
	draw_circle(Vector2(-21.0, 0.0), 10.0, palette["abyss"], false, 2.0)
	draw_circle(Vector2(-21.0, 0.0), 3.0, palette["rust"])
	# coal dust scatter (flat decal)
	draw_circle(Vector2(10.0, 9.0), 10.0, Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.25))


func _draw_coal_pile() -> void:
	draw_circle(Vector2(0.0, 4.0), 18.0, Color(0, 0, 0, 0.22))
	# Mound of black coal — low heap of overlapping lumps.
	draw_circle(Vector2(0.0, -2.0), 16.0, palette["abyss"])
	draw_circle(Vector2(-9.0, 1.0), 8.0, palette["iron"].darkened(0.3))
	draw_circle(Vector2(9.0, 0.0), 9.0, palette["iron"].darkened(0.4))
	draw_circle(Vector2(2.0, -8.0), 8.0, palette["iron"].darkened(0.25))
	# Faceted highlights on the lumps.
	draw_circle(Vector2(-5.0, -6.0), 3.0, palette["ash"].darkened(0.2))
	draw_circle(Vector2(7.0, -3.0), 2.5, palette["ash"].darkened(0.3))
	# A few embers still smouldering deep in the heap.
	draw_circle(Vector2(0.0, -1.0), 3.0, palette["rust"])
	draw_circle(Vector2(0.0, -1.0), 5.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.18))
	# Ash dust spilled flat at the base.
	draw_circle(Vector2(-13.0, 6.0), 4.0, Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.3))


func _draw_coin_scale_table() -> void:
	draw_circle(Vector2(0.0, 4.0), 26.0, Color(0, 0, 0, 0.22))
	# Worn table.
	_draw_box(Vector2(46.0, 24.0), 12.0, palette["wood"], palette["wood_dark"])
	# Balance scale post and beam (negative Y).
	draw_line(Vector2(0.0, -12.0), Vector2(0.0, -36.0), palette["iron"], 3.0)
	draw_line(Vector2(-16.0, -34.0), Vector2(16.0, -34.0), palette["iron"], 2.0)
	# Tarnished pans hanging crooked.
	draw_line(Vector2(-16.0, -34.0), Vector2(-16.0, -26.0), palette["ash"], 1.0)
	draw_line(Vector2(16.0, -34.0), Vector2(16.0, -22.0), palette["ash"], 1.0)
	draw_ellipse_top(Vector2(-16.0, -26.0), 7.0, 3.0, palette["gold"].darkened(0.2))
	draw_ellipse_top(Vector2(16.0, -22.0), 7.0, 3.0, palette["gold"].darkened(0.3))
	# A few dull coins spilled on the top.
	draw_circle(Vector2(-6.0, -14.0), 2.0, palette["gold"])
	draw_circle(Vector2(2.0, -16.0), 2.0, palette["gold"].darkened(0.15))


func _draw_confession_cell() -> void:
	draw_circle(Vector2(0.0, 6.0), 30.0, Color(0, 0, 0, 0.22))
	# Tall rotting-wood booth body.
	_draw_box(Vector2(40.0, 26.0), 52.0, palette["umber"], palette["umber"].darkened(0.35))
	# Sagging plank seams.
	draw_line(Vector2(-20.0, -52.0), Vector2(-20.0, -13.0), palette["umber"].darkened(0.4), 1.5)
	draw_line(Vector2(0.0, -54.0), Vector2(0.0, -13.0), palette["umber"].darkened(0.4), 1.5)
	draw_line(Vector2(20.0, -52.0), Vector2(20.0, -13.0), palette["umber"].darkened(0.4), 1.5)
	# Dark curtained doorway, void within.
	draw_rect(Rect2(-12.0, -50.0, 24.0, 37.0), palette["abyss"], true)
	# The confession lattice window.
	draw_rect(Rect2(-7.0, -46.0, 14.0, 12.0), palette["iron"], true)
	for i in range(4):
		draw_line(Vector2(-7.0 + i * 4.0, -46.0), Vector2(-7.0 + i * 4.0, -34.0), palette["abyss"], 1.0)
	draw_line(Vector2(-7.0, -40.0), Vector2(7.0, -40.0), palette["abyss"], 1.0)
	# Tarnished gold cross crowning the booth.
	draw_rect(Rect2(-2.0, -72.0, 4.0, 14.0), palette["gold"].darkened(0.15), true)
	draw_rect(Rect2(-6.0, -68.0, 12.0, 4.0), palette["gold"].darkened(0.15), true)


func _draw_corpse_cart() -> void:
	draw_circle(Vector2(0.0, 4.0), 30.0, Color(0, 0, 0, 0.22))
	var w: Color = palette["umber"]
	var wd: Color = w.darkened(0.4)
	# heavy plague-cart bed
	_draw_box(Vector2(52.0, 26.0), 14.0, w, wd)
	# piled shrouded dead (filthy taupe cloth heaps)
	draw_circle(Vector2(-12.0, -22.0), 9.0, palette["taupe"].darkened(0.15))
	draw_circle(Vector2(6.0, -24.0), 8.0, palette["taupe"].darkened(0.25))
	draw_circle(Vector2(16.0, -20.0), 6.0, palette["taupe"].darkened(0.1))
	# a pale skull resting on the pile
	draw_circle(Vector2(-2.0, -27.0), 4.5, palette["bone"])
	draw_circle(Vector2(-3.5, -27.0), 1.0, palette["abyss"])
	draw_circle(Vector2(-0.5, -27.0), 1.0, palette["abyss"])
	# big wheel
	draw_circle(Vector2(-24.0, 0.0), 11.0, palette["iron"])
	draw_circle(Vector2(-24.0, 0.0), 11.0, palette["abyss"], false, 2.0)
	draw_circle(Vector2(-24.0, 0.0), 3.0, palette["rust"])
	# pooled old blood beneath (flat decal)
	draw_circle(Vector2(8.0, 10.0), 14.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.3))


func _draw_counter() -> void:
	draw_circle(Vector2(0.0, 4.0), 36.0, Color(0, 0, 0, 0.22))
	# Long worn-wood counter.
	_draw_box(Vector2(72.0, 26.0), 14.0, palette["wood"], palette["wood_dark"])
	# Plank seams on the sunlit top.
	draw_line(Vector2(-36.0, -22.0), Vector2(36.0, -22.0), palette["wood_dark"], 1.0)
	draw_line(Vector2(-36.0, -10.0), Vector2(36.0, -10.0), palette["wood_dark"], 1.0)
	# Old stain on the surface.
	draw_circle(Vector2(14.0, -16.0), 6.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.4))


func _draw_dead_campfire() -> void:
	draw_circle(Vector2(0.0, 3.0), 18.0, Color(0, 0, 0, 0.2))
	# ash bed (flat, cold grey)
	draw_circle(Vector2(0.0, 0.0), 14.0, Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.55))
	draw_circle(Vector2(0.0, 0.0), 8.0, Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5))
	# ring of blackened stones
	for i in range(8):
		var a := TAU * float(i) / 8.0
		var p := Vector2(cos(a) * 15.0, sin(a) * 8.0)
		draw_circle(p, 3.0, palette["iron"])
		draw_circle(p + Vector2(0.0, -1.0), 2.0, palette["ash"].darkened(0.2))
	# charred, half-burnt logs crossing
	draw_line(Vector2(-9.0, -3.0), Vector2(8.0, 2.0), palette["abyss"], 4.0)
	draw_line(Vector2(-7.0, 4.0), Vector2(9.0, -4.0), palette["umber"].darkened(0.3), 3.0)
	# spent charcoal ends
	draw_circle(Vector2(-9.0, -3.0), 2.0, palette["ash"].darkened(0.1))
	draw_circle(Vector2(9.0, -4.0), 2.0, palette["ash"].darkened(0.1))


func _draw_dead_tree_large() -> void:
	draw_circle(Vector2(0.0, 6.0), 16.0, Color(0, 0, 0, 0.22))
	var bark: Color = palette["umber"].darkened(0.12)
	var darkbark: Color = palette["umber"].darkened(0.3)
	draw_line(Vector2(0.0, 4.0), Vector2(-2.0, -50.0), bark, 9.0)
	draw_line(Vector2(0.0, 4.0), Vector2(-2.0, -50.0), darkbark, 3.0)
	draw_line(Vector2(-2.0, -24.0), Vector2(-20.0, -42.0), bark, 5.0)
	draw_line(Vector2(-2.0, -30.0), Vector2(18.0, -48.0), bark, 5.0)
	draw_line(Vector2(-20.0, -42.0), Vector2(-30.0, -54.0), bark, 3.0)
	draw_line(Vector2(-20.0, -42.0), Vector2(-24.0, -58.0), bark, 3.0)
	draw_line(Vector2(18.0, -48.0), Vector2(28.0, -60.0), bark, 3.0)
	draw_line(Vector2(18.0, -48.0), Vector2(14.0, -64.0), bark, 3.0)
	draw_line(Vector2(-2.0, -50.0), Vector2(2.0, -66.0), bark, 4.0)
	draw_line(Vector2(-2.0, -50.0), Vector2(-10.0, -62.0), bark, 3.0)
	draw_circle(Vector2(4.0, -10.0), 8.0, darkbark)


func _draw_dead_tree_small() -> void:
	draw_circle(Vector2(0.0, 4.0), 10.0, Color(0, 0, 0, 0.22))
	var bark: Color = palette["umber"].darkened(0.1)
	draw_line(Vector2(0.0, 2.0), Vector2(-1.0, -32.0), bark, 5.0)
	draw_line(Vector2(-1.0, -16.0), Vector2(-12.0, -28.0), bark, 3.0)
	draw_line(Vector2(-1.0, -22.0), Vector2(10.0, -34.0), bark, 3.0)
	draw_line(Vector2(-1.0, -30.0), Vector2(-7.0, -40.0), bark.darkened(0.15), 2.0)
	draw_line(Vector2(-1.0, -30.0), Vector2(6.0, -42.0), bark.darkened(0.15), 2.0)
	draw_line(Vector2(10.0, -34.0), Vector2(16.0, -40.0), bark.darkened(0.15), 2.0)
	draw_line(Vector2(-12.0, -28.0), Vector2(-18.0, -33.0), bark.darkened(0.15), 2.0)
	draw_circle(Vector2(-2.0, -4.0), 6.0, palette["umber"].darkened(0.3))


func _draw_dry_well() -> void:
	draw_circle(Vector2(0.0, 6.0), 28.0, Color(0, 0, 0, 0.22))
	# Crumbling stone ring.
	draw_circle(Vector2.ZERO, 26.0, palette["iron"])
	draw_circle(Vector2.ZERO, 22.0, palette["ash"].darkened(0.2))
	# Dry, cracked mud bottom — no water.
	draw_circle(Vector2.ZERO, 16.0, palette["umber"].darkened(0.25))
	draw_circle(Vector2.ZERO, 13.0, palette["abyss"])
	# Cracks in the dry bed.
	draw_line(Vector2(-8.0, -2.0), Vector2(4.0, 6.0), palette["umber"].darkened(0.4), 1.0)
	draw_line(Vector2(2.0, -8.0), Vector2(6.0, 4.0), palette["umber"].darkened(0.4), 1.0)
	# Broken stones missing from the rim.
	draw_rect(Rect2(14.0, -14.0, 8.0, 8.0), palette["ash"].darkened(0.2), true)
	# Collapsed roof beam leaning across.
	draw_line(Vector2(-26.0, -6.0), Vector2(20.0, -40.0), palette["umber"], 4.0)
	draw_line(Vector2(-26.0, -6.0), Vector2(20.0, -40.0), palette["umber"].darkened(0.3), 1.0)
	# Lone broken upright post.
	draw_line(Vector2(-22.0, -6.0), Vector2(-22.0, -30.0), palette["umber"], 3.0)


func _draw_fireplace() -> void:
	draw_circle(Vector2(0.0, 6.0), 28.0, Color(0, 0, 0, 0.22))
	# Blackened stone hearth surround.
	_draw_box(Vector2(50.0, 30.0), 24.0, palette["ash"].darkened(0.3), palette["iron"])
	# Dark inner firebox cavity.
	draw_rect(Rect2(-18.0, -36.0, 36.0, 24.0), palette["abyss"], true)
	# Charred logs across the grate.
	draw_rect(Rect2(-15.0, -18.0, 30.0, 5.0), palette["umber"].darkened(0.3), true)
	draw_rect(Rect2(-13.0, -22.0, 26.0, 4.0), palette["umber"].darkened(0.15), true)
	# Glowing ember bed.
	draw_rect(Rect2(-13.0, -16.0, 26.0, 4.0), palette["blood"], true)
	# Flame core + firelight halo (static so it reads unpowered).
	draw_colored_polygon(PackedVector2Array([
		Vector2(0.0, -34.0), Vector2(-7.0, -18.0), Vector2(7.0, -18.0)
	]), palette["sulfur"])
	draw_circle(Vector2(0.0, -22.0), 5.0, palette["bone"].lightened(0.1))
	draw_circle(Vector2(0.0, -22.0), 18.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.2))
	# Soot stain rising up the chimney breast.
	draw_rect(Rect2(-10.0, -44.0, 20.0, 8.0), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5), true)


func _draw_floating_stone() -> void:
	# A single chunk of masonry torn loose and hovering, lit by cold void glow beneath.
	var stone_top: Color = palette["ash"]
	var stone_face: Color = palette["iron"]
	var glow: Color = palette["violet"]
	# Small ground shadow far below the levitating rock.
	draw_circle(Vector2(0.0, 4.0), 9.0, Color(0, 0, 0, 0.18))
	# Cold glow trailing from the underside.
	draw_circle(Vector2(0.0, -22.0), 14.0, Color(glow.r, glow.g, glow.b, 0.12))
	# Floating rock body (south/under face darker).
	draw_colored_polygon(PackedVector2Array([
		Vector2(-12.0, -24.0), Vector2(11.0, -26.0), Vector2(14.0, -18.0),
		Vector2(2.0, -10.0), Vector2(-11.0, -16.0)
	]), stone_face)
	# Sunlit top facet.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-12.0, -24.0), Vector2(11.0, -26.0), Vector2(6.0, -32.0), Vector2(-9.0, -30.0)
	]), stone_top)
	# Cracks and corruption seam.
	draw_line(Vector2(-4.0, -28.0), Vector2(0.0, -12.0), stone_face.darkened(0.3), 1.0)
	draw_line(Vector2(-10.0, -16.0), Vector2(12.0, -19.0), Color(glow.r, glow.g, glow.b, 0.5), 1.0)


func _draw_floating_stones() -> void:
	# A cluster of broken masonry hovering at staggered heights in a void updraft.
	var stone_top: Color = palette["ash"]
	var stone_face: Color = palette["iron"]
	var glow: Color = palette["violet"]
	draw_circle(Vector2(0.0, 4.0), 14.0, Color(0, 0, 0, 0.18))  # ground shadow
	# Rising column of cold glow binding the stones.
	draw_circle(Vector2(0.0, -30.0), 22.0, Color(glow.r, glow.g, glow.b, 0.10))
	# Lowest, largest fragment.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-13.0, -14.0), Vector2(6.0, -16.0), Vector2(9.0, -8.0), Vector2(-10.0, -6.0)
	]), stone_face)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-13.0, -14.0), Vector2(6.0, -16.0), Vector2(1.0, -20.0), Vector2(-11.0, -19.0)
	]), stone_top)
	# Mid fragment, offset right.
	draw_colored_polygon(PackedVector2Array([
		Vector2(4.0, -32.0), Vector2(16.0, -34.0), Vector2(15.0, -27.0), Vector2(5.0, -26.0)
	]), stone_face)
	draw_colored_polygon(PackedVector2Array([
		Vector2(4.0, -32.0), Vector2(16.0, -34.0), Vector2(12.0, -37.0), Vector2(3.0, -36.0)
	]), stone_top)
	# Highest small shard.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-12.0, -44.0), Vector2(-3.0, -46.0), Vector2(-2.0, -40.0), Vector2(-11.0, -39.0)
	]), stone_top.darkened(0.1))
	# Glow seam threading the cluster.
	draw_line(Vector2(-2.0, -10.0), Vector2(10.0, -30.0), Color(glow.r, glow.g, glow.b, 0.45), 1.0)


func _draw_forbidden_books_crate() -> void:
	# An open crate of cursed tomes, one volume glowing with magenta veins.
	var wood: Color = palette["umber"]
	var wood_dark: Color = wood.darkened(0.3)
	var curse: Color = palette["magenta"]
	draw_circle(Vector2(0.0, 4.0), 15.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Halo of cursed light from the open lid.
	draw_circle(Vector2(0.0, -16.0), 16.0, Color(curse.r, curse.g, curse.b, 0.10))
	# Crate body.
	_draw_box(Vector2(30.0, 20.0), 14.0, wood, wood_dark)
	# Plank seams.
	draw_line(Vector2(-15.0, -16.0), Vector2(15.0, -16.0), wood_dark, 1.0)
	draw_line(Vector2(-5.0, -24.0), Vector2(-5.0, -10.0), wood_dark, 1.0)
	draw_line(Vector2(5.0, -24.0), Vector2(5.0, -10.0), wood_dark, 1.0)
	# Open top: dark interior.
	draw_ellipse_top(Vector2(0.0, -24.0), 13.0, 5.0, palette["abyss"])
	# Stacked book edges poking out.
	draw_rect(Rect2(-10.0, -30.0, 9.0, 6.0), palette["blood"], true)
	draw_rect(Rect2(0.0, -32.0, 9.0, 8.0), palette["iron"], true)
	# The forbidden tome, glowing with veins.
	draw_rect(Rect2(-4.0, -36.0, 10.0, 7.0), palette["bone"].darkened(0.3), true)
	draw_line(Vector2(-3.0, -34.0), Vector2(4.0, -30.0), curse.lightened(0.2), 1.0)
	draw_circle(Vector2(1.0, -32.0), 2.0, curse.lightened(0.3))


func _draw_forge() -> void:
	draw_circle(Vector2(0.0, 6.0), 30.0, Color(0, 0, 0, 0.22))
	# Blackened stone furnace body.
	_draw_box(Vector2(48.0, 34.0), 26.0, palette["ash"].darkened(0.35), palette["iron"])
	# Soot-stained chimney hood rising at the back.
	draw_rect(Rect2(-12.0, -56.0, 24.0, 24.0), palette["iron"].darkened(0.2), true)
	draw_rect(Rect2(-12.0, -56.0, 24.0, 24.0), palette["abyss"], false, 1.0)
	# Arched fire mouth, dark stone lip.
	draw_rect(Rect2(-16.0, -34.0, 32.0, 22.0), palette["abyss"], true)
	# Coal bed glowing inside the mouth.
	draw_rect(Rect2(-13.0, -22.0, 26.0, 9.0), palette["blood"], true)
	draw_rect(Rect2(-11.0, -20.0, 22.0, 6.0), palette["rust"], true)
	# Bright ember core + firelight halo.
	draw_circle(Vector2(0.0, -18.0), 7.0, palette["sulfur"])
	draw_circle(Vector2(0.0, -18.0), 14.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.22))
	# Tarnished iron grate bars across the mouth.
	draw_line(Vector2(-7.0, -34.0), Vector2(-7.0, -12.0), palette["iron"].darkened(0.3), 2.0)
	draw_line(Vector2(7.0, -34.0), Vector2(7.0, -12.0), palette["iron"].darkened(0.3), 2.0)


func _draw_forge_smoke_stack() -> void:
	draw_circle(Vector2(0.0, 6.0), 20.0, Color(0, 0, 0, 0.22))
	# Wide soot-caked stone base.
	_draw_box(Vector2(30.0, 24.0), 14.0, palette["ash"].darkened(0.4), palette["iron"])
	# Tall chimney shaft, blackened brick.
	draw_rect(Rect2(-10.0, -64.0, 20.0, 50.0), palette["iron"].darkened(0.15), true)
	draw_rect(Rect2(-10.0, -64.0, 4.0, 50.0), palette["ash"].darkened(0.45), true)
	draw_rect(Rect2(-10.0, -64.0, 20.0, 50.0), palette["abyss"], false, 1.0)
	# Mortar seams streaked with soot.
	draw_line(Vector2(-10.0, -40.0), Vector2(10.0, -40.0), palette["abyss"], 1.0)
	draw_line(Vector2(-10.0, -26.0), Vector2(10.0, -26.0), palette["abyss"], 1.0)
	# Flared cap mouth.
	draw_rect(Rect2(-13.0, -70.0, 26.0, 8.0), palette["iron"].darkened(0.3), true)
	# Static smoke plume so it reads when unpowered.
	draw_circle(Vector2(-2.0, -78.0), 7.0, Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.22))
	draw_circle(Vector2(3.0, -86.0), 9.0, Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.14))


func _draw_gallows() -> void:
	draw_circle(Vector2(0.0, 6.0), 22.0, Color(0, 0, 0, 0.22))
	# Plank platform base.
	_draw_box(Vector2(40.0, 18.0), 8.0, palette["umber"].lightened(0.1), palette["umber"].darkened(0.2))
	# Upright post (rotting wood).
	var wood: Color = palette["umber"]
	var wdark: Color = palette["umber"].darkened(0.3)
	draw_rect(Rect2(-20.0, -64.0, 9.0, 56.0), wdark, true)
	draw_rect(Rect2(-20.0, -64.0, 6.0, 56.0), wood, true)
	# Cross-beam arm reaching out.
	draw_rect(Rect2(-20.0, -64.0, 38.0, 8.0), wdark, true)
	draw_rect(Rect2(-20.0, -64.0, 38.0, 5.0), wood, true)
	# Diagonal support brace.
	draw_line(Vector2(-12.0, -56.0), Vector2(-4.0, -44.0), wdark, 3.0)
	# The noose — frayed rope hanging.
	draw_line(Vector2(12.0, -56.0), Vector2(12.0, -34.0), palette["taupe"].darkened(0.2), 2.0)
	draw_arc(Vector2(12.0, -30.0), 4.0, 0.0, TAU, 12, palette["taupe"].darkened(0.2), 2.0)
	# Old blood pooled on the trapdoor below.
	draw_circle(Vector2(12.0, -4.0), 6.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.4))


func _draw_glory_shrine() -> void:
	draw_circle(Vector2(0.0, 4.0), 22.0, Color(0, 0, 0, 0.22))
	# Blackened stone plinth.
	_draw_box(Vector2(30.0, 18.0), 14.0, palette["ash"].darkened(0.15), palette["iron"])
	# Pointed gothic arch niche behind the icon.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-14.0, -22.0), Vector2(-14.0, -52.0), Vector2(0.0, -64.0),
		Vector2(14.0, -52.0), Vector2(14.0, -22.0)
	]), palette["iron"].darkened(0.2))
	# Tarnished gold trim on the arch.
	draw_polyline(PackedVector2Array([
		Vector2(-14.0, -22.0), Vector2(-14.0, -52.0), Vector2(0.0, -64.0),
		Vector2(14.0, -52.0), Vector2(14.0, -22.0)
	]), palette["gold"], 2.0)
	# Cold holy soul-light at the heart of the shrine.
	draw_circle(Vector2(0.0, -40.0), 6.0, palette["teal"].lightened(0.3))
	draw_circle(Vector2(0.0, -40.0), 12.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.25))
	# Wax-caked votive candles at the foot.
	draw_rect(Rect2(-10.0, -28.0, 3.0, 8.0), palette["bone"], true)
	draw_rect(Rect2(7.0, -28.0, 3.0, 8.0), palette["bone"], true)


func _draw_grave_marker() -> void:
	draw_circle(Vector2(0.0, 4.0), 12.0, Color(0, 0, 0, 0.22))
	# Leaning, cracked headstone — base mound of dead earth.
	draw_rect(Rect2(-13.0, -4.0, 26.0, 8.0), palette["umber"].darkened(0.2), true)
	# Tilted slab body.
	var slab := PackedVector2Array([
		Vector2(-11.0, -2.0), Vector2(11.0, -4.0),
		Vector2(13.0, -34.0), Vector2(-9.0, -32.0)
	])
	draw_colored_polygon(slab, palette["ash"])
	# Rounded top cap.
	draw_ellipse_top(Vector2(2.0, -34.0), 11.0, 5.0, palette["ash"].lightened(0.1))
	# Sunlit left edge.
	draw_line(Vector2(-11.0, -2.0), Vector2(-9.0, -32.0), palette["ash"].lightened(0.2), 2.0)
	# Dark crack splitting the face.
	draw_line(Vector2(0.0, -8.0), Vector2(5.0, -28.0), palette["iron"], 2.0)
	# Carved cross, worn faint.
	draw_line(Vector2(2.0, -26.0), Vector2(2.0, -14.0), palette["iron"], 2.0)
	draw_line(Vector2(-4.0, -22.0), Vector2(8.0, -22.0), palette["iron"], 2.0)
	# Old bloodstain seeping at the base (flat decal).
	draw_circle(Vector2(-6.0, 2.0), 5.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.35))


func _draw_hanging_cage() -> void:
	draw_circle(Vector2(0.0, 4.0), 10.0, Color(0, 0, 0, 0.22))
	# Gibbet post the cage hangs from.
	var wdark: Color = palette["umber"].darkened(0.3)
	draw_rect(Rect2(-22.0, -66.0, 7.0, 70.0), wdark, true)
	draw_rect(Rect2(-22.0, -66.0, 4.0, 70.0), palette["umber"], true)
	draw_rect(Rect2(-22.0, -66.0, 24.0, 6.0), wdark, true)
	# Chain from the arm.
	draw_line(Vector2(-2.0, -60.0), Vector2(-2.0, -48.0), palette["iron"].lightened(0.2), 2.0)
	# Rusted iron cage (gibbet).
	var rusti: Color = palette["rust"].darkened(0.2)
	var cage_top := -48.0
	var cage_bot := -18.0
	# Vertical bars.
	for i in range(5):
		var bx := -14.0 + float(i) * 6.0
		draw_line(Vector2(bx, cage_top + 2.0), Vector2(bx, cage_bot), rusti, 2.0)
	# Top and bottom hoops.
	draw_ellipse_top(Vector2(-2.0, cage_top), 14.0, 5.0, rusti)
	draw_arc(Vector2(-2.0, cage_bot), 14.0, 0.0, PI, 12, rusti, 2.0)
	# Slumped corpse / bones inside.
	draw_circle(Vector2(-2.0, -26.0), 5.0, palette["bone"].darkened(0.15))
	draw_circle(Vector2(-4.0, -27.0), 1.3, palette["abyss"])
	draw_circle(Vector2(0.0, -27.0), 1.3, palette["abyss"])
	draw_line(Vector2(-2.0, -22.0), Vector2(-6.0, -19.0), palette["bone"].darkened(0.3), 2.0)


func _draw_hanging_cloth() -> void:
	draw_line(Vector2(-20.0, -44.0), Vector2(20.0, -44.0), palette["umber"].darkened(0.2), 2.0)
	var cloth: Color = palette["taupe"].darkened(0.3)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-16.0, -44.0), Vector2(-3.0, -44.0), Vector2(-5.0, -6.0),
		Vector2(-9.0, -2.0), Vector2(-14.0, -8.0)
	]), Color(cloth.r, cloth.g, cloth.b, 0.82))
	draw_colored_polygon(PackedVector2Array([
		Vector2(2.0, -44.0), Vector2(16.0, -44.0), Vector2(15.0, -10.0),
		Vector2(9.0, -4.0), Vector2(4.0, -9.0)
	]), Color(cloth.lightened(0.08).r, cloth.lightened(0.08).g, cloth.lightened(0.08).b, 0.8))
	draw_line(Vector2(-10.0, -42.0), Vector2(-8.0, -8.0), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.3), 1.0)
	draw_line(Vector2(9.0, -42.0), Vector2(10.0, -10.0), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.3), 1.0)
	draw_circle(Vector2(-12.0, -20.0), 3.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.28))
	draw_circle(Vector2(7.0, -30.0), 2.0, Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.4))


func _draw_hanging_lantern_post() -> void:
	draw_circle(Vector2(0.0, 4.0), 9.0, Color(0, 0, 0, 0.22))
	# stone footing
	_draw_box(Vector2(12.0, 12.0), 6.0, palette["ash"], palette["iron"])
	# tall post with a gallows arm reaching out
	draw_line(Vector2(0.0, -8.0), Vector2(0.0, -54.0), palette["iron"], 3.0)
	draw_line(Vector2(0.0, -54.0), Vector2(18.0, -54.0), palette["iron"], 3.0)
	# small brace
	draw_line(Vector2(0.0, -46.0), Vector2(10.0, -54.0), palette["iron"].darkened(0.2), 2.0)
	# chain dangling the lantern
	draw_line(Vector2(18.0, -54.0), Vector2(18.0, -44.0), palette["iron"].lightened(0.1), 1.5)
	# lantern body
	draw_colored_polygon(PackedVector2Array([Vector2(13.0, -44.0), Vector2(23.0, -44.0), Vector2(21.0, -32.0), Vector2(15.0, -32.0)]), palette["iron"])
	draw_rect(Rect2(14.0, -45.0, 8.0, 2.0), palette["gold"].darkened(0.2), true)
	# warm light (sulfur core + halo)
	var sf: Color = palette["sulfur"]
	draw_circle(Vector2(18.0, -38.0), 9.0, Color(sf.r, sf.g, sf.b, 0.16))
	draw_circle(Vector2(18.0, -38.0), 4.0, Color(sf.r, sf.g, sf.b, 0.5))
	draw_circle(Vector2(18.0, -38.0), 1.6, sf.lightened(0.35))


func _draw_hidden_chest() -> void:
	draw_circle(Vector2(0.0, 4.0), 24.0, Color(0, 0, 0, 0.22))
	# Cursed chest half-buried, lid sealed shut.
	_draw_box(Vector2(40.0, 24.0), 10.0, palette["eldritch"], palette["eldritch"].darkened(0.3))
	# Sealed iron-banded lid.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-20.0, -28.0), Vector2(-14.0, -36.0), Vector2(14.0, -36.0), Vector2(20.0, -28.0)
	]), palette["iron"].darkened(0.2))
	# Glowing eldritch seam where the lid meets (rare violet glow).
	draw_line(Vector2(-20.0, -28.0), Vector2(20.0, -28.0), palette["violet"].lightened(0.3), 2.0)
	draw_line(Vector2(-20.0, -28.0), Vector2(20.0, -28.0), Color(palette["violet"].r, palette["violet"].g, palette["violet"].b, 0.35), 6.0)
	# Cursed sigil on the lid.
	draw_circle(Vector2(0.0, -30.0), 4.0, palette["magenta"])
	draw_circle(Vector2(0.0, -30.0), 7.0, Color(palette["violet"].r, palette["violet"].g, palette["violet"].b, 0.3))


func _draw_kneeling_statue() -> void:
	draw_circle(Vector2(0.0, 6.0), 18.0, Color(0, 0, 0, 0.22))
	# Low plinth.
	_draw_box(Vector2(30.0, 18.0), 8.0, palette["ash"], palette["iron"])
	var stone: Color = palette["ash"].lightened(0.06)
	var dark: Color = palette["iron"]
	# Kneeling, mourning figure — bent, hooded.
	# Lower robe / kneeling base.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-12.0, -10.0), Vector2(12.0, -10.0),
		Vector2(8.0, -30.0), Vector2(-9.0, -30.0)
	]), stone)
	# Bowed back / hunched torso.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-9.0, -30.0), Vector2(8.0, -30.0),
		Vector2(11.0, -42.0), Vector2(-2.0, -44.0)
	]), stone)
	# Hooded head bowed forward.
	draw_circle(Vector2(3.0, -42.0), 6.0, stone)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-3.0, -44.0), Vector2(8.0, -44.0), Vector2(9.0, -38.0), Vector2(-1.0, -38.0)
	]), dark)
	# Clasped-hands shadow in the lap.
	draw_circle(Vector2(0.0, -22.0), 3.0, dark)
	# Worn grime streaks down the robe.
	draw_line(Vector2(-4.0, -28.0), Vector2(-5.0, -12.0), Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.4), 2.0)


func _draw_knife_marks_wall() -> void:
	var gash: Color = Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.55)
	draw_line(Vector2(-12.0, -2.0), Vector2(-6.0, -22.0), gash, 2.0)
	draw_line(Vector2(-4.0, 0.0), Vector2(1.0, -20.0), gash, 2.0)
	draw_line(Vector2(5.0, -3.0), Vector2(10.0, -24.0), gash, 2.0)
	draw_line(Vector2(-10.0, -10.0), Vector2(9.0, -14.0), gash, 1.0)
	var nick: Color = Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.4)
	draw_line(Vector2(-7.0, -6.0), Vector2(-3.0, -18.0), nick, 1.0)
	draw_line(Vector2(7.0, -8.0), Vector2(11.0, -19.0), nick, 1.0)


func _draw_knife_table() -> void:
	draw_circle(Vector2(0.0, 4.0), 28.0, Color(0, 0, 0, 0.22))
	# Butcher / weapon-monger table, blood-stained.
	_draw_box(Vector2(50.0, 26.0), 12.0, palette["wood"], palette["wood_dark"])
	# Dried blood stains on the surface (flat low-alpha).
	draw_circle(Vector2(-10.0, -16.0), 7.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.5))
	draw_circle(Vector2(6.0, -10.0), 4.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.4))
	# Knives stuck point-down into the wood.
	draw_line(Vector2(-14.0, -18.0), Vector2(-14.0, -36.0), palette["ash"], 2.0)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-16.0, -28.0), Vector2(-12.0, -28.0), Vector2(-14.0, -36.0)
	]), palette["bone"].darkened(0.1))
	draw_line(Vector2(8.0, -16.0), Vector2(12.0, -34.0), palette["iron"], 2.0)
	draw_rect(Rect2(6.0, -16.0, 5.0, 4.0), palette["umber"], true)


func _draw_lantern_post() -> void:
	draw_circle(Vector2(0.0, 4.0), 9.0, Color(0, 0, 0, 0.22))
	# stone base
	_draw_box(Vector2(12.0, 12.0), 6.0, palette["ash"], palette["iron"])
	# tall iron post
	draw_line(Vector2(0.0, -8.0), Vector2(0.0, -48.0), palette["iron"], 3.0)
	# little cross-arm
	draw_line(Vector2(0.0, -48.0), Vector2(6.0, -48.0), palette["iron"], 2.0)
	# hanging lantern cage
	draw_rect(Rect2(2.0, -47.0, 9.0, 11.0), palette["iron"], true)
	draw_rect(Rect2(2.0, -47.0, 9.0, 11.0), palette["abyss"], false, 1.0)
	# candle glow inside (sulfur core + halo)
	var sf: Color = palette["sulfur"]
	draw_circle(Vector2(6.5, -41.0), 7.0, Color(sf.r, sf.g, sf.b, 0.18))
	draw_circle(Vector2(6.5, -41.0), 3.5, Color(sf.r, sf.g, sf.b, 0.5))
	draw_circle(Vector2(6.5, -41.0), 1.5, sf.lightened(0.3))


func _draw_ledger_table() -> void:
	draw_circle(Vector2(0.0, 4.0), 28.0, Color(0, 0, 0, 0.22))
	# Writing table.
	_draw_box(Vector2(50.0, 28.0), 12.0, palette["wood"], palette["wood_dark"])
	# Open ledger / parchment on top (negative Y, flat-ish).
	draw_colored_polygon(PackedVector2Array([
		Vector2(-18.0, -22.0), Vector2(2.0, -24.0), Vector2(0.0, -10.0), Vector2(-20.0, -8.0)
	]), palette["bone"].darkened(0.1))
	draw_colored_polygon(PackedVector2Array([
		Vector2(2.0, -24.0), Vector2(20.0, -22.0), Vector2(18.0, -8.0), Vector2(0.0, -10.0)
	]), palette["bone"].darkened(0.2))
	draw_line(Vector2(2.0, -24.0), Vector2(0.0, -10.0), palette["umber"], 1.0)
	# Quill and inkpot.
	draw_line(Vector2(14.0, -20.0), Vector2(22.0, -34.0), palette["ash"], 1.5)
	draw_rect(Rect2(-24.0, -16.0, 6.0, 6.0), palette["iron"], true)


func _draw_lockbox_stack() -> void:
	draw_circle(Vector2(0.0, 4.0), 24.0, Color(0, 0, 0, 0.22))
	# Bottom iron-banded box.
	_draw_box(Vector2(40.0, 26.0), 14.0, palette["iron"], palette["iron"].darkened(0.3))
	# Rusted band + lock on the lower box face.
	draw_rect(Rect2(-4.0, 0.0, 8.0, 6.0), palette["rust"], true)
	# Smaller box stacked askew on top.
	draw_rect(Rect2(-14.0, -40.0, 28.0, 4.0), palette["iron"].darkened(0.3), true)
	draw_rect(Rect2(-14.0, -56.0, 28.0, 16.0), palette["umber"], true)
	draw_rect(Rect2(-14.0, -56.0, 28.0, 3.0), palette["wood"].lightened(0.15), true)
	draw_rect(Rect2(-14.0, -56.0, 28.0, 16.0), palette["iron"], false, 1.5)
	# Tiny lock glint.
	draw_rect(Rect2(-2.0, -46.0, 4.0, 5.0), palette["gold"].darkened(0.1), true)


func _draw_map_wall() -> void:
	var parch: Color = palette["bone"].darkened(0.28)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-20.0, -30.0), Vector2(20.0, -31.0), Vector2(21.0, -4.0), Vector2(-19.0, -3.0)
	]), Color(parch.r, parch.g, parch.b, 0.85))
	draw_rect(Rect2(-20.0, -31.0, 41.0, 28.0), Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.7), false, 1.0)
	var ink: Color = Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.6)
	draw_line(Vector2(-14.0, -10.0), Vector2(-2.0, -22.0), ink, 1.0)
	draw_line(Vector2(-2.0, -22.0), Vector2(12.0, -14.0), ink, 1.0)
	draw_line(Vector2(12.0, -14.0), Vector2(4.0, -6.0), ink, 1.0)
	draw_circle(Vector2(3.0, -16.0), 2.0, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.6))
	draw_line(Vector2(3.0, -16.0), Vector2(8.0, -20.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.5), 1.0)


func _draw_market_stall() -> void:
	draw_circle(Vector2(0.0, 4.0), 34.0, Color(0, 0, 0, 0.22))
	# Rotting counter plank on splayed legs.
	_draw_box(Vector2(60.0, 22.0), 10.0, palette["wood"], palette["wood_dark"])
	# Sagging, filthy awning frame (negative Y).
	draw_line(Vector2(-28.0, -14.0), Vector2(-28.0, -48.0), palette["umber"], 3.0)
	draw_line(Vector2(28.0, -14.0), Vector2(28.0, -48.0), palette["umber"], 3.0)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-34.0, -46.0), Vector2(34.0, -46.0), Vector2(30.0, -34.0), Vector2(-30.0, -36.0)
	]), palette["taupe"].darkened(0.25))
	# Torn tattered hem.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-30.0, -36.0), Vector2(-16.0, -30.0), Vector2(-2.0, -36.0), Vector2(12.0, -28.0), Vector2(30.0, -34.0), Vector2(30.0, -36.0)
	]), palette["blood"].darkened(0.2))
	# A scrap of tarnished wares.
	draw_circle(Vector2(-12.0, -16.0), 4.0, palette["rust"])
	draw_circle(Vector2(10.0, -16.0), 3.0, palette["gold"])


func _draw_mausoleum() -> void:
	draw_circle(Vector2(0.0, 8.0), 34.0, Color(0, 0, 0, 0.22))
	# Blackened stone tomb body.
	_draw_box(Vector2(54.0, 34.0), 30.0, palette["ash"].darkened(0.1), palette["iron"])
	# Heavy pitched roof slab on top.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-30.0, -47.0), Vector2(30.0, -47.0),
		Vector2(20.0, -62.0), Vector2(-20.0, -62.0)
	]), palette["ash"])
	draw_colored_polygon(PackedVector2Array([
		Vector2(-30.0, -47.0), Vector2(30.0, -47.0),
		Vector2(30.0, -43.0), Vector2(-30.0, -43.0)
	]), palette["iron"])
	# Sealed iron door, recessed in shadow.
	draw_rect(Rect2(-9.0, -40.0, 18.0, 22.0), palette["abyss"], true)
	draw_rect(Rect2(-9.0, -40.0, 18.0, 22.0), palette["iron"].lightened(0.1), false, 1.0)
	draw_line(Vector2(0.0, -40.0), Vector2(0.0, -18.0), palette["iron"], 1.0)
	# Tarnished gold cross above the door.
	draw_line(Vector2(0.0, -56.0), Vector2(0.0, -45.0), palette["gold"], 2.0)
	draw_line(Vector2(-5.0, -52.0), Vector2(5.0, -52.0), palette["gold"], 2.0)
	# Moss / grime streak.
	draw_rect(Rect2(-24.0, -38.0, 6.0, 20.0), Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.4), true)


func _draw_notice_board() -> void:
	draw_circle(Vector2(0.0, 4.0), 18.0, Color(0, 0, 0, 0.22))
	var w: Color = palette["umber"]
	var wd: Color = w.darkened(0.35)
	# two posts
	draw_line(Vector2(-18.0, 4.0), Vector2(-18.0, -34.0), wd, 4.0)
	draw_line(Vector2(18.0, 4.0), Vector2(18.0, -34.0), wd, 4.0)
	# weathered board
	draw_rect(Rect2(-22.0, -40.0, 44.0, 28.0), w, true)
	draw_rect(Rect2(-22.0, -40.0, 44.0, 3.0), w.lightened(0.18), true)
	draw_rect(Rect2(-22.0, -40.0, 44.0, 28.0), palette["abyss"], false, 1.5)
	draw_line(Vector2(-22.0, -26.0), Vector2(22.0, -26.0), wd, 1.0)
	# tattered parchment notices (bone), one torn
	draw_rect(Rect2(-17.0, -36.0, 12.0, 14.0), palette["bone"].darkened(0.1), true)
	draw_colored_polygon(PackedVector2Array([Vector2(2.0, -36.0), Vector2(15.0, -36.0), Vector2(15.0, -24.0), Vector2(9.0, -22.0), Vector2(2.0, -25.0)]), palette["bone"].darkened(0.2))
	# faint ink lines
	draw_line(Vector2(-15.0, -32.0), Vector2(-7.0, -32.0), palette["iron"], 1.0)
	draw_line(Vector2(-15.0, -29.0), Vector2(-8.0, -29.0), palette["iron"], 1.0)


func _draw_notice_wall() -> void:
	var paper: Color = palette["bone"].darkened(0.18)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-14.0, -28.0), Vector2(14.0, -29.0), Vector2(15.0, -5.0), Vector2(-13.0, -4.0)
	]), Color(paper.r, paper.g, paper.b, 0.85))
	draw_rect(Rect2(-14.0, -29.0, 29.0, 25.0), Color(palette["iron"].r, palette["iron"].g, palette["iron"].b, 0.6), false, 1.0)
	var ink: Color = Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5)
	for i in range(5):
		var y := -23.0 + float(i) * 4.0
		var w := 22.0 - float(i % 2) * 6.0
		draw_rect(Rect2(-10.0, y, w, 1.5), ink, true)
	draw_circle(Vector2(-11.0, -26.0), 1.5, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.7))
	draw_circle(Vector2(12.0, -26.0), 1.5, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.7))


func _draw_obelisk() -> void:
	# A tall blackened standing stone carved with cursed runes, a faint cold gleam at its tip.
	var stone_top: Color = palette["ash"]
	var stone_face: Color = palette["iron"]
	var rune: Color = palette["teal"]
	draw_circle(Vector2(0.0, 5.0), 16.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Plinth base.
	_draw_box(Vector2(26.0, 12.0), 6.0, stone_top, stone_face)
	# Tapered shaft: darker south face.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-9.0, -16.0), Vector2(9.0, -16.0), Vector2(4.0, -66.0), Vector2(-4.0, -66.0)
	]), stone_face)
	# Sunlit left edge of the shaft.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-9.0, -16.0), Vector2(-4.0, -16.0), Vector2(-1.0, -66.0), Vector2(-4.0, -66.0)
	]), stone_top)
	# Carved runes glowing faintly.
	draw_line(Vector2(-3.0, -28.0), Vector2(3.0, -28.0), Color(rune.r, rune.g, rune.b, 0.5), 1.0)
	draw_line(Vector2(0.0, -42.0), Vector2(0.0, -34.0), Color(rune.r, rune.g, rune.b, 0.5), 1.0)
	draw_line(Vector2(-2.0, -52.0), Vector2(2.0, -50.0), Color(rune.r, rune.g, rune.b, 0.5), 1.0)
	# Cracks.
	draw_line(Vector2(5.0, -20.0), Vector2(2.0, -40.0), stone_face.darkened(0.3), 1.0)
	# Cold gleam at the apex.
	draw_circle(Vector2(0.0, -66.0), 3.0, rune.lightened(0.2))
	draw_circle(Vector2(0.0, -66.0), 8.0, Color(rune.r, rune.g, rune.b, 0.15))


func _draw_pew_left_01() -> void:
	draw_circle(Vector2(0.0, 4.0), 22.0, Color(0, 0, 0, 0.2))
	# Long bench seat, worn rotting wood.
	_draw_box(Vector2(50.0, 14.0), 8.0, palette["umber"], palette["umber"].darkened(0.35))
	# Tall backrest along the rear (north) edge.
	draw_rect(Rect2(-25.0, -28.0, 50.0, 12.0), palette["umber"].darkened(0.15), true)
	draw_rect(Rect2(-25.0, -28.0, 50.0, 2.0), palette["umber"].lightened(0.15), true)
	# Plank gaps in the backrest.
	draw_line(Vector2(-8.0, -28.0), Vector2(-8.0, -16.0), palette["umber"].darkened(0.4), 1.5)
	draw_line(Vector2(8.0, -28.0), Vector2(8.0, -16.0), palette["umber"].darkened(0.4), 1.5)
	# Dust and ash settled on the worn seat.
	draw_rect(Rect2(-22.0, -20.0, 18.0, 4.0), Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.3), true)


func _draw_pew_left_02() -> void:
	draw_circle(Vector2(0.0, 4.0), 22.0, Color(0, 0, 0, 0.2))
	# Long bench seat, darker rotting wood.
	_draw_box(Vector2(50.0, 14.0), 8.0, palette["umber"].darkened(0.1), palette["umber"].darkened(0.4))
	# Tall backrest along the rear edge.
	draw_rect(Rect2(-25.0, -28.0, 50.0, 12.0), palette["umber"].darkened(0.2), true)
	draw_rect(Rect2(-25.0, -28.0, 50.0, 2.0), palette["umber"].lightened(0.1), true)
	# Splintered missing plank near the left end.
	draw_rect(Rect2(-24.0, -28.0, 7.0, 12.0), palette["abyss"], true)
	draw_line(Vector2(6.0, -28.0), Vector2(6.0, -16.0), palette["umber"].darkened(0.45), 1.5)
	# Old dried blood smear on the seat.
	draw_rect(Rect2(2.0, -20.0, 16.0, 4.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.45), true)


func _draw_pew_right_01() -> void:
	draw_circle(Vector2(0.0, 4.0), 22.0, Color(0, 0, 0, 0.2))
	# Long bench seat, worn rotting wood.
	_draw_box(Vector2(50.0, 14.0), 8.0, palette["umber"], palette["umber"].darkened(0.35))
	# Tall backrest along the rear edge.
	draw_rect(Rect2(-25.0, -28.0, 50.0, 12.0), palette["umber"].darkened(0.15), true)
	draw_rect(Rect2(-25.0, -28.0, 50.0, 2.0), palette["umber"].lightened(0.15), true)
	# Plank gaps in the backrest.
	draw_line(Vector2(-6.0, -28.0), Vector2(-6.0, -16.0), palette["umber"].darkened(0.4), 1.5)
	draw_line(Vector2(10.0, -28.0), Vector2(10.0, -16.0), palette["umber"].darkened(0.4), 1.5)
	# Ash dust drifted to the right end of the seat.
	draw_rect(Rect2(4.0, -20.0, 18.0, 4.0), Color(palette["ash"].r, palette["ash"].g, palette["ash"].b, 0.3), true)


func _draw_pew_right_02() -> void:
	draw_circle(Vector2(0.0, 4.0), 22.0, Color(0, 0, 0, 0.2))
	# Long bench seat, darker rotting wood.
	_draw_box(Vector2(50.0, 14.0), 8.0, palette["umber"].darkened(0.1), palette["umber"].darkened(0.4))
	# Tall backrest along the rear edge.
	draw_rect(Rect2(-25.0, -28.0, 50.0, 12.0), palette["umber"].darkened(0.2), true)
	draw_rect(Rect2(-25.0, -28.0, 50.0, 2.0), palette["umber"].lightened(0.1), true)
	# Splintered missing plank near the right end.
	draw_rect(Rect2(17.0, -28.0, 7.0, 12.0), palette["abyss"], true)
	draw_line(Vector2(-6.0, -28.0), Vector2(-6.0, -16.0), palette["umber"].darkened(0.45), 1.5)
	# Old dried blood smear on the seat.
	draw_rect(Rect2(-18.0, -20.0, 16.0, 4.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.45), true)


func _draw_prayer_strip_wall() -> void:
	var cloth: Color = palette["bone"].darkened(0.25)
	var strips := [-14.0, -5.0, 4.0, 13.0]
	for i in range(strips.size()):
		var x: float = strips[i]
		var lift := -2.0 - float(i % 2) * 3.0
		draw_colored_polygon(PackedVector2Array([
			Vector2(x - 3.0, -28.0), Vector2(x + 3.0, -28.0),
			Vector2(x + 3.0, -8.0 + lift), Vector2(x, -4.0 + lift), Vector2(x - 3.0, -8.0 + lift)
		]), Color(cloth.r, cloth.g, cloth.b, 0.75))
		draw_line(Vector2(x, -26.0), Vector2(x, -8.0 + lift), Color(palette["gold"].r, palette["gold"].g, palette["gold"].b, 0.4), 1.0)
	draw_line(Vector2(-18.0, -28.0), Vector2(18.0, -28.0), palette["umber"].darkened(0.2), 2.0)


func _draw_refugee_tent() -> void:
	draw_circle(Vector2(0.0, 4.0), 26.0, Color(0, 0, 0, 0.22))
	var cloth: Color = palette["taupe"]
	var cloth_dark: Color = cloth.darkened(0.4)
	# sagging canvas: dark south flank + lit ridge
	draw_colored_polygon(PackedVector2Array([Vector2(-24.0, 6.0), Vector2(0.0, -34.0), Vector2(2.0, 6.0)]), cloth_dark)
	draw_colored_polygon(PackedVector2Array([Vector2(0.0, -34.0), Vector2(24.0, 6.0), Vector2(2.0, 6.0)]), cloth)
	# patched, filthy hide
	draw_colored_polygon(PackedVector2Array([Vector2(8.0, -6.0), Vector2(16.0, -2.0), Vector2(13.0, 4.0), Vector2(6.0, 2.0)]), palette["umber"])
	draw_line(Vector2(0.0, -34.0), Vector2(0.0, 6.0), cloth.lightened(0.15), 2.0)
	# dark doorway opening
	draw_colored_polygon(PackedVector2Array([Vector2(-7.0, 6.0), Vector2(0.0, -16.0), Vector2(7.0, 6.0)]), palette["abyss"])
	# guy-rope stakes
	draw_line(Vector2(-24.0, 6.0), Vector2(-32.0, 8.0), palette["iron"], 1.5)
	draw_line(Vector2(24.0, 6.0), Vector2(32.0, 8.0), palette["iron"], 1.5)
	# ground stain at the threshold (flat decal)
	draw_circle(Vector2(0.0, 8.0), 9.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.18))


func _draw_ritual_blood_stain() -> void:
	var b: Color = palette["blood"]
	draw_circle(Vector2.ZERO, 17.0, Color(b.r, b.g, b.b, 0.4))
	draw_arc(Vector2.ZERO, 16.0, 0.0, TAU, 32, Color(palette["magenta"].r, palette["magenta"].g, palette["magenta"].b, 0.5), 2.0)
	var mark: Color = Color(palette["magenta"].r, palette["magenta"].g, palette["magenta"].b, 0.55)
	for i in range(5):
		var a := TAU * float(i) / 5.0 - PI * 0.5
		var p := Vector2(cos(a), sin(a)) * 13.0
		draw_line(p, Vector2(-p.x, -p.y) * 0.62, mark, 2.0)
	draw_circle(Vector2.ZERO, 4.0, Color(b.r, b.g, b.b, 0.6))
	draw_circle(Vector2.ZERO, 2.0, Color(palette["violet"].r, palette["violet"].g, palette["violet"].b, 0.4))


func _draw_ritual_circle() -> void:
	# A flat summoning sigil chalked on the ground: rings, an inscribed star, glowing runes.
	var mark: Color = palette["magenta"]
	var glow: Color = palette["violet"]
	var r := 26.0
	# Faint corruption wash on the floor (flat decal, no shadow).
	draw_circle(Vector2.ZERO, r + 4.0, Color(glow.r, glow.g, glow.b, 0.07))
	# Outer and inner rings.
	draw_arc(Vector2.ZERO, r, 0.0, TAU, 40, Color(mark.r, mark.g, mark.b, 0.7), 2.0)
	draw_arc(Vector2.ZERO, r - 6.0, 0.0, TAU, 40, Color(mark.r, mark.g, mark.b, 0.5), 1.0)
	# Inscribed five-point star.
	var star := PackedVector2Array()
	for i in range(5):
		var a := -PI * 0.5 + TAU * float(i * 2) / 5.0
		star.append(Vector2(cos(a), sin(a)) * (r - 7.0))
	star.append(star[0])
	draw_polyline(star, Color(glow.r, glow.g, glow.b, 0.65), 2.0)
	# Rune ticks around the ring.
	for i in range(8):
		var a := TAU * float(i) / 8.0
		var p := Vector2(cos(a), sin(a))
		draw_line(p * (r - 3.0), p * (r + 2.0), Color(mark.r, mark.g, mark.b, 0.6), 1.0)
	# Glowing core at the heart of the circle.
	draw_circle(Vector2.ZERO, 3.0, glow.lightened(0.25))
	draw_circle(Vector2.ZERO, 7.0, Color(glow.r, glow.g, glow.b, 0.18))


func _draw_ritual_table() -> void:
	# A blood-stained altar table strewn with candles, bone, and a cursed grimoire.
	var wood: Color = palette["umber"]
	var wood_dark: Color = wood.darkened(0.3)
	draw_circle(Vector2(0.0, 5.0), 24.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Old blood pooled flat beneath the table.
	draw_circle(Vector2(2.0, 2.0), 18.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.4))
	# Table slab as oblique box.
	_draw_box(Vector2(48.0, 22.0), 16.0, wood, wood_dark)
	# Dark blood stain on the tabletop.
	draw_circle(Vector2(-6.0, -22.0), 7.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.55))
	# Open grimoire on the surface.
	draw_rect(Rect2(2.0, -28.0, 16.0, 9.0), palette["bone"].darkened(0.25), true)
	draw_line(Vector2(10.0, -28.0), Vector2(10.0, -19.0), wood_dark, 1.0)
	draw_line(Vector2(5.0, -24.0), Vector2(8.0, -23.0), palette["magenta"], 1.0)
	# Two candle stubs with halos.
	draw_rect(Rect2(-19.0, -30.0, 4.0, 9.0), palette["bone"], true)
	draw_circle(Vector2(-17.0, -32.0), 2.0, palette["sulfur"].lightened(0.2))
	draw_circle(Vector2(-17.0, -32.0), 5.0, Color(palette["sulfur"].r, palette["sulfur"].g, palette["sulfur"].b, 0.18))
	draw_rect(Rect2(18.0, -28.0, 4.0, 7.0), palette["bone"], true)
	draw_circle(Vector2(20.0, -30.0), 2.0, palette["sulfur"].lightened(0.2))
	# A skull set at the table edge.
	draw_circle(Vector2(-14.0, -20.0), 4.0, palette["bone"])
	draw_circle(Vector2(-15.0, -20.0), 1.0, palette["abyss"])


func _draw_sewer_grate() -> void:
	draw_rect(Rect2(-16.0, -14.0, 32.0, 28.0), palette["iron"].darkened(0.2), true)
	draw_rect(Rect2(-14.0, -12.0, 28.0, 24.0), palette["abyss"], true)
	var bar: Color = palette["iron"].lightened(0.05)
	for i in range(4):
		var x := -11.0 + float(i) * 7.0
		draw_rect(Rect2(x, -12.0, 3.0, 24.0), bar, true)
	draw_rect(Rect2(-14.0, -3.0, 28.0, 2.0), bar.darkened(0.2), true)
	draw_rect(Rect2(-16.0, -14.0, 32.0, 28.0), palette["rust"].darkened(0.1), false, 2.0)
	draw_circle(Vector2(-9.0, 6.0), 2.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.3))


func _draw_shelf_potions() -> void:
	draw_circle(Vector2(0.0, 4.0), 26.0, Color(0, 0, 0, 0.22))
	# Tall narrow shelf cabinet.
	_draw_box(Vector2(40.0, 18.0), 8.0, palette["wood"], palette["wood_dark"])
	draw_rect(Rect2(-20.0, -56.0, 40.0, 48.0), palette["wood_dark"], true)
	draw_rect(Rect2(-20.0, -56.0, 40.0, 48.0), palette["abyss"], false, 1.0)
	# Two shelf ledges.
	draw_rect(Rect2(-20.0, -40.0, 40.0, 3.0), palette["wood"], true)
	draw_rect(Rect2(-20.0, -24.0, 40.0, 3.0), palette["wood"], true)
	# Glowing potion vials (rare eldritch light).
	draw_rect(Rect2(-15.0, -50.0, 6.0, 9.0), palette["teal"], true)
	draw_circle(Vector2(-12.0, -50.0), 5.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.3))
	draw_rect(Rect2(0.0, -50.0, 6.0, 9.0), palette["magenta"], true)
	draw_rect(Rect2(-8.0, -34.0, 6.0, 9.0), palette["sulfur"], true)


func _draw_skull_reliquary() -> void:
	draw_circle(Vector2(0.0, 4.0), 16.0, Color(0, 0, 0, 0.22))
	# Pedestal of dark stone.
	_draw_box(Vector2(24.0, 16.0), 14.0, palette["ash"], palette["iron"])
	# Tarnished gold reliquary band on the pedestal.
	draw_rect(Rect2(-12.0, -22.0, 24.0, 3.0), palette["gold"], true)
	# A single skull enshrined, lit by soul-light.
	var bone: Color = palette["bone"]
	draw_circle(Vector2(0.0, -34.0), 9.0, bone)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-5.0, -28.0), Vector2(5.0, -28.0),
		Vector2(3.0, -22.0), Vector2(-3.0, -22.0)
	]), bone)
	# Hollow sockets glowing teal (soul).
	draw_circle(Vector2(-3.5, -35.0), 2.4, palette["teal"])
	draw_circle(Vector2(3.5, -35.0), 2.4, palette["teal"])
	draw_circle(Vector2(-3.5, -35.0), 4.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.3))
	draw_circle(Vector2(3.5, -35.0), 4.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.3))
	# Soul halo around the whole skull.
	draw_circle(Vector2(0.0, -34.0), 15.0, Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.14))


func _draw_sleeping_roll() -> void:
	var cloth: Color = palette["taupe"].darkened(0.15)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-20.0, -7.0), Vector2(18.0, -8.0), Vector2(20.0, 7.0), Vector2(-18.0, 8.0)
	]), Color(cloth.r, cloth.g, cloth.b, 0.8))
	for i in range(4):
		var x := -14.0 + float(i) * 9.0
		draw_line(Vector2(x, -7.0), Vector2(x + 1.0, 7.0), Color(palette["umber"].r, palette["umber"].g, palette["umber"].b, 0.35), 1.0)
	draw_colored_polygon(PackedVector2Array([
		Vector2(14.0, -8.0), Vector2(20.0, -6.0), Vector2(20.0, 7.0), Vector2(15.0, 8.0)
	]), Color(palette["bone"].r, palette["bone"].g, palette["bone"].b, 0.3))
	draw_line(Vector2(-18.0, 8.0), Vector2(20.0, 7.0), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.25), 1.0)


func _draw_table() -> void:
	draw_circle(Vector2(0.0, 4.0), 30.0, Color(0, 0, 0, 0.22))
	# Plain rotting-wood table.
	_draw_box(Vector2(54.0, 30.0), 14.0, palette["wood"], palette["wood_dark"])
	# Plank seams.
	draw_line(Vector2(-27.0, -22.0), Vector2(27.0, -22.0), palette["wood_dark"], 1.0)
	draw_line(Vector2(-27.0, -8.0), Vector2(27.0, -8.0), palette["wood_dark"], 1.0)
	# Knot / rot mark.
	draw_circle(Vector2(-10.0, -16.0), 3.0, palette["umber"].darkened(0.3))
	draw_circle(Vector2(8.0, -20.0), 2.0, palette["abyss"])


func _draw_tavern_sign() -> void:
	draw_circle(Vector2(0.0, 4.0), 10.0, Color(0, 0, 0, 0.22))
	var wd: Color = palette["umber"].darkened(0.4)
	# wall bracket post
	draw_line(Vector2(0.0, 4.0), Vector2(0.0, -50.0), wd, 4.0)
	# iron arm jutting out
	draw_line(Vector2(0.0, -50.0), Vector2(22.0, -50.0), palette["iron"], 2.5)
	draw_line(Vector2(0.0, -42.0), Vector2(14.0, -50.0), palette["iron"].darkened(0.2), 1.5)
	# two short chains
	draw_line(Vector2(8.0, -50.0), Vector2(8.0, -42.0), palette["iron"].lightened(0.1), 1.0)
	draw_line(Vector2(20.0, -50.0), Vector2(20.0, -42.0), palette["iron"].lightened(0.1), 1.0)
	# swinging sign board, weathered with faded gold trim
	var w: Color = palette["umber"]
	draw_rect(Rect2(4.0, -42.0, 20.0, 16.0), w, true)
	draw_rect(Rect2(4.0, -42.0, 20.0, 16.0), palette["gold"].darkened(0.3), false, 1.5)
	draw_rect(Rect2(4.0, -42.0, 20.0, 2.0), w.lightened(0.12), true)
	# crude painted tankard emblem in tarnished gold
	var g: Color = palette["gold"]
	draw_rect(Rect2(10.0, -38.0, 7.0, 8.0), g, true)
	draw_line(Vector2(17.0, -37.0), Vector2(20.0, -35.0), g, 1.5)
	draw_rect(Rect2(10.0, -39.0, 7.0, 2.0), palette["bone"], true)


func _draw_trade_board() -> void:
	draw_circle(Vector2(0.0, 4.0), 18.0, Color(0, 0, 0, 0.22))
	var w: Color = palette["umber"]
	var wd: Color = w.darkened(0.4)
	# single thick post
	draw_line(Vector2(0.0, 4.0), Vector2(0.0, -20.0), wd, 6.0)
	# angled board with gold trade trim
	_draw_box(Vector2(40.0, 10.0), 22.0, w, wd)
	draw_rect(Rect2(-20.0, -34.0, 40.0, 2.0), palette["gold"], true)
	draw_rect(Rect2(-20.0, -16.0, 40.0, 2.0), palette["gold"].darkened(0.2), true)
	# scrawled wares (parchment strips)
	draw_rect(Rect2(-16.0, -31.0, 9.0, 12.0), palette["bone"].darkened(0.15), true)
	draw_rect(Rect2(-3.0, -31.0, 9.0, 12.0), palette["taupe"].lightened(0.1), true)
	draw_rect(Rect2(10.0, -31.0, 7.0, 12.0), palette["bone"].darkened(0.3), true)
	# a tarnished coin nailed up as a sign
	draw_circle(Vector2(0.0, -25.0), 3.5, palette["gold"])
	draw_circle(Vector2(0.0, -25.0), 3.5, palette["gold"].darkened(0.4), false, 1.0)
	draw_line(Vector2(-16.0, -27.0), Vector2(-9.0, -27.0), palette["iron"], 1.0)


func _draw_training_dummy() -> void:
	draw_circle(Vector2(0.0, 5.0), 14.0, Color(0, 0, 0, 0.22))
	# Rotting wooden post driven into the ground.
	draw_rect(Rect2(-4.0, -34.0, 8.0, 40.0), palette["umber"], true)
	draw_rect(Rect2(-4.0, -34.0, 2.0, 40.0), palette["umber"].darkened(0.25), true)
	# Filthy burlap-stuffed torso.
	draw_circle(Vector2(0.0, -42.0), 13.0, palette["taupe"].darkened(0.15))
	draw_circle(Vector2(-4.0, -46.0), 5.0, palette["taupe"].darkened(0.05))
	# Lashing ropes binding the stuffing.
	draw_rect(Rect2(-13.0, -48.0, 26.0, 3.0), palette["umber"].darkened(0.1), true)
	draw_rect(Rect2(-13.0, -38.0, 26.0, 3.0), palette["umber"].darkened(0.1), true)
	# Crossbar 'arms' of lashed wood.
	draw_rect(Rect2(-20.0, -46.0, 40.0, 5.0), palette["umber"].lightened(0.05), true)
	# Hack-marks and old dried blood from drilling.
	draw_line(Vector2(-6.0, -50.0), Vector2(2.0, -42.0), palette["abyss"], 2.0)
	draw_circle(Vector2(4.0, -44.0), 3.0, Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.5))


func _draw_vault_door() -> void:
	draw_circle(Vector2(0.0, 4.0), 34.0, Color(0, 0, 0, 0.28))
	# Massive iron vault door slab.
	draw_rect(Rect2(-26.0, -64.0, 52.0, 70.0), palette["iron"].darkened(0.3), true)
	draw_rect(Rect2(-26.0, -64.0, 52.0, 70.0), palette["abyss"], false, 2.0)
	# Sunlit top bevel.
	draw_rect(Rect2(-26.0, -64.0, 52.0, 4.0), palette["ash"], true)
	# Heavy rivets around the frame.
	for ry in [-58.0, -42.0, -26.0, -10.0]:
		draw_circle(Vector2(-20.0, ry), 2.0, palette["rust"])
		draw_circle(Vector2(20.0, ry), 2.0, palette["rust"])
	# Central wheel-lock.
	draw_circle(Vector2(0.0, -32.0), 12.0, palette["iron"])
	draw_circle(Vector2(0.0, -32.0), 12.0, palette["ash"], false, 2.0)
	draw_circle(Vector2(0.0, -32.0), 4.0, palette["gold"].darkened(0.2))
	draw_line(Vector2(-12.0, -32.0), Vector2(12.0, -32.0), palette["iron"].darkened(0.2), 2.0)
	draw_line(Vector2(0.0, -44.0), Vector2(0.0, -20.0), palette["iron"].darkened(0.2), 2.0)


func _draw_vendor_counter() -> void:
	draw_circle(Vector2(0.0, 4.0), 34.0, Color(0, 0, 0, 0.22))
	# Stone-topped vendor counter.
	_draw_box(Vector2(64.0, 26.0), 14.0, palette["stone"], palette["stone_dark"])
	# Tarnished gold trim line.
	draw_line(Vector2(-32.0, -26.0), Vector2(32.0, -26.0), palette["gold"].darkened(0.15), 2.0)
	# Goods laid out: scroll + dull gem.
	draw_rect(Rect2(-22.0, -36.0, 14.0, 8.0), palette["bone"].darkened(0.15), true)
	draw_line(Vector2(-22.0, -32.0), Vector2(-8.0, -32.0), palette["umber"], 1.0)
	draw_circle(Vector2(12.0, -30.0), 4.0, palette["violet"].darkened(0.1))
	draw_circle(Vector2(12.0, -31.0), 2.0, palette["violet"].lightened(0.3))


func _draw_void_crack() -> void:
	# A jagged fissure tearing upward out of the ground, leaking violet void-light.
	var void_col: Color = palette["eldritch"]
	var glow: Color = palette["violet"]
	draw_circle(Vector2(0.0, 4.0), 16.0, Color(0, 0, 0, 0.22))  # contact shadow
	# Halo so it reads when unpowered.
	draw_circle(Vector2(0.0, -18.0), 22.0, Color(glow.r, glow.g, glow.b, 0.12))
	# Main crack body: a tall narrow void wedge.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-3.0, 6.0), Vector2(3.0, 6.0), Vector2(6.0, -16.0),
		Vector2(2.0, -40.0), Vector2(-1.0, -28.0), Vector2(-5.0, -14.0)
	]), void_col)
	# Branch fractures.
	draw_line(Vector2(2.0, -18.0), Vector2(12.0, -26.0), void_col, 2.0)
	draw_line(Vector2(-3.0, -10.0), Vector2(-11.0, -16.0), void_col, 2.0)
	# Bright inner seam.
	draw_line(Vector2(0.0, 4.0), Vector2(1.0, -38.0), glow, 2.0)
	draw_line(Vector2(1.0, -22.0), Vector2(6.0, -28.0), glow.lightened(0.2), 1.0)
	# Hot core at the tear's heart.
	draw_circle(Vector2(1.0, -22.0), 3.0, palette["magenta"].lightened(0.25))


func _draw_void_crack_ground() -> void:
	# A flat decal: a void fissure splitting the floor, no lift, no shadow.
	var void_col: Color = palette["eldritch"]
	var glow: Color = palette["violet"]
	# Faint corruption stain spread on the floor.
	draw_circle(Vector2.ZERO, 24.0, Color(glow.r, glow.g, glow.b, 0.08))
	# Central jagged split lying flat across the ground.
	draw_colored_polygon(PackedVector2Array([
		Vector2(-22.0, 2.0), Vector2(-6.0, -4.0), Vector2(4.0, 3.0),
		Vector2(20.0, -2.0), Vector2(8.0, 6.0), Vector2(-4.0, 9.0)
	]), Color(void_col.r, void_col.g, void_col.b, 0.9))
	# Radiating hairline cracks.
	draw_line(Vector2(-6.0, -4.0), Vector2(-14.0, -12.0), Color(void_col.r, void_col.g, void_col.b, 0.7), 2.0)
	draw_line(Vector2(4.0, 3.0), Vector2(12.0, 12.0), Color(void_col.r, void_col.g, void_col.b, 0.7), 2.0)
	draw_line(Vector2(-4.0, 9.0), Vector2(-2.0, 18.0), Color(void_col.r, void_col.g, void_col.b, 0.6), 1.0)
	# Glowing seam down the center of the split.
	draw_line(Vector2(-18.0, 1.0), Vector2(16.0, 0.0), Color(glow.r, glow.g, glow.b, 0.55), 1.0)


func _draw_vomit_stain() -> void:
	var bile: Color = palette["sulfur"].darkened(0.4)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-12.0, -1.0), Vector2(-3.0, -6.0), Vector2(7.0, -3.0),
		Vector2(13.0, 3.0), Vector2(4.0, 7.0), Vector2(-8.0, 6.0)
	]), Color(bile.r, bile.g, bile.b, 0.4))
	draw_circle(Vector2(1.0, 0.0), 6.0, Color(bile.r, bile.g, bile.b, 0.42))
	draw_circle(Vector2(6.0, 2.0), 3.0, Color(palette["taupe"].r, palette["taupe"].g, palette["taupe"].b, 0.35))
	draw_circle(Vector2(-7.0, 3.0), 2.0, Color(bile.r, bile.g, bile.b, 0.45))
	draw_circle(Vector2(11.0, 4.0), 1.5, Color(bile.r, bile.g, bile.b, 0.4))


func _draw_wanted_posters() -> void:
	var paper: Color = palette["bone"].darkened(0.2)
	draw_colored_polygon(PackedVector2Array([
		Vector2(-13.0, -26.0), Vector2(-1.0, -27.0), Vector2(-2.0, -4.0), Vector2(-12.0, -3.0)
	]), Color(paper.r, paper.g, paper.b, 0.85))
	draw_colored_polygon(PackedVector2Array([
		Vector2(2.0, -23.0), Vector2(13.0, -25.0), Vector2(14.0, -6.0), Vector2(3.0, -5.0)
	]), Color(paper.r, paper.g, paper.b, 0.8))
	draw_circle(Vector2(-7.0, -18.0), 4.0, Color(palette["iron"].r, palette["iron"].g, palette["iron"].b, 0.6))
	draw_rect(Rect2(-11.0, -10.0, 9.0, 1.5), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5), true)
	draw_rect(Rect2(-11.0, -7.0, 7.0, 1.5), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5), true)
	draw_rect(Rect2(4.0, -16.0, 8.0, 1.5), Color(palette["abyss"].r, palette["abyss"].g, palette["abyss"].b, 0.5), true)
	draw_line(Vector2(2.0, -23.0), Vector2(13.0, -10.0), Color(palette["blood"].r, palette["blood"].g, palette["blood"].b, 0.4), 1.0)


func _draw_warning_bell() -> void:
	draw_circle(Vector2(0.0, 4.0), 16.0, Color(0, 0, 0, 0.22))
	var wd: Color = palette["umber"].darkened(0.4)
	# A-frame gallows for the alarm bell
	draw_line(Vector2(-14.0, 6.0), Vector2(0.0, -44.0), wd, 4.0)
	draw_line(Vector2(14.0, 6.0), Vector2(0.0, -44.0), wd, 4.0)
	draw_line(Vector2(-9.0, -22.0), Vector2(9.0, -22.0), wd, 3.0)
	# crossbeam from which the bell hangs
	draw_line(Vector2(-2.0, -44.0), Vector2(0.0, -38.0), palette["iron"], 2.0)
	# tarnished bronze bell
	var g: Color = palette["gold"]
	draw_colored_polygon(PackedVector2Array([Vector2(-9.0, -22.0), Vector2(-7.0, -36.0), Vector2(7.0, -36.0), Vector2(9.0, -22.0)]), g.darkened(0.15))
	draw_colored_polygon(PackedVector2Array([Vector2(-9.0, -22.0), Vector2(-7.0, -36.0), Vector2(0.0, -36.0), Vector2(0.0, -22.0)]), g)
	draw_rect(Rect2(-11.0, -23.0, 22.0, 3.0), g.darkened(0.3), true)
	# clapper
	draw_circle(Vector2(0.0, -19.0), 2.5, palette["iron"])
	draw_line(Vector2(0.0, -22.0), Vector2(0.0, -18.0), palette["iron"], 1.0)
	# verdigris streak on the bronze
	draw_line(Vector2(4.0, -34.0), Vector2(6.0, -24.0), Color(palette["teal"].r, palette["teal"].g, palette["teal"].b, 0.3), 1.5)


func _draw_warning_sign() -> void:
	draw_circle(Vector2(0.0, 4.0), 12.0, Color(0, 0, 0, 0.22))
	var wd: Color = palette["umber"].darkened(0.35)
	# leaning post
	draw_line(Vector2(0.0, 4.0), Vector2(-2.0, -28.0), wd, 5.0)
	# crude warning plank, blood-marked
	draw_colored_polygon(PackedVector2Array([Vector2(-18.0, -30.0), Vector2(16.0, -34.0), Vector2(18.0, -20.0), Vector2(-16.0, -16.0)]), palette["umber"])
	draw_colored_polygon(PackedVector2Array([Vector2(-18.0, -30.0), Vector2(16.0, -34.0), Vector2(16.0, -32.0), Vector2(-18.0, -28.0)]), palette["umber"].lightened(0.15))
	# painted skull / warning glyph in old blood
	var b: Color = palette["blood"]
	draw_line(Vector2(-8.0, -28.0), Vector2(8.0, -24.0), b, 2.5)
	draw_line(Vector2(-8.0, -22.0), Vector2(8.0, -30.0), b, 2.5)
	draw_circle(Vector2(0.0, -26.0), 4.0, Color(b.r, b.g, b.b, 0.35))
	# rusted nails
	draw_circle(Vector2(-15.0, -27.0), 1.2, palette["rust"])
	draw_circle(Vector2(14.0, -31.0), 1.2, palette["rust"])


func _draw_weapon_display() -> void:
	draw_circle(Vector2(0.0, 4.0), 28.0, Color(0, 0, 0, 0.22))
	# Wooden rack base.
	_draw_box(Vector2(50.0, 18.0), 8.0, palette["wood"], palette["wood_dark"])
	# Upright posts + crossbar (negative Y).
	draw_line(Vector2(-22.0, -8.0), Vector2(-22.0, -52.0), palette["wood_dark"], 3.0)
	draw_line(Vector2(22.0, -8.0), Vector2(22.0, -52.0), palette["wood_dark"], 3.0)
	draw_line(Vector2(-24.0, -50.0), Vector2(24.0, -50.0), palette["wood_dark"], 3.0)
	# A rusted sword.
	draw_line(Vector2(-12.0, -50.0), Vector2(-12.0, -16.0), palette["ash"], 3.0)
	draw_line(Vector2(-18.0, -44.0), Vector2(-6.0, -44.0), palette["iron"], 2.0)
	# A pitted axe.
	draw_line(Vector2(8.0, -50.0), Vector2(8.0, -18.0), palette["umber"], 3.0)
	draw_colored_polygon(PackedVector2Array([
		Vector2(8.0, -46.0), Vector2(20.0, -42.0), Vector2(8.0, -34.0)
	]), palette["rust"])


func _draw_weapon_rack() -> void:
	draw_circle(Vector2(0.0, 5.0), 22.0, Color(0, 0, 0, 0.22))
	# Rotting wooden frame: two posts + top rail.
	draw_rect(Rect2(-22.0, -40.0, 5.0, 46.0), palette["umber"], true)
	draw_rect(Rect2(17.0, -40.0, 5.0, 46.0), palette["umber"], true)
	draw_rect(Rect2(-22.0, -40.0, 44.0, 5.0), palette["umber"].lightened(0.06), true)
	# Lower holding rail.
	draw_rect(Rect2(-22.0, -12.0, 44.0, 4.0), palette["umber"].darkened(0.2), true)
	# A rusted sword leaning in the rack.
	draw_line(Vector2(-12.0, -8.0), Vector2(-12.0, -42.0), palette["ash"], 2.0)
	draw_line(Vector2(-16.0, -36.0), Vector2(-8.0, -36.0), palette["iron"], 3.0)
	# A spear/halberd shaft.
	draw_line(Vector2(0.0, -8.0), Vector2(2.0, -48.0), palette["umber"].darkened(0.1), 2.0)
	draw_colored_polygon(PackedVector2Array([
		Vector2(2.0, -48.0), Vector2(-2.0, -42.0), Vector2(6.0, -42.0)
	]), palette["ash"])
	# A notched axe head hung on the rail.
	draw_line(Vector2(12.0, -8.0), Vector2(12.0, -40.0), palette["umber"].darkened(0.15), 2.0)
	draw_rect(Rect2(8.0, -40.0, 10.0, 7.0), palette["iron"], true)
	draw_circle(Vector2(12.0, -36.0), 1.5, Color(palette["rust"].r, palette["rust"].g, palette["rust"].b, 0.6))


## Solid-prop collider footprints (kinds absent here are walkable decor).
const COLLIDERS := {
	"altar": {"size": Vector2(44.0, 22.0)},
	"anvil": {"size": Vector2(30.0, 16.0)},
	"armor_pile": {"radius": 16.0},
	"armor_rack": {"size": Vector2(30.0, 12.0)},
	"armor_stand": {"radius": 12.0},
	"ash_brazier": {"radius": 12.0},
	"bar_counter": {"size": Vector2(78.0, 28.0)},
	"barrels": {"size": Vector2(46.0, 28.0)},
	"blue_brazier": {"radius": 12.0},
	"bone_wall": {"size": Vector2(58.0, 16.0)},
	"bookcase": {"size": Vector2(38.0, 14.0)},
	"broken_arcade": {"size": Vector2(60.0, 14.0)},
	"broken_bench": {"size": Vector2(40.0, 14.0)},
	"broken_cart": {"size": Vector2(40.0, 18.0)},
	"broken_portcullis": {"size": Vector2(62.0, 14.0)},
	"broken_statue": {"size": Vector2(34.0, 22.0)},
	"broken_table": {"size": Vector2(50.0, 20.0)},
	"broken_telescope": {"radius": 11.0},
	"broken_telescope_large": {"size": Vector2(26.0, 16.0)},
	"cauldron": {"radius": 18.0},
	"chain_post": {"radius": 9.0},
	"chest": {"size": Vector2(40.0, 24.0)},
	"cloister_dead_tree": {"radius": 16.0},
	"coal_cart": {"size": Vector2(46.0, 26.0)},
	"coal_pile": {"radius": 16.0},
	"coin_scale_table": {"size": Vector2(46.0, 24.0)},
	"confession_cell": {"size": Vector2(40.0, 26.0)},
	"corpse_cart": {"size": Vector2(52.0, 28.0)},
	"counter": {"size": Vector2(72.0, 26.0)},
	"dead_tree_large": {"radius": 11.0},
	"dead_tree_small": {"radius": 7.0},
	"dry_well": {"radius": 26.0},
	"fireplace": {"size": Vector2(50.0, 30.0)},
	"forbidden_books_crate": {"size": Vector2(30.0, 20.0)},
	"forge": {"size": Vector2(48.0, 34.0)},
	"forge_smoke_stack": {"size": Vector2(30.0, 24.0)},
	"gallows": {"size": Vector2(40.0, 18.0)},
	"glory_shrine": {"size": Vector2(30.0, 18.0)},
	"grave_marker": {"size": Vector2(26.0, 10.0)},
	"hanging_cage": {"size": Vector2(14.0, 8.0)},
	"hanging_lantern_post": {"radius": 7.0},
	"hidden_chest": {"size": Vector2(40.0, 24.0)},
	"kneeling_statue": {"size": Vector2(30.0, 18.0)},
	"knife_table": {"size": Vector2(50.0, 26.0)},
	"lantern_post": {"radius": 7.0},
	"ledger_table": {"size": Vector2(50.0, 28.0)},
	"lockbox_stack": {"size": Vector2(40.0, 26.0)},
	"market_stall": {"size": Vector2(60.0, 22.0)},
	"mausoleum": {"size": Vector2(54.0, 34.0)},
	"notice_board": {"size": Vector2(44.0, 8.0)},
	"obelisk": {"size": Vector2(26.0, 12.0)},
	"pew_left_01": {"size": Vector2(50.0, 14.0)},
	"pew_left_02": {"size": Vector2(50.0, 14.0)},
	"pew_right_01": {"size": Vector2(50.0, 14.0)},
	"pew_right_02": {"size": Vector2(50.0, 14.0)},
	"refugee_tent": {"size": Vector2(46.0, 14.0)},
	"ritual_table": {"size": Vector2(48.0, 22.0)},
	"shelf_potions": {"size": Vector2(40.0, 18.0)},
	"skull_reliquary": {"size": Vector2(24.0, 16.0)},
	"table": {"size": Vector2(54.0, 30.0)},
	"trade_board": {"size": Vector2(40.0, 10.0)},
	"training_dummy": {"radius": 12.0},
	"vault_door": {"size": Vector2(52.0, 18.0)},
	"vendor_counter": {"size": Vector2(64.0, 26.0)},
	"warning_bell": {"size": Vector2(28.0, 12.0)},
	"warning_sign": {"radius": 6.0},
	"weapon_display": {"size": Vector2(50.0, 18.0)},
	"weapon_rack": {"size": Vector2(44.0, 10.0)},
}


## Per-kind ambient FX hint consumed by the builder (shader/particle attachment).
## Values: "sway" | "glow:<paletteKey>" | "particles:leaves|ash|smoke|fire|bubble".
const FX := {
	"altar": "glow:sulfur",
	"ash_brazier": "particles:ash",
	"ash_pile": "particles:ash",
	"blue_brazier": "glow:vblue",
	"broken_telescope_large": "glow:vblue",
	"candle_cluster": "glow:sulfur",
	"catacomb_seal": "glow:magenta",
	"cauldron": "particles:bubble",
	"chain_post": "sway",
	"cloister_dead_tree": "sway",
	"dead_campfire": "particles:ash",
	"dead_tree_large": "sway",
	"dead_tree_small": "sway",
	"fireplace": "glow:sulfur",
	"floating_stone": "glow:violet",
	"floating_stones": "glow:violet",
	"forbidden_books_crate": "glow:magenta",
	"forge": "glow:sulfur",
	"forge_smoke_stack": "particles:smoke",
	"glory_shrine": "glow:teal",
	"hanging_cage": "sway",
	"hanging_cloth": "sway",
	"hanging_lantern_post": "glow:sulfur",
	"hidden_chest": "glow:violet",
	"lantern_post": "glow:sulfur",
	"market_stall": "sway",
	"obelisk": "glow:teal",
	"prayer_strip_wall": "sway",
	"refugee_tent": "sway",
	"ritual_blood_stain": "glow:violet",
	"ritual_circle": "glow:violet",
	"ritual_table": "glow:sulfur",
	"shelf_potions": "glow:teal",
	"skull_reliquary": "glow:teal",
	"tavern_sign": "sway",
	"void_crack": "glow:violet",
	"void_crack_ground": "glow:violet",
	"warning_bell": "sway",
}


static func collider_for(prop_kind: String) -> Dictionary:
	return COLLIDERS.get(prop_kind, {})


static func fx_for(prop_kind: String) -> String:
	return FX.get(prop_kind, "")
