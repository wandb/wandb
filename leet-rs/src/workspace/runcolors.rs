//! Stable, non-colliding color assignment for workspace runs.
//!
//! Each run path is anchored to its original hashed palette color. Collisions
//! are resolved by generating nearby color variants that stay visually close
//! to the palette while remaining unique within the current workspace.

use std::collections::HashMap;

use crate::theme::{Adaptive, color_index, graph_colors};

const VARIANT_PHASES: i32 = 6;
const HUE_STEP: f64 = 17.0;
const LIGHTNESS_STEP: f64 = 0.035;
const SATURATION_STEP: f64 = 0.05;

/// Keeps allocation bounded even in large workspaces.
const MAX_VARIANTS: i32 = 1024;

pub struct WorkspaceRunColors {
    palette: Vec<Adaptive>,
    assigned: HashMap<String, Adaptive>,
    /// Serialized color -> owning run path.
    used: HashMap<(u32, u32), String>,
}

fn color_key(c: Adaptive) -> (u32, u32) {
    let pack = |(r, g, b): (u8, u8, u8)| (r as u32) << 16 | (g as u32) << 8 | b as u32;
    (pack(c.light), pack(c.dark))
}

impl WorkspaceRunColors {
    pub fn new(palette: &'static [Adaptive]) -> Self {
        let palette = if palette.is_empty() {
            graph_colors(crate::theme::DEFAULT_COLOR_SCHEME)
        } else {
            palette
        };
        Self {
            palette: palette.to_vec(),
            assigned: HashMap::new(),
            used: HashMap::new(),
        }
    }

    /// Returns the stable color for `run_path`, allocating one if needed.
    pub fn assign(&mut self, run_path: &str) -> Adaptive {
        if let Some(&c) = self.assigned.get(run_path) {
            return c;
        }
        let c = self.pick_color(run_path);
        self.assigned.insert(run_path.to_string(), c);
        self.used.insert(color_key(c), run_path.to_string());
        c
    }

    /// Forgets the color assignment for `run_path` so it can be reused.
    pub fn release(&mut self, run_path: &str) {
        let Some(c) = self.assigned.remove(run_path) else {
            return;
        };
        let key = color_key(c);
        if self.used.get(&key).is_some_and(|owner| owner == run_path) {
            self.used.remove(&key);
        }
    }

    fn pick_color(&self, run_path: &str) -> Adaptive {
        let base = self.palette[color_index(run_path, self.palette.len())];
        if self.is_available(base, run_path) {
            return base;
        }
        for step in 1..=MAX_VARIANTS {
            let candidate = color_variant(base, step);
            if self.is_available(candidate, run_path) {
                return candidate;
            }
        }
        base
    }

    fn is_available(&self, c: Adaptive, run_path: &str) -> bool {
        match self.used.get(&color_key(c)) {
            Some(owner) => owner == run_path,
            None => true,
        }
    }
}

/// Returns the step-th nearby variant of `base`.
///
/// The search expands in rings around the hashed base color. Hue always
/// shifts so adjacent collisions remain visually distinct. Saturation and
/// lightness use a reflected walk instead of simple clamping, which avoids
/// collapsing repeated attempts to identical black, white, or gray endpoints.
fn color_variant(base: Adaptive, step: i32) -> Adaptive {
    if step <= 0 {
        return base;
    }

    let ring = 1 + (step - 1) / VARIANT_PHASES;
    let phase = (step - 1) % VARIANT_PHASES;

    let mut hue_shift = f64::from(ring) * HUE_STEP;
    if phase % 2 == 1 {
        hue_shift = -hue_shift;
    }

    let magnitude = f64::from(ring);
    let (lightness_delta, saturation_delta) = match phase {
        0 => (LIGHTNESS_STEP * magnitude, 0.0),
        1 => (-LIGHTNESS_STEP * magnitude, 0.0),
        2 => (0.0, SATURATION_STEP * magnitude),
        3 => (0.0, -SATURATION_STEP * magnitude),
        4 => (
            0.5 * LIGHTNESS_STEP * magnitude,
            0.5 * SATURATION_STEP * magnitude,
        ),
        _ => (
            -0.5 * LIGHTNESS_STEP * magnitude,
            -0.5 * SATURATION_STEP * magnitude,
        ),
    };

    Adaptive {
        light: adjust(base.light, hue_shift, saturation_delta, lightness_delta),
        dark: adjust(base.dark, hue_shift, saturation_delta, lightness_delta),
    }
}

