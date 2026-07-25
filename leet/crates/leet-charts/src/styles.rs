//! Port of `core/internal/leet/styles.go`.
//!
//! Trial-port scope: only the animation constants — palettes, adaptive
//! colors, and lipgloss styles land in Phase 3.

use std::time::Duration;

/// The duration for sidebar animations.
pub const ANIMATION_DURATION: Duration = Duration::from_millis(150);

/// The number of steps in sidebar animations.
pub const ANIMATION_STEPS: u32 = 10;

/// The tick interval used for sidebar animations
/// (ANIMATION_DURATION / ANIMATION_STEPS).
pub const ANIMATION_FRAME: Duration = Duration::from_millis(15);
