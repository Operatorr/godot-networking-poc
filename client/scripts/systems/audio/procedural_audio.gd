## ProceduralAudio - Generates all game sounds from mathematical waveforms
## Aesthetic: Industrial horror, metallic impacts, wet organic textures, dark techno
## All sounds generated at runtime using AudioStreamWAV
class_name ProceduralAudio
extends RefCounted

const SAMPLE_RATE := 22050
const MIX_RATE := 22050

## Generate all game audio and return as dictionary of AudioStreamWAV
static func generate_all_sounds() -> Dictionary:
	var sounds := {}

	# UI sounds
	sounds["button_hover"] = _gen_button_hover()
	sounds["button_click"] = _gen_button_click()

	# Player combat sounds
	sounds["player_shoot"] = _gen_player_shoot()
	sounds["player_hit"] = _gen_player_hit()
	sounds["player_death"] = _gen_player_death()
	sounds["player_kill"] = _gen_player_kill()
	sounds["level_up"] = _gen_level_up()

	# Monster sounds
	sounds["monster_shoot"] = _gen_monster_shoot()
	sounds["monster_hit"] = _gen_monster_hit()
	sounds["monster_death"] = _gen_monster_death()
	sounds["monster_spawn"] = _gen_monster_spawn()

	# Combat sounds
	sounds["projectile_impact"] = _gen_projectile_impact()
	sounds["mageblast"] = _gen_mageblast()

	# Movement sounds
	sounds["footstep_l"] = _gen_footstep(0)
	sounds["footstep_r"] = _gen_footstep(1)

	return sounds


## Generate looping music tracks
static func generate_music() -> Dictionary:
	var music := {}
	music["menu_bgm"] = _gen_menu_bgm()
	music["arena_ambience"] = _gen_arena_ambience()
	return music


# ─── HELPER: Create AudioStreamWAV from float samples ───

static func _samples_to_wav(
	samples: PackedFloat32Array,
	loop_mode: AudioStreamWAV.LoopMode = AudioStreamWAV.LOOP_DISABLED
) -> AudioStreamWAV:
	var wav := AudioStreamWAV.new()
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.mix_rate = MIX_RATE
	wav.stereo = false
	wav.loop_mode = loop_mode

	# Convert float samples to 16-bit PCM
	var pcm := PackedByteArray()
	pcm.resize(samples.size() * 2)
	for i in range(samples.size()):
		var val := clampf(samples[i], -1.0, 1.0)
		var s16 := int(val * 32767.0)
		pcm[i * 2] = s16 & 0xFF
		pcm[i * 2 + 1] = (s16 >> 8) & 0xFF

	wav.data = pcm
	if loop_mode != AudioStreamWAV.LOOP_DISABLED:
		wav.loop_begin = 0
		wav.loop_end = samples.size()
	return wav


# ─── WAVEFORM GENERATORS ───

static func _sine(phase: float) -> float:
	return sin(phase * TAU)

static func _square(phase: float) -> float:
	return 1.0 if fmod(phase, 1.0) < 0.5 else -1.0

static func _saw(phase: float) -> float:
	return 2.0 * fmod(phase, 1.0) - 1.0

static func _noise() -> float:
	return randf_range(-1.0, 1.0)

static func _noise_filtered(prev: float, amount: float) -> float:
	return prev * (1.0 - amount) + _noise() * amount


# ─── ENVELOPE ───

static func _envelope(t: float, attack: float, decay: float, sustain: float, release: float, total: float) -> float:
	if t < attack:
		return t / attack
	t -= attack
	if t < decay:
		return 1.0 - (1.0 - sustain) * (t / decay)
	t -= decay
	var sustain_time := total - attack - decay - release
	if t < sustain_time:
		return sustain
	t -= sustain_time
	if t < release:
		return sustain * (1.0 - t / release)
	return 0.0


# ─── UI SOUNDS ───

