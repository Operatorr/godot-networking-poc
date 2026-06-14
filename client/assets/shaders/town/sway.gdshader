// Sanctuary town — base-anchored wind sway for foliage, cloth, hanging signs.
//
// Canvas-item VERTEX shader. The prop is drawn with its ground-contact at local
// y = 0 and its body built UPWARD into negative y (see SanctuaryTownWorld._Prop).
// Sway weight scales with height above the base so the trunk/anchor stays pinned
// while the canopy/cloth top bends. Each instance gets its own ShaderMaterial with
// a random `phase` so nothing sways in unison (set_shader_parameter is per-material).
shader_type canvas_item;

uniform float sway_strength = 3.0;   // max horizontal px at the crown
uniform float sway_speed    = 1.2;
uniform float phase         = 0.0;   // per-instance offset (radians)
uniform float anchor_height = 48.0;  // px from base to the swaying crown
// false: base-anchored (trees) — pinned at y>=0, sways at the crown (y = -anchor_height).
// true:  top-anchored (hung cloth/signs/strips) — pinned at the top, sways at the free hem (y≈0).
uniform bool  top_anchored = false;

void vertex() {
	float w = top_anchored
		? clamp(1.0 + VERTEX.y / anchor_height, 0.0, 1.0)   // 1 at the hem (y≈0), 0 at the rail
		: clamp(-VERTEX.y / anchor_height, 0.0, 1.0);        // 0 at the base, 1 at the crown
	float t = TIME * sway_speed + phase;
	// a slow primary gust plus a small high-frequency flutter
	float gust = sin(t + VERTEX.y * 0.04);
	float flutter = 0.25 * sin(t * 3.1 + VERTEX.y * 0.13);
	VERTEX.x += (gust + flutter) * sway_strength * w;
}
