# Feedback recipes — depth for `game-feel`

> Modified for Omega Realm: replaced global hit-stop and client impulses with visual-only feedback. Example intensities are starting points, not required presets. Keep one property owner, restore baseline values on pool return, and preserve readable projectile timing.

Detail the `game-feel` body defers here: the shake math, easing cheat sheet, the rest of the
feedback menu (knockback, flash, number pop, freeze), importance-tier presets, and the
per-engine bindings for tweens and particles. All snippets target **Godot 4.7** and **Unity 6.3 LTS**.

## 1. The trauma model (why shake feels good)

Track a single `trauma` value in `[0, 1]`. Events **add** trauma; it **decays** linearly each
frame. The actual shake amount is `trauma^2` (or `trauma^3`) so:

- small/frequent events barely nudge the screen (low trauma, squared → tiny),
- big events punch hard (high trauma, squared → near full),
- shake **always ends** on its own because trauma decays to 0.

Offset and rotation are `max_* * shake * noise(t)`. Sample a noise function or summed sines
across time — never a fresh `rand()` per frame, which produces a harsh buzz instead of a shake.

```gdscript
# 1D value-noise-ish sampler without an addon: layered sines at incommensurate rates.
func _shake_axis(seed: float, t: float) -> float:
    return 0.6 * sin(t * 11.0 + seed) + 0.4 * sin(t * 23.0 + seed * 2.0)
```

Tunable starting points: `max_offset = (8..16, 6..10) px`, `max_roll = 0.05..0.12 rad`,
`decay = 1.0..1.5` trauma/sec, per-hit trauma `0.15` (light) → `0.8` (heavy).

## 2. Easing cheat sheet — which curve for which job

| Goal | Ease | Godot `Tween` | Notes |
|------|------|---------------|-------|
| UI/element "pop" in | overshoot | `TRANS_BACK`, `EASE_OUT` | shoots past target, settles back |
| Bouncy, lively land | bounce/elastic | `TRANS_ELASTIC`/`TRANS_BOUNCE`, `EASE_OUT` | use sparingly; reads as cartoonish |
| Settle / decelerate | ease-out | `TRANS_CUBIC`/`TRANS_QUAD`, `EASE_OUT` | the default for "comes to rest" |
| Anticipation / wind-up | ease-in | `TRANS_CUBIC`, `EASE_IN` | slow start before a fast action |
| Smooth A→B both ends | ease-in-out | `TRANS_SINE`, `EASE_IN_OUT` | camera moves, menu slides |

Unity 6.3 LTS has no built-in tween library; options in order of preference: `Vector3.SmoothDamp`
for spring-like follow, `Mathf.SmoothStep`/hand-rolled ease in a coroutine, Animator curves,
or a third-party tween package if the project already uses one. Keep the *curve choice* the
same regardless of tool.

```csharp
// Unity 6.3 LTS: an eased scale "pop" in a coroutine (no external deps).
static float EaseOutBack(float k) {                     // 0 -> 1, peaks ~10% past 1
    const float c1 = 1.70158f, c3 = c1 + 1f;
    float m = k - 1f;
    return 1f + c3 * m * m * m + c1 * m * m;
}

IEnumerator Pop(Transform t, float dur = 0.18f) {
    var squash = new Vector3(1.3f, 0.7f, 1f);            // squash on the event
    for (float e = 0f; e < dur; e += Time.deltaTime) {
        // Unclamped, so the overshoot past Vector3.one survives the lerp.
        t.localScale = Vector3.LerpUnclamped(squash, Vector3.one, EaseOutBack(e / dur));
        yield return null;
    }
    t.localScale = Vector3.one;
}
```

## 3. The rest of the feedback menu

- **Flash:** briefly tint a visual sprite/material, then restore its original value. Express
  duration in seconds and cap aggregate intensity; repeated hits must remain readable.
- **Knockback:** gameplay displacement belongs to the server/shared simulation. A cosmetic
  recoil may offset a visual child only; it must not move the body, collider, or aim origin.
- **Number/text pop:** spawn a damage number that rises, fades, and eases out; randomize the
  horizontal drift so stacked hits fan out.
- **Particles:** a short burst at the contact point (sparks, dust, debris). Pool them
  (`performance-optimization`) — do not instance-and-free per hit.
- **Visual hold:** briefly hold an owned sprite animation only when it preserves readable
  attack timing. Keep input, networking, prediction, and interpolation running. Cancel/reset
  the hold on reuse or teardown; online feedback never changes global time scale or pauses the tree.
- **Anticipation & follow-through:** a tiny wind-up before a big action and a settle after read
  as weight; this is animation, not code (engine animation skill).
- **Chromatic/vignette/zoom punch:** post-process nudges for big moments; keep brief.

## 4. Importance tiers (keep the whole game proportional)

Define three presets and assign every juicy event to one. This is what stops a game from
feeling either dead (under-juiced) or exhausting (everything maxed).

| Tier | Trauma | Optional visual hold | Particles | Extra | Example events |
|------|:------:|:--------:|:---------:|-------|----------------|
| small | 0.10–0.20 | none | 0–4 | tick SFX | footstep, UI hover, coin |
| medium | 0.30–0.50 | 0.04–0.06 s | 6–12 | flash | normal hit, jump-land, pickup |
| large | 0.70–1.00 | 0.10–0.15 s | 20–40 | flash + zoom + number | crit, boss hit, death, explosion |

## 5. Accessibility (ship these toggles)

- **Reduce screen shake** (scale trauma output by a 0–100% setting, default ~60–80%).
- **Reduce/disable flashing** (photosensitivity) — replace white flashes with a static tint.
  Even with flashing on, keep any large-area flash at or under three flashes in any one-second
  window ([WCAG 2.3.1](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html)
  general flash threshold; [Xbox Accessibility Guideline 118](https://learn.microsoft.com/en-us/xbox/accessibility/xbox-accessibility-guidelines/118),
  Photosensitivity).
- **Reduce camera motion** — cut shake roll and zoom punches.

These pair with `game-ui-ux` (settings menu) and `input-systems` (accessibility section).

## 6. Per-engine binding summary

- **Godot 4.7:** `create_tween()` + `tween_property().set_trans().set_ease()`;
  one-shot particles; cancellable visual animation holds; shake on a camera offset composed
  by the existing camera owner. Restore baseline properties when an effect ends.
- **Unity 6.3 LTS:** coroutines + `SmoothDamp`/curves (or a tween package); `ParticleSystem.Play()`;
  visual-only holds for networked play; shake via `CinemachineBasicMultiChannelPerlin`
  amplitude/frequency driven by `trauma^2`, or `CinemachineImpulseSource.GenerateImpulse()` for
  one-off hits (see `camera-systems`).
- **Web (Phaser/Pixi/three):** tween via the engine/library tween; `this.cameras.main.shake()`
  in Phaser; `requestAnimationFrame`-driven eases elsewhere.
