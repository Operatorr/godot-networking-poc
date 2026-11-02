shader_type canvas_item;

// Geometry/alpha still come from the connected wall atlas. Generated raster
// materials supply the stone detail without changing collision or Y sorting.
uniform sampler2D masonry : source_color, filter_nearest, repeat_disable;
uniform bool carved_faces = true;
varying vec2 world_pos;
varying vec4 tint;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 0.0, 1.0)).xy;
	tint = COLOR;
}

vec3 swatch(vec2 quadrant, vec2 uv) {
	// Inset sampling keeps the neighboring material out of quadrant edges.
	vec2 texel = 1.0 / vec2(textureSize(masonry, 0));
	return texture(masonry, quadrant * 0.5 + mix(texel, vec2(0.5) - texel, uv)).rgb;
}

void fragment() {
	vec4 silhouette = texture(TEXTURE, UV);
	// Use the tile's own texture: Godot pads/repackages atlas cells at runtime,
	// so UV cannot address a second unpadded atlas with matching coordinates.
	vec3 surface = silhouette.rgb;
	vec3 stone;
	// Match the surrounding material atlas's roughly half-unit art pixel.
	vec2 stone_pos = floor(world_pos * 2.0) * 0.5;
	if (surface.r > 0.75) {
		// Map caps in ground space, continuously through straight/corner/T tiles.
		vec2 cap_uv = fract((stone_pos + vec2(8.0, 24.0)) / vec2(96.0, 64.0));
		stone = swatch(vec2(0.0), cap_uv);
		stone *= 1.10 + surface.g * 0.55 - surface.b * 0.70;
	} else {
		float depth = clamp(surface.r * 2.0, 0.0, 1.0);
		bool east = surface.b > surface.g;
		float along = east ? stone_pos.y - depth * 24.0 : stone_pos.x - depth * 8.0;
		// Blind pointed arches form the lower face; heavy coping reads above.
		stone = swatch(carved_faces ? vec2(0.0, 1.0) : vec2(1.0, 0.0), vec2(fract(along / 96.0), depth));
		stone *= east ? 0.70 : 0.92;
	}
	COLOR = vec4(stone, silhouette.a) * tint;
}