fn adjust(
    (r, g, b): (u8, u8, u8),
    hue_shift: f64,
    saturation_delta: f64,
    lightness_delta: f64,
) -> (u8, u8, u8) {
    let (h, s, l) = rgb_to_hsl(r, g, b);
    hsl_to_rgb(
        wrap_hue(h + hue_shift),
        reflect01(s + saturation_delta),
        reflect01(l + lightness_delta),
    )
}

fn rgb_to_hsl(r: u8, g: u8, b: u8) -> (f64, f64, f64) {
    let rf = f64::from(r) / 255.0;
    let gf = f64::from(g) / 255.0;
    let bf = f64::from(b) / 255.0;

    let max_c = rf.max(gf).max(bf);
    let min_c = rf.min(gf).min(bf);
    let l = (max_c + min_c) / 2.0;

    if max_c == min_c {
        return (0.0, 0.0, l);
    }

    let delta = max_c - min_c;
    let s = if l > 0.5 {
        delta / (2.0 - max_c - min_c)
    } else {
        delta / (max_c + min_c)
    };

    let mut h = if max_c == rf {
        let mut h = (gf - bf) / delta;
        if gf < bf {
            h += 6.0;
        }
        h
    } else if max_c == gf {
        (bf - rf) / delta + 2.0
    } else {
        (rf - gf) / delta + 4.0
    };
    h *= 60.0;
    (h, s, l)
}

fn hsl_to_rgb(h: f64, s: f64, l: f64) -> (u8, u8, u8) {
    let h = wrap_hue(h) / 360.0;
    if s == 0.0 {
        let gray = (l * 255.0).round() as u8;
        return (gray, gray, gray);
    }

    let q = if l < 0.5 {
        l * (1.0 + s)
    } else {
        l + s - l * s
    };
    let p = 2.0 * l - q;

    let to_byte = |v: f64| (v * 255.0).round() as u8;
    (
        to_byte(hue_to_rgb(p, q, h + 1.0 / 3.0)),
        to_byte(hue_to_rgb(p, q, h)),
        to_byte(hue_to_rgb(p, q, h - 1.0 / 3.0)),
    )
}

fn hue_to_rgb(p: f64, q: f64, mut t: f64) -> f64 {
    while t < 0.0 {
        t += 1.0;
    }
    while t > 1.0 {
        t -= 1.0;
    }
    if t < 1.0 / 6.0 {
        p + (q - p) * 6.0 * t
    } else if t < 1.0 / 2.0 {
        q
    } else if t < 2.0 / 3.0 {
        p + (q - p) * (2.0 / 3.0 - t) * 6.0
    } else {
        p
    }
}

fn wrap_hue(h: f64) -> f64 {
    let h = h % 360.0;
    if h < 0.0 { h + 360.0 } else { h }
}

/// Folds `v` into [0, 1] by reflecting at the interval boundaries.
///
/// Unlike clamping, reflection preserves variation for large offsets instead
/// of flattening multiple candidates to the same endpoint.
fn reflect01(v: f64) -> f64 {
    let mut v = v % 2.0;
    if v < 0.0 {
        v += 2.0;
    }
    if v > 1.0 { 2.0 - v } else { v }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::theme::DEFAULT_COLOR_SCHEME;

    #[test]
    fn stable_assignment() {
        let mut colors = WorkspaceRunColors::new(graph_colors(DEFAULT_COLOR_SCHEME));
        let a = colors.assign("run-a");
        let b = colors.assign("run-b");
        assert_eq!(a, colors.assign("run-a"));
        assert_eq!(b, colors.assign("run-b"));
    }

    #[test]
    fn collisions_resolved_with_variants() {
        let mut colors = WorkspaceRunColors::new(graph_colors(DEFAULT_COLOR_SCHEME));
        // Assign many runs; all colors must be distinct.
        let mut seen = std::collections::HashSet::new();
        for i in 0..64 {
            let c = colors.assign(&format!("run-{i}"));
            assert!(seen.insert(color_key(c)), "duplicate color at {i}");
        }
    }

    #[test]
    fn release_allows_reuse() {
        let mut colors = WorkspaceRunColors::new(graph_colors(DEFAULT_COLOR_SCHEME));
        let a = colors.assign("run-a");
        colors.release("run-a");
        // A run hashing to the same palette slot can take the base color.
        let b = colors.assign("run-a");
        assert_eq!(a, b);
    }

    #[test]
    fn hsl_roundtrip() {
        let (h, s, l) = rgb_to_hsl(0xFC, 0xBC, 0x32);
        let (r, g, b) = hsl_to_rgb(h, s, l);
        assert!((i32::from(r) - 0xFC).abs() <= 1);
        assert!((i32::from(g) - 0xBC).abs() <= 1);
        assert!((i32::from(b) - 0x32).abs() <= 1);
    }
}
