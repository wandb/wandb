//! Port of `core/internal/leet/workspace_runcolors.go`.
//!
//! Stable per-run color assignment with collision avoidance: colors are
//! anchored to the hashed palette color and collisions are resolved by
//! walking nearby HSL variants.

use std::collections::HashMap;

use crate::styles::{AdaptiveColor, Rgb, color_index, graph_colors};

const WORKSPACE_RUN_COLOR_VARIANT_PHASES: i64 = 6;
const WORKSPACE_RUN_COLOR_HUE_STEP: f64 = 17.0;
const WORKSPACE_RUN_COLOR_LIGHTNESS_STEP: f64 = 0.035;
const WORKSPACE_RUN_COLOR_SATURATION_STEP: f64 = 0.05;

// Keep allocation bounded even in large workspaces. The reflected
// saturation/lightness walk below preserves enough variation that this still
// provides ample headroom per base color before any fallback to reuse.
const MAX_WORKSPACE_RUN_COLOR_VARIANTS: i64 = 1024;

/// `WorkspaceRunColors` assigns stable, non-colliding colors to workspace runs.
///
/// Each run path is anchored to its original hashed palette color. Collisions
/// are resolved by generating nearby color variants that stay visually close
/// to the palette while remaining unique within the current workspace.
///
/// The workspace owns this allocator on the update thread, so it does not
/// require internal locking.
pub struct WorkspaceRunColors {
    palette: Vec<AdaptiveColor>,
    /// run path -> color
    assigned: HashMap<String, AdaptiveColor>,
    /// serialized color -> run path
    used: HashMap<String, String>,
}

impl WorkspaceRunColors {
    /// Go: `newWorkspaceRunColors`.
    pub fn new(palette: &[AdaptiveColor]) -> Self {
        let palette = if palette.is_empty() {
            // Go: `GraphColors(DefaultColorScheme)`.
            graph_colors(leet_data::config::DEFAULT_COLOR_SCHEME).to_vec()
        } else {
            // Go clones the caller's slice (`append([]AdaptiveColor(nil), ...)`).
            palette.to_vec()
        };
        Self {
            palette,
            assigned: HashMap::new(),
            used: HashMap::new(),
        }
    }

    /// Assign returns the stable color for `run_path`, allocating one if needed.
    pub fn assign(&mut self, run_path: &str) -> AdaptiveColor {
        if let Some(&c) = self.assigned.get(run_path) {
            return c;
        }

        let c = self.pick_color(run_path);
        self.assigned.insert(run_path.to_string(), c);
        self.used
            .insert(workspace_run_color_key(c), run_path.to_string());
        c
    }

    /// Release forgets the color assignment for `run_path` so the color can be
    /// reused.
    pub fn release(&mut self, run_path: &str) {
        let Some(c) = self.assigned.remove(run_path) else {
            return;
        };

        let key = workspace_run_color_key(c);
        if self.used.get(&key).is_some_and(|owner| owner == run_path) {
            self.used.remove(&key);
        }
    }

    fn pick_color(&self, run_path: &str) -> AdaptiveColor {
        let base = self.palette[color_index(run_path, self.palette.len())];
        if self.is_available(base, run_path) {
            return base;
        }

        for step in 1..=MAX_WORKSPACE_RUN_COLOR_VARIANTS {
            let candidate = workspace_run_color_variant(base, step);
            if self.is_available(candidate, run_path) {
                return candidate;
            }
        }

        base
    }

    fn is_available(&self, c: AdaptiveColor, run_path: &str) -> bool {
        match self.used.get(&workspace_run_color_key(c)) {
            None => true,
            Some(owner) => owner == run_path,
        }
    }
}

// Go is package-private but exposed to black-box tests via testhelpers.go
// `TestWorkspaceRunColorKey`; testhelpers is not ported (PORTING.md), so this
// is `pub` for the `Workspace` tests that port with workspace.go to leet-tui.
pub fn workspace_run_color_key(c: AdaptiveColor) -> String {
    format!(
        "{}|{}",
        normalize_workspace_run_color_component(c.light),
        normalize_workspace_run_color_component(c.dark)
    )
}

