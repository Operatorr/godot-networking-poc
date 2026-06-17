// Warrior Charge — GPU particle process shader for the energy trail streamed
// behind the warrior while charging. Cosmetic only (no gameplay), mirrors the
// charge-loop SFX edge in prediction.gd via ChargeTrail (charge_trail.gd).
//
// The emitter (a GPUParticles2D parented to the player, local_coords = false)
// spits glowing embers that are LEFT BEHIND in world space as the warrior
// dashes — the fast charge motion does most of the trailing, and `flow_dir`
// (the live charge direction, pushed in each frame) sweeps the embers back for
// a stronger comet look. Particles fade hot-white -> orange -> dark and shrink
// over their life. Rendered additive (blend_add) by ChargeTrail for glow.
shader_type particles;

uniform vec4 color_hot : source_color = vec4(1.0, 0.95, 0.70, 1.0);  // white-hot core
uniform vec4 color_mid : source_color = vec4(1.0, 0.55, 0.15, 1.0);  // warrior orange
uniform vec4 color_cool : source_color = vec4(0.55, 0.12, 0.04, 0.0); // dark ember, fades out
uniform vec2 flow_dir = vec2(0.0, 0.0);   // unit charge direction (set each frame); embers sweep -flow_dir
uniform float trail_speed = 70.0;         // backward sweep speed along -flow_dir
uniform float spawn_radius = 13.0;        // disc the embers spawn within, around the warrior
uniform float spread_speed = 28.0;        // small outward bloom
uniform float base_size = 1.0;            // quad scale at birth (xN of the dot texture)
uniform float drag_rate = 2.6;            // velocity damping per second

// Cheap per-particle hash from the unique particle NUMBER -> [0,1).
float hash11(uint n) {
	n = (n << 13u) ^ n;
	n = n * (n * n * 15731u + 789221u) + 1376312589u;
	return float(n & 0x7fffffffu) / float(0x7fffffff);
}

void start() {
	// On restart the engine has already placed TRANSFORM at the emitter
	// (EMISSION_TRANSFORM); only ADD a local offset so the base position is
	// never double-applied. w = 0 -> rotate the direction by the emitter basis.
	float a = hash11(NUMBER) * 6.2831853;
	float r = hash11(NUMBER * 747796405u + 2891336453u);
	vec3 radial = (EMISSION_TRANSFORM * vec4(cos(a), sin(a), 0.0, 0.0)).xyz;
	TRANSFORM[3].xyz += radial * spawn_radius * r;

	vec3 sweep = vec3(-flow_dir, 0.0) * trail_speed * (0.6 + 0.4 * r);
	VELOCITY = sweep + radial * spread_speed * r;

	COLOR = color_hot;
	CUSTOM = vec4(0.0);  // CUSTOM.x = normalized age
}

void process() {
	float life = max(LIFETIME, 0.0001);
	CUSTOM.x += DELTA / life;
	float t = clamp(CUSTOM.x, 0.0, 1.0);

	// hot-white -> orange -> dark, alpha fading to 0 at end of life.
	vec4 c = (t < 0.5) ? mix(color_hot, color_mid, t * 2.0)
	                   : mix(color_mid, color_cool, (t - 0.5) * 2.0);
	c.a *= (1.0 - t);
	COLOR = c;

	// Exponential-ish drag (framerate independent).
	VELOCITY -= VELOCITY * clamp(drag_rate * DELTA, 0.0, 1.0);

	// Uniform shrink over life; preserve position, drop emitter rotation (round dots).
	float s = base_size * mix(1.0, 0.2, t);
	vec3 pos = TRANSFORM[3].xyz;
	TRANSFORM[0] = vec4(s, 0.0, 0.0, 0.0);
	TRANSFORM[1] = vec4(0.0, s, 0.0, 0.0);
	TRANSFORM[2] = vec4(0.0, 0.0, 1.0, 0.0);
	TRANSFORM[3] = vec4(pos, 1.0);
}
