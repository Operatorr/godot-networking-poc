//! Axis-aligned rect mirroring Godot `Rect2` (position = top-left, y grows downward).

use crate::vec2::Vec2;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Rect {
    pub position: Vec2,
    pub size: Vec2,
}

impl Rect {
    pub const fn new(x: f32, y: f32, w: f32, h: f32) -> Self {
        Self {
            position: Vec2::new(x, y),
            size: Vec2::new(w, h),
        }
    }

    /// Godot `Rect2.has_point`: lower edges inclusive, upper edges EXCLUSIVE. The mover's
    /// behavior depends on this exact convention — do not change it (extraction §4.2).
    pub fn has_point(&self, p: Vec2) -> bool {
        p.x >= self.position.x
            && p.y >= self.position.y
            && p.x < self.position.x + self.size.x
            && p.y < self.position.y + self.size.y
    }

    /// The radius-expanded rect used for the Chebyshev circle-vs-rect tests.
    pub fn expanded(&self, radius: f32) -> Rect {
        Rect {
            position: Vec2::new(self.position.x - radius, self.position.y - radius),
            size: Vec2::new(self.size.x + radius * 2.0, self.size.y + radius * 2.0),
        }
    }

    /// Godot `Rect2.intersects(other, include_borders = true)` — used by the arena tile layout.
    pub fn intersects_inclusive(&self, o: &Rect) -> bool {
        self.position.x <= o.position.x + o.size.x
            && self.position.x + self.size.x >= o.position.x
            && self.position.y <= o.position.y + o.size.y
            && self.position.y + self.size.y >= o.position.y
    }
}
