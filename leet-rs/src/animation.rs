//! Smooth expand/collapse animation for pane sizes.

use std::time::{Duration, Instant};

/// Duration of expand/collapse animations.
pub const ANIMATION_DURATION: Duration = Duration::from_millis(150);

/// Frame interval while animating (duration / 10 steps).
pub const ANIMATION_FRAME: Duration = Duration::from_millis(15);

/// Manages a scalar (width, height, etc.) that animates smoothly between a
/// collapsed state (0) and an expanded state.
#[derive(Debug, Clone)]
pub struct AnimatedValue {
    /// Current rendered size.
    current: i32,
    /// Desired size we're animating toward.
    target: i32,
    /// Fully-expanded size.
    expanded: i32,
    /// Rendered size at the beginning of the current animation.
    start_value: i32,
    /// When the current animation started; `None` when idle.
    start_time: Option<Instant>,
}

impl AnimatedValue {
    pub fn new(is_expanded: bool, expanded_size: i32) -> Self {
        let v = if is_expanded { expanded_size } else { 0 };
        Self {
            current: v,
            target: v,
            expanded: expanded_size,
            start_value: v,
            start_time: None,
        }
    }

    /// Toggles between expanded and collapsed targets. If already animating,
    /// reverses direction from the current interpolated value.
    pub fn toggle(&mut self) {
        let now = Instant::now();
        self.advance(now);

        self.target = if self.target == 0 { self.expanded } else { 0 };
        if self.current == self.target {
            self.start_value = self.current;
            self.start_time = None;
            return;
        }
        self.start_value = self.current;
        self.start_time = Some(now);
    }

    /// Advances the animation; returns whether it is complete.
    pub fn update(&mut self, now: Instant) -> bool {
        self.advance(now)
    }

    fn advance(&mut self, now: Instant) -> bool {
        if self.current == self.target {
            self.start_value = self.current;
            self.start_time = None;
            return true;
        }
        let start_time = match self.start_time {
            Some(t) => t,
            None => {
                self.start_value = self.current;
                self.start_time = Some(now);
                return self.current == self.target;
            }
        };

        let elapsed = now.saturating_duration_since(start_time);
        if elapsed.is_zero() {
            return false;
        }

        let progress = elapsed.as_secs_f64() / ANIMATION_DURATION.as_secs_f64();
        if progress >= 1.0 {
            self.current = self.target;
            self.start_value = self.target;
            self.start_time = None;
            return true;
        }

        let eased = ease_out_cubic(progress);
        let next = f64::from(self.start_value) + eased * f64::from(self.target - self.start_value);
        self.current = next.round() as i32;
        false
    }

    /// Updates the desired expanded size.
    pub fn set_expanded(&mut self, size: i32) {
        let now = Instant::now();
        let was_expanded = self.target > 0 && self.current == self.target;

        self.advance(now);
        self.expanded = size;

        if self.target == 0 {
            return;
        }
        if was_expanded {
            // Stably expanded; snap immediately to the new size.
            self.current = size;
            self.start_value = size;
            self.target = size;
            self.start_time = None;
            return;
        }

        // Already animating toward this size; restarting the easing clock
        // every frame would converge short of the target and never finish.
        if self.target == size {
            return;
        }

        // Animate smoothly toward the new expanded size.
        self.target = size;
        self.start_value = self.current;
        if self.current == self.target {
            self.start_time = None;
            return;
        }
        self.start_time = Some(now);
    }

    pub fn value(&self) -> i32 {
        self.current
    }

    pub fn is_animating(&self) -> bool {
        self.current != self.target
    }

    pub fn is_visible(&self) -> bool {
        self.current > 0
    }

    /// True if stably at the expanded value.
    pub fn is_expanded(&self) -> bool {
        self.target > 0 && self.current == self.target
    }

    /// True if stably at zero.
    #[allow(dead_code)]
    pub fn is_collapsed(&self) -> bool {
        self.target == 0 && self.current == 0
    }

    /// Immediately snaps to zero without animation.
    pub fn force_collapse(&mut self) {
        self.current = 0;
        self.start_value = 0;
        self.target = 0;
        self.start_time = None;
    }

    /// Immediately snaps to the expanded value without animation.
    pub fn force_expand(&mut self) {
        self.current = self.expanded;
        self.start_value = self.expanded;
        self.target = self.expanded;
        self.start_time = None;
    }

    /// Whether the animation's target is expanded (intended logical
    /// visibility, regardless of the current interpolated value).
    pub fn target_visible(&self) -> bool {
        self.target > 0
    }
}

/// Maps t ∈ [0, 1] -> [0, 1] with deceleration near the end: (t-1)^3 + 1.
fn ease_out_cubic(t: f64) -> f64 {
    (t - 1.0) * (t - 1.0) * (t - 1.0) + 1.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    /// Calling set_expanded with an unchanged size on every frame (as layout
    /// recomputation does) must not restart the easing clock, or the value
    /// converges short of the target and never finishes animating.
    #[test]
    fn per_frame_set_expanded_does_not_stall_animation() {
        let mut av = AnimatedValue::new(false, 16);
        av.toggle();

        let start = Instant::now();
        for frame in 1..=40 {
            let now = start + Duration::from_millis(15 * frame);
            av.update(now);
            av.set_expanded(16);
        }

        assert_eq!(av.value(), 16);
        assert!(!av.is_animating());
    }
}