static func _gen_button_hover() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.015)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := 1.0 - (t / 0.015)
		samples[i] = _sine(t * 2800.0) * env * 0.3 + _noise() * env * 0.05
	return _samples_to_wav(samples)


static func _gen_button_click() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.035)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 120.0)
		# Pneumatic hiss + metallic impact
		var hiss := _noise() * env * 0.3
		var impact := _sine(t * 600.0) * env * 0.5
		samples[i] = hiss + impact
	return _samples_to_wav(samples)


# ─── PLAYER SOUNDS ───

static func _gen_player_shoot() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.07)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 40.0)
		# Descending distorted synth stab
		var freq := lerpf(900.0, 200.0, t / 0.07)
		var synth := _square(t * freq) * 0.3
		# Metallic clang overtone
		var clang := _sine(t * 1800.0) * exp(-t * 80.0) * 0.2
		# Noise burst
		var burst := _noise() * exp(-t * 60.0) * 0.15
		samples[i] = (synth + clang + burst) * env
	return _samples_to_wav(samples)


static func _gen_player_hit() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.06)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var prev_noise := 0.0
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 50.0)
		# Low thud
		var thud := _sine(t * 120.0) * env * 0.5
		# Wet crunch (filtered noise)
		prev_noise = _noise_filtered(prev_noise, 0.4)
		var crunch := prev_noise * env * 0.3
		# Sub impact
		var sub := _sine(t * 50.0) * exp(-t * 30.0) * 0.3
		samples[i] = thud + crunch + sub
	return _samples_to_wav(samples)


static func _gen_player_death() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.35)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var prev_noise := 0.0
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 6.0)
		# Descending industrial groan
		var freq := lerpf(300.0, 40.0, t / 0.35)
		var groan := _saw(t * freq) * 0.3
		# Splatter noise
		prev_noise = _noise_filtered(prev_noise, 0.3)
		var splatter := prev_noise * exp(-t * 8.0) * 0.25
		# Dissonant overtone
		var dissonant := _sine(t * freq * 1.414) * 0.15 * env
		# Sub rumble
		var rumble := _sine(t * 30.0) * env * 0.2
		samples[i] = (groan + splatter + dissonant + rumble) * env
	return _samples_to_wav(samples)


static func _gen_player_kill() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.18)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := _envelope(t, 0.005, 0.05, 0.4, 0.1, 0.18)
		# Dissonant ascending tone - "wrong triumph"
		var freq1 := lerpf(400.0, 900.0, t / 0.18)
		var freq2 := freq1 * 1.26  # Minor sixth - unsettling
		var tone1 := _sine(t * freq1) * 0.3
		var tone2 := _sine(t * freq2) * 0.2
		# Metallic ring
		var ring := _sine(t * 3200.0) * exp(-t * 30.0) * 0.1
		samples[i] = (tone1 + tone2 + ring) * env
	return _samples_to_wav(samples)


## Triumphant ascending C-major arpeggio (C-E-G-C) with a bell timbre — the level-up "ding".
static func _gen_level_up() -> AudioStreamWAV:
	var notes := [523.25, 659.25, 783.99, 1046.50]  # C5, E5, G5, C6
	var note_step := 0.10
	var total := 0.70
	var num_samples := int(SAMPLE_RATE * total)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var sample := 0.0
		# Each note enters in turn and rings out to the end, building a bright chord.
		for n in range(notes.size()):
			var start := n * note_step
			if t < start:
				continue
			var nt := t - start
			var env := _envelope(nt, 0.004, 0.10, 0.45, 0.4, total - start)
			var f: float = notes[n]
			sample += (_sine(t * f) * 0.6 + _sine(t * f * 2.0) * 0.18) * env * 0.32
		# Sparkle shimmer over the top after the chord forms.
		if t > 2.0 * note_step:
			var shimmer := _envelope(t - 2.0 * note_step, 0.01, 0.12, 0.35, 0.4, total - 2.0 * note_step)
			sample += _sine(t * 2093.0) * shimmer * 0.07
		samples[i] = clampf(sample, -1.0, 1.0)
	return _samples_to_wav(samples)