fn normalize_workspace_run_color_component(component: Rgb) -> String {
    // PARITY: Go lowercases/trims `fmt.Sprint(component)` when the component
    // is not RGB-parseable; unreachable here because components are concrete
    // `Rgb`.
    let (r, g, b) = workspace_run_color_component_rgb(component);
    format!("#{r:02X}{g:02X}{b:02X}")
}

fn workspace_run_color_component_rgb(component: Rgb) -> (u8, u8, u8) {
    // PARITY: Go inspects `any` (an `image/color.Color` via the NRGBA model,
    // else a "#RRGGBB" string via `parseHexColor`) and can fail; the concrete
    // `Rgb` conversion is total.
    let Rgb(r, g, b) = component;
    (r, g, b)
}

/// `workspace_run_color_variant` returns the step-th nearby variant of base.
///
/// The search expands in rings around the hashed base color. Hue always shifts
/// so adjacent collisions remain visually distinct. Saturation and lightness
/// use a reflected walk instead of simple clamping, which avoids collapsing
/// repeated attempts to identical black, white, or gray endpoints.
fn workspace_run_color_variant(base: AdaptiveColor, step: i64) -> AdaptiveColor {
    if step <= 0 {
        return base;
    }

    let ring = 1 + (step - 1) / WORKSPACE_RUN_COLOR_VARIANT_PHASES;
    let phase = (step - 1) % WORKSPACE_RUN_COLOR_VARIANT_PHASES;

    let mut hue_shift = ring as f64 * WORKSPACE_RUN_COLOR_HUE_STEP;
    if phase % 2 == 1 {
        hue_shift = -hue_shift;
    }

    let mut lightness_delta = 0.0;
    let mut saturation_delta = 0.0;
    let magnitude = ring as f64;

    match phase {
        0 => lightness_delta = WORKSPACE_RUN_COLOR_LIGHTNESS_STEP * magnitude,
        1 => lightness_delta = -WORKSPACE_RUN_COLOR_LIGHTNESS_STEP * magnitude,
        2 => saturation_delta = WORKSPACE_RUN_COLOR_SATURATION_STEP * magnitude,
        3 => saturation_delta = -WORKSPACE_RUN_COLOR_SATURATION_STEP * magnitude,
        4 => {
            lightness_delta = 0.5 * WORKSPACE_RUN_COLOR_LIGHTNESS_STEP * magnitude;
            saturation_delta = 0.5 * WORKSPACE_RUN_COLOR_SATURATION_STEP * magnitude;
        }
        5 => {
            lightness_delta = -0.5 * WORKSPACE_RUN_COLOR_LIGHTNESS_STEP * magnitude;
            saturation_delta = -0.5 * WORKSPACE_RUN_COLOR_SATURATION_STEP * magnitude;
        }
        _ => {}
    }

    AdaptiveColor {
        light: adjust_workspace_run_color(base.light, hue_shift, saturation_delta, lightness_delta),
        dark: adjust_workspace_run_color(base.dark, hue_shift, saturation_delta, lightness_delta),
    }
}

fn adjust_workspace_run_color(
    base: Rgb,
    hue_shift: f64,
    saturation_delta: f64,
    lightness_delta: f64,
) -> Rgb {
    // PARITY: Go falls back to passing the raw string through as a
    // `lipgloss.Color` when the component is not RGB-parseable; unreachable
    // here because components are concrete `Rgb`.
    let (r, g, b) = workspace_run_color_component_rgb(base);

    let (h, s, l) = rgb_to_hsl(r, g, b);
    let h = wrap_hue(h + hue_shift);
    let s = reflect01(s + saturation_delta);
    let l = reflect01(l + lightness_delta);

    let (r2, g2, b2) = hsl_to_rgb(h, s, l);
    Rgb(r2, g2, b2)
}

