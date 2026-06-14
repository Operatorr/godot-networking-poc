// Sanctuary town — additive pulsing glow for braziers, candles, shrines, void
// cracks, portal aura and the cursed fountain.
//
// Applied to a CanvasItem that draws translucent halo primitives (no texture).
// blend_add brightens whatever is behind it; the fragment pass just breathes the
// alpha so a static halo becomes a living flicker. Per-instance `phase` keeps each
// light source out of sync. Light must feel earned (spec §14) — keep pulse subtle.
shader_type canvas_item;
render_mode blend_add;

uniform float pulse_speed = 2.4;
uniform float pulse_min   = 0.45;   // 0..1 intensity floor (never fully dark)
uniform float pulse_max   = 1.0;
uniform float phase       = 0.0;    // per-instance offset (radians)
uniform float flicker     = 0.12;   // small chaotic firelight jitter (0 = steady)

void fragment() {
	float base = 0.5 + 0.5 * sin(TIME * pulse_speed + phase);
	// layered higher-frequency wobble for candle/fire chaos
	float jit = flicker * sin(TIME * 11.0 + phase * 3.0) * sin(TIME * 6.3 + phase);
	float pulse = clamp(mix(pulse_min, pulse_max, base) + jit, 0.0, 1.0);
	COLOR.a *= pulse;
}