# ─── MONSTER SOUNDS ───

static func _gen_monster_shoot() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.06)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 40.0)
		# Lower, more guttural
		var freq := lerpf(500.0, 100.0, t / 0.06)
		var guttural := _saw(t * freq) * 0.35
		var sub := _sine(t * 80.0) * env * 0.25
		var burst := _noise() * exp(-t * 70.0) * 0.15
		samples[i] = (guttural + sub + burst) * env
	return _samples_to_wav(samples)


static func _gen_monster_hit() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.05)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var prev_noise := 0.0
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 55.0)
		# Meaty squelch
		prev_noise = _noise_filtered(prev_noise, 0.35)
		var squelch := prev_noise * 0.35
		var meat := _sine(t * 180.0) * 0.3
		var sub := _sine(t * 60.0) * 0.2
		samples[i] = (squelch + meat + sub) * env
	return _samples_to_wav(samples)


static func _gen_monster_death() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.25)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var prev_noise := 0.0
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 7.0)
		# Tearing/ripping
		prev_noise = _noise_filtered(prev_noise, 0.5)
		var tear := prev_noise * 0.3
		# Gurgling descent
		var freq := lerpf(250.0, 30.0, t / 0.25)
		var gurgle := _sine(t * freq) * 0.25
		# Wobble modulation
		var wobble := sin(t * 25.0) * 0.3
		gurgle *= (1.0 + wobble)
		# Organic pop
		var pop := _sine(t * 400.0) * exp(-t * 50.0) * 0.15
		samples[i] = (tear + gurgle + pop) * env
	return _samples_to_wav(samples)


static func _gen_monster_spawn() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.15)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		# Reversed envelope: builds up then snaps
		var env: float
		if t < 0.12:
			env = pow(t / 0.12, 2.0)
		else:
			env = exp(-(t - 0.12) * 60.0)
		# Ascending noise sweep (reversed whisper feel)
		var freq := lerpf(100.0, 2000.0, t / 0.15)
		var sweep := _sine(t * freq) * 0.2
		# Dimensional pop at end
		var pop := _sine(t * 800.0) * exp(-maxf(0.0, t - 0.11) * 100.0) * 0.3
		# Noise texture
		var tex := _noise() * env * 0.15
		samples[i] = (sweep + pop + tex) * env
	return _samples_to_wav(samples)


# ─── COMBAT SOUNDS ───

static func _gen_projectile_impact() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.03)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 100.0)
		# Sharp crack
		var crack := _noise() * env * 0.4
		# Wet pop
		var pop := _sine(t * 350.0) * env * 0.3
		samples[i] = crack + pop
	return _samples_to_wav(samples)


## Mage RMB Mageblast — an arcane AOE detonation: a low impact boom under a bright crackling
## shimmer, with a downward magical whoosh. ~0.28 s.
static func _gen_mageblast() -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.28)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var shimmer := 0.0
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		# Sharp attack, long-ish exponential tail.
		var env := exp(-t * 11.0)
		# Low detonation boom: a sine sweeping from ~140 Hz down to ~60 Hz.
		var boom_freq := 140.0 - 80.0 * clampf(t / 0.28, 0.0, 1.0)
		var boom := _sine(t * boom_freq) * 0.55
		# Bright arcane shimmer: detuned high sines, fast-decaying.
		var shimmer_env := exp(-t * 26.0)
		var shimmer_tone := (_sine(t * 880.0) + _sine(t * 1320.0) * 0.6) * 0.22 * shimmer_env
		# Crackling magic: filtered noise sparkle riding the shimmer.
		shimmer = _noise_filtered(shimmer, 0.35)
		var crackle := shimmer * 0.30 * shimmer_env
		# Downward whoosh tail (descending saw) for the dissipating energy.
		var whoosh := _saw(t * (320.0 - 220.0 * clampf(t / 0.28, 0.0, 1.0))) * 0.12 * env
		samples[i] = (boom * env) + shimmer_tone + crackle + whoosh
	return _samples_to_wav(samples)