fn rgb_to_hsl(r: u8, g: u8, b: u8) -> (f64, f64, f64) {
    let rf = f64::from(r) / 255.0;
    let gf = f64::from(g) / 255.0;
    let bf = f64::from(b) / 255.0;

    // PARITY: Go's builtin max/min propagate NaN, `f64::max/min` do not;
    // inputs here are derived from u8 so they are always finite.
    let max_c = rf.max(gf.max(bf));
    let min_c = rf.min(gf.min(bf));
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

    let mut h;
    if max_c == rf {
        h = (gf - bf) / delta;
        if gf < bf {
            h += 6.0;
        }
    } else if max_c == gf {
        h = (bf - rf) / delta + 2.0;
    } else {
        h = (rf - gf) / delta + 4.0;
    }

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

    let r = hue_to_rgb(p, q, h + 1.0 / 3.0);
    let g = hue_to_rgb(p, q, h);
    let b = hue_to_rgb(p, q, h - 1.0 / 3.0);

    (
        (r * 255.0).round() as u8,
        (g * 255.0).round() as u8,
        (b * 255.0).round() as u8,
    )
}

fn hue_to_rgb(p: f64, q: f64, t: f64) -> f64 {
    let mut t = t;
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
    // Rust's `%` on f64 matches Go `math.Mod` (truncated remainder, sign of
    // the dividend).
    let mut h = h % 360.0;
    if h < 0.0 {
        h += 360.0;
    }
    h
}

/// `reflect01` folds v into [0, 1] by reflecting at the interval boundaries.
/// Unlike clamping, reflection preserves variation for large offsets instead
/// of flattening multiple candidates to the same endpoint.
fn reflect01(v: f64) -> f64 {
    let mut v = v % 2.0;
    if v < 0.0 {
        v += 2.0;
    }
    if v > 1.0 {
        return 2.0 - v;
    }
    v
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use pretty_assertions::{assert_eq, assert_ne};

    use super::*;

    // NOTE: Go's workspace_runcolors_test.go also contains
    // TestWorkspaceApplyRunKeysAssignsUniqueColors and
    // TestWorkspaceApplyRunKeysReusesReleasedColor; they exercise `Workspace`
    // and port with workspace.go to `leet-tui`.

    fn hex(s: &str) -> Rgb {
        crate::styles::parse_hex_color(s).expect("valid hex literal")
    }

    // Go: testWorkspaceRunColorPalette.
    fn test_workspace_run_color_palette() -> Vec<AdaptiveColor> {
        vec![AdaptiveColor {
            light: hex("#3DBAC4"),
            dark: hex("#58D3DB"),
        }]
    }

    // Go: TestWorkspaceRunColorsAssignUniqueWithinWorkspace.
    #[test]
    fn workspace_run_colors_assign_unique_within_workspace() {
        let mut colors = WorkspaceRunColors::new(&test_workspace_run_color_palette());

        let mut seen: HashMap<String, String> = HashMap::new();
        for i in 0..256 {
            let run_path = format!("/tmp/run-{i:03}.wandb");
            let key = workspace_run_color_key(colors.assign(&run_path));
            if let Some(previous) = seen.get(&key) {
                panic!("workspace color collision: {previous} and {run_path} both mapped to {key}");
            }
            seen.insert(key, run_path);
        }
    }

    // Go: TestWorkspaceRunColorsReleaseAllowsReuse.
    #[test]
    fn workspace_run_colors_release_allows_reuse() {
        let mut colors = WorkspaceRunColors::new(&test_workspace_run_color_palette());

        let first = colors.assign("/tmp/first.wandb");
        let second = colors.assign("/tmp/second.wandb");
        assert_ne!(
            workspace_run_color_key(second),
            workspace_run_color_key(first)
        );

        colors.release("/tmp/first.wandb");
        let third = colors.assign("/tmp/third.wandb");
        assert_eq!(
            workspace_run_color_key(third),
            workspace_run_color_key(first)
        );
    }

    // Go: TestWorkspaceRunColorComponentRGBAcceptsColorColor.
    //
    // PARITY: Go exercises the `image/color.Color` branch (NRGBA model
    // conversion); the Rust component is concrete `Rgb`, so the conversion is
    // the identity.
    #[test]
    fn workspace_run_color_component_rgb_accepts_color_color() {
        let (r, g, b) = workspace_run_color_component_rgb(Rgb(0x3D, 0xBA, 0xC4));
        assert_eq!(r, 0x3D);
        assert_eq!(g, 0xBA);
        assert_eq!(b, 0xC4);
    }
}
