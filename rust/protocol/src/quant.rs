//! Quantization rules, ported exactly (extraction/wire-protocol.md §4.2–4.3).
//!
//! Positions/velocities: ×10, **truncate toward zero**, clamp to i16 (0.1-unit precision).
//! Angles: ×100, same rule (0.01-rad precision).
//! Resources (stamina/mana in ActionConfirm): **round half away from zero**, clamp 0..=255 —
//! the GDScript `roundi` rule, distinct from position truncation.

pub fn quant_coord(v: f32) -> i16 {
    // GDScript: clampi(int(v * 10.0), -32768, 32767) — f32 promoted to f64, int() truncates
    // toward zero. NaN saturates to 0 via Rust's `as` cast, matching GDScript's int(NaN) == 0.
    // Non-finite inputs are pinned (see tests): +inf clamps to 32767, -inf clamps to -32768
    // (`f64::clamp` returns the matching bound for ±inf), NaN ⇒ 0. Both sides agree, so a stray
    // non-finite coordinate can never desync client and server.
    let q = (v as f64 * 10.0).trunc();
    q.clamp(-32768.0, 32767.0) as i16
}

pub fn dequant_coord(q: i16) -> f32 {
    q as f32 / 10.0
}

pub fn quant_angle(rad: f32) -> i16 {
    // Same non-finite policy as quant_coord (pinned by `angle_non_finite_pinned`): NaN ⇒ 0,
    // +inf ⇒ 32767, -inf ⇒ -32768.
    let q = (rad as f64 * 100.0).trunc();
    q.clamp(-32768.0, 32767.0) as i16
}

pub fn dequant_angle(q: i16) -> f32 {
    q as f32 / 100.0
}

/// Stamina/mana on the wire: `clamp(roundi(v), 0, 255)`. Godot `roundi` rounds half away from
/// zero; `f64::round` does the same.
pub fn quant_resource(v: f64) -> u8 {
    v.round().clamp(0.0, 255.0) as u8
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coord_truncates_toward_zero() {
        assert_eq!(quant_coord(-1.26), -12); // not -13
        assert_eq!(quant_coord(1.26), 12);
        assert_eq!(quant_coord(-0.04), 0); // sub-0.05 motion never transmits
        assert_eq!(quant_coord(0.04), 0);
    }

    #[test]
    fn coord_clamps() {
        assert_eq!(quant_coord(40000.0), 32767);
        assert_eq!(quant_coord(-40000.0), -32768);
    }

    #[test]
    fn coord_non_finite_pinned() {
        // NaN ⇒ 0 (Rust `as i16` saturates NaN to 0, matching GDScript int(NaN) == 0).
        assert_eq!(quant_coord(f32::NAN), 0);
        // ±inf clamp to the i16 extremes — pinned so client/server can't diverge on a stray inf.
        assert_eq!(quant_coord(f32::INFINITY), 32767);
        assert_eq!(quant_coord(f32::NEG_INFINITY), -32768);
    }

    #[test]
    fn angle_non_finite_pinned() {
        assert_eq!(quant_angle(f32::NAN), 0);
        assert_eq!(quant_angle(f32::INFINITY), 32767);
        assert_eq!(quant_angle(f32::NEG_INFINITY), -32768);
    }

    #[test]
    fn resource_non_finite_pinned() {
        // NaN ⇒ 0; +inf clamps to 255; -inf clamps to 0.
        assert_eq!(quant_resource(f64::NAN), 0);
        assert_eq!(quant_resource(f64::INFINITY), 255);
        assert_eq!(quant_resource(f64::NEG_INFINITY), 0);
    }

    #[test]
    fn resource_rounds_half_away() {
        assert_eq!(quant_resource(0.5), 1);
        assert_eq!(quant_resource(99.5), 100);
        assert_eq!(quant_resource(-1.0), 0);
        assert_eq!(quant_resource(300.0), 255);
    }

    #[test]
    fn round_trip_error_bounded() {
        for i in -10000..10000 {
            let v = i as f32 * 0.173;
            if v.abs() > 3000.0 {
                continue;
            }
            let rt = dequant_coord(quant_coord(v));
            // Truncation error is < 0.1 in exact math; f32 representation adds ~1e-5 on top.
            assert!((rt - v).abs() < 0.1001, "v={v} rt={rt}");
        }
    }
}