# ─── MOVEMENT SOUNDS ───

static func _gen_footstep(variant: int) -> AudioStreamWAV:
	var num_samples := int(SAMPLE_RATE * 0.02)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var prev_noise := 0.0
	var base_freq := 100.0 + variant * 20.0  # Slight pitch variation
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var env := exp(-t * 150.0)
		# Soft organic squelch
		prev_noise = _noise_filtered(prev_noise, 0.3)
		var squelch := prev_noise * env * 0.2
		var tap := _sine(t * base_freq) * env * 0.15
		samples[i] = squelch + tap
	return _samples_to_wav(samples)


# ─── MUSIC ───

static func _gen_menu_bgm() -> AudioStreamWAV:
	# 4-second droning loop: low-frequency hum, breathing atmosphere
	var duration := 4.0
	var num_samples := int(SAMPLE_RATE * duration)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		# Base drone - low sine layers
		var drone1 := _sine(t * 45.0) * 0.15
		var drone2 := _sine(t * 67.5) * 0.1  # Perfect fifth below
		var drone3 := _sine(t * 33.75) * 0.08  # Sub octave

		# Breathing modulation (slow LFO)
		var breath := (1.0 + sin(t * 0.5 * TAU) * 0.3)

		# Subtle dissonant shimmer
		var shimmer := _sine(t * 180.0) * sin(t * 0.25 * TAU) * 0.03

		# Very faint noise texture
		var texture := _noise() * 0.01

		# Reversed feel: occasional swell
		var swell := maxf(0.0, sin(t * 0.8 * TAU)) * 0.03
		var swell_tone := _sine(t * 200.0) * swell

		samples[i] = (drone1 + drone2 + drone3) * breath + shimmer + texture + swell_tone

	return _samples_to_wav(samples, AudioStreamWAV.LOOP_FORWARD)


static func _gen_arena_ambience() -> AudioStreamWAV:
	# 8-second dark techno loop: driving kick + industrial drone
	var duration := 8.0
	var num_samples := int(SAMPLE_RATE * duration)
	var samples := PackedFloat32Array()
	samples.resize(num_samples)
	var bpm := 120.0
	var beat_len := 60.0 / bpm  # 0.5 seconds per beat
	var prev_noise := 0.0

	for i in range(num_samples):
		var t := float(i) / SAMPLE_RATE
		var beat_pos := fmod(t, beat_len)
		var bar_pos := fmod(t, beat_len * 4.0)

		# ── Kick drum: every beat ──
		var kick_env := exp(-beat_pos * 25.0)
		var kick_freq := lerpf(150.0, 40.0, minf(beat_pos * 8.0, 1.0))
		var kick := _sine(beat_pos * kick_freq) * kick_env * 0.35

		# ── Hi-hat: off-beats (every half-beat offset) ──
		var half_beat := fmod(t + beat_len * 0.5, beat_len)
		var hat_env := exp(-half_beat * 80.0)
		prev_noise = _noise_filtered(prev_noise, 0.6)
		var hat := prev_noise * hat_env * 0.08

		# ── Bass drone: sub oscillation ──
		var bass := _sine(t * 55.0) * 0.1

		# ── Industrial texture: metallic resonance ──
		var metal := _sine(t * 440.0) * _sine(t * 3.0) * 0.02

		# ── Atmospheric whisper layer ──
		var whisper := _noise() * 0.015 * (0.5 + 0.5 * sin(t * 0.3 * TAU))

		# ── Accent: heavier hit on beat 1 of each bar ──
		var bar_beat := fmod(bar_pos, beat_len)
		var accent := 0.0
		if bar_pos < beat_len:  # First beat of bar
			accent = _sine(bar_beat * 200.0) * exp(-bar_beat * 30.0) * 0.1

		samples[i] = kick + hat + bass + metal + whisper + accent

	return _samples_to_wav(samples, AudioStreamWAV.LOOP_FORWARD)
