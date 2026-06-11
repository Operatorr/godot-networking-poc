//! f32 2-vector mirroring Godot's single-precision `Vector2` semantics.

use std::ops::{Add, AddAssign, Div, Mul, MulAssign, Neg, Sub, SubAssign};

pub const CMP_EPSILON: f64 = 0.00001;

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub const ZERO: Vec2 = Vec2 { x: 0.0, y: 0.0 };

    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }

    /// Godot `Vector2.from_angle`: `(cos a, sin a)`. The engine narrows the angle to
    /// real_t = f32 FIRST and runs cosf/sinf; mirror that, not f64-then-narrow.
    pub fn from_angle(rad: f64) -> Self {
        let r = rad as f32;
        Self {
            x: r.cos(),
            y: r.sin(),
        }
    }

    pub fn length_squared(self) -> f32 {
        self.x * self.x + self.y * self.y
    }

    pub fn length(self) -> f32 {
        self.length_squared().sqrt()
    }

    /// Godot semantics: the engine gates on `x*x + y*y != 0` BEFORE the sqrt, and a vector
    /// whose squared length underflows to 0 with nonzero components is returned UNCHANGED
    /// (so the zero vector normalizes to ZERO, and denormal inputs pass through — never NaN).
    pub fn normalized(self) -> Self {
        let l_sq = self.length_squared();
        if l_sq == 0.0 {
            self
        } else {
            let l = l_sq.sqrt();
            Vec2::new(self.x / l, self.y / l)
        }
    }

    pub fn dot(self, o: Vec2) -> f32 {
        self.x * o.x + self.y * o.y
    }

    pub fn distance_to(self, o: Vec2) -> f32 {
        (o - self).length()
    }

    pub fn distance_squared_to(self, o: Vec2) -> f32 {
        (o - self).length_squared()
    }

    /// Godot `Vector2.angle_to_point(p)` = `atan2(p.y - y, p.x - x)` computed by the engine
    /// in real_t = f32 (atan2f), then widened to f64 for the GDScript caller.
    pub fn angle_to_point(self, p: Vec2) -> f64 {
        (p.y - self.y).atan2(p.x - self.x) as f64
    }

    /// Godot `Vector2.is_equal_approx`: per-component scalar approx compare in f32 with
    /// CMP_EPSILON = 1e-5 (tolerance scales with |a| only — asymmetric).
    pub fn is_equal_approx(self, o: Vec2) -> bool {
        is_equal_approx_f32(self.x, o.x) && is_equal_approx_f32(self.y, o.y)
    }

    pub fn is_finite(self) -> bool {
        self.x.is_finite() && self.y.is_finite()
    }
}

/// Godot `Math::is_equal_approx` for real_t = float.
pub fn is_equal_approx_f32(a: f32, b: f32) -> bool {
    if a == b {
        return true;
    }
    let mut tol = CMP_EPSILON as f32 * a.abs();
    if tol < CMP_EPSILON as f32 {
        tol = CMP_EPSILON as f32;
    }
    (a - b).abs() < tol
}

/// GDScript `is_equal_approx` on 64-bit floats (used for the stamina/mana signal gates).
pub fn is_equal_approx_f64(a: f64, b: f64) -> bool {
    if a == b {
        return true;
    }
    let mut tol = CMP_EPSILON * a.abs();
    if tol < CMP_EPSILON {
        tol = CMP_EPSILON;
    }
    (a - b).abs() < tol
}

impl Add for Vec2 {
    type Output = Vec2;
    fn add(self, o: Vec2) -> Vec2 {
        Vec2::new(self.x + o.x, self.y + o.y)
    }
}

impl AddAssign for Vec2 {
    fn add_assign(&mut self, o: Vec2) {
        *self = *self + o;
    }
}

impl Sub for Vec2 {
    type Output = Vec2;
    fn sub(self, o: Vec2) -> Vec2 {
        Vec2::new(self.x - o.x, self.y - o.y)
    }
}

impl SubAssign for Vec2 {
    fn sub_assign(&mut self, o: Vec2) {
        *self = *self - o;
    }
}

impl Mul<f32> for Vec2 {
    type Output = Vec2;
    fn mul(self, s: f32) -> Vec2 {
        Vec2::new(self.x * s, self.y * s)
    }
}

impl MulAssign<f32> for Vec2 {
    fn mul_assign(&mut self, s: f32) {
        *self = *self * s;
    }
}

/// Godot `Vector2 / float`: componentwise division (NOT multiply-by-reciprocal).
impl Div<f32> for Vec2 {
    type Output = Vec2;
    fn div(self, s: f32) -> Vec2 {
        Vec2::new(self.x / s, self.y / s)
    }
}

impl Neg for Vec2 {
    type Output = Vec2;
    fn neg(self) -> Vec2 {
        Vec2::new(-self.x, -self.y)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_normalizes_to_zero() {
        assert_eq!(Vec2::ZERO.normalized(), Vec2::ZERO);
    }

    #[test]
    fn diagonal_normalizes() {
        let d = Vec2::new(1.0, 1.0).normalized();
        assert!((d.x - std::f32::consts::FRAC_1_SQRT_2).abs() < 1e-6);
        assert!((d.y - std::f32::consts::FRAC_1_SQRT_2).abs() < 1e-6);
    }

    #[test]
    fn approx_asymmetric() {
        assert!(is_equal_approx_f64(1000.0, 1000.005));
        assert!(!is_equal_approx_f64(0.0, 0.005));
    }
}
