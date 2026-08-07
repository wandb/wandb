//! Port of `core/internal/leet/animation.go`.
//!
//! Go guarded `AnimatedValue` with an RWMutex because bubbletea's renderer
//! reads `Value()` concurrently with `Update`; in the Rust design update and
//! view run on one thread, so the lock dies (CONCURRENCY.md §2).

use std::time::Instant;

use leet_charts::styles::ANIMATION_DURATION;

/// AnimatedValue manages a scalar (width, height, etc.) that animates
/// smoothly between a collapsed state (0) and an expanded state.
#[derive(Debug, Clone)]
pub struct AnimatedValue {
    /// The current rendered size (px/cols/rows).
    current: isize,

    /// The desired size we're animating toward.
    target: isize,

    /// The fully-expanded size.
    expanded: isize,

    /// The rendered size at the beginning of the current animation.
    start_value: isize,

    /// When the current animation started. `None` ≙ Go's zero time.
    start_time: Option<Instant>,
}

impl AnimatedValue {
    pub fn new(is_expanded: bool, expanded_size: isize) -> Self {
        let mut a = AnimatedValue {
            current: 0,
            target: 0,
            expanded: expanded_size,
            start_value: 0,
            start_time: None,
        };
        if is_expanded {
            a.current = expanded_size;
            a.target = expanded_size;
            a.start_value = expanded_size;
        }
        a
    }

    /// Toggle toggles between expanded and collapsed targets.
    ///
    /// If the value is already animating, Toggle reverses direction from the
    /// current interpolated value rather than jumping back to 0 or expanded.
    pub fn toggle(&mut self) {
        let now = Instant::now();
        self.advance(now);

        if self.target == 0 {
            self.target = self.expanded;
        } else {
            self.target = 0;
        }
        if self.current == self.target {
            self.start_value = self.current;
            self.start_time = None;
            return;
        }

        self.start_value = self.current;
        self.start_time = Some(now);

        if leet_data::test_mode::enabled() {
            self.snap_to_target();
        }
    }

    /// Update advances the animation given a wall-clock time and returns
    /// whether the animation is complete.
    pub fn update(&mut self, now: Instant) -> bool {
        self.advance(now)
    }

    /// advance updates current to match now.
    fn advance(&mut self, now: Instant) -> bool {
        if self.current == self.target {
            self.start_value = self.current;
            self.start_time = None;
            return true;
        }
        let Some(start_time) = self.start_time else {
            self.start_value = self.current;
            self.start_time = Some(now);
            return self.current == self.target;
        };

        // Go: `elapsed <= 0` → still animating. `checked_duration_since`
        // yields None when `now` precedes the start, the same case.
        let Some(elapsed) = now.checked_duration_since(start_time) else {
            return false;
        };
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
        let next = self.start_value as f64 + eased * (self.target - self.start_value) as f64;
        self.current = next.round() as isize;
        false
    }

    /// snap_to_target completes the animation immediately so that no
    /// animation ticks are scheduled (`is_animating` reports false).
    fn snap_to_target(&mut self) {
        self.current = self.target;
        self.start_value = self.target;
        self.start_time = None;
    }

    /// SetExpanded updates the desired expanded size.
    pub fn set_expanded(&mut self, size: isize) {
        let now = Instant::now();
        let was_expanded = self.target > 0 && self.current == self.target;

        self.advance(now);
        self.expanded = size;

        if self.target == 0 {
            return;
        }
        if was_expanded {
            // We were stably expanded; snap immediately to the new size.
            self.current = size;
            self.start_value = size;
            self.target = size;
            self.start_time = None;
            return;
        }

        // Preserve the current rendered value and animate smoothly toward
        // the new expanded size.
        self.target = size;
        self.start_value = self.current;
        if self.current == self.target {
            self.start_time = None;
            return;
        }
        self.start_time = Some(now);

        if leet_data::test_mode::enabled() {
            self.snap_to_target();
        }
    }

    /// The current animated value.
    pub fn value(&self) -> isize {
        self.current
    }

    /// Whether the value is in motion.
    pub fn is_animating(&self) -> bool {
        self.current != self.target
    }

    /// True if the value is greater than zero.
    pub fn is_visible(&self) -> bool {
        self.current > 0
    }

    /// True if we're stably at the expanded value.
    pub fn is_expanded(&self) -> bool {
        self.target > 0 && self.current == self.target
    }

    /// True if we're stably at zero.
    pub fn is_collapsed(&self) -> bool {
        self.target == 0 && self.current == 0
    }

    /// Whether we're animating toward the expanded value.
    pub fn is_expanding(&self) -> bool {
        self.current < self.target
    }

    /// Whether we're animating toward zero.
    pub fn is_collapsing(&self) -> bool {
        self.current > self.target
    }

    /// Immediately snaps to zero without animation.
    pub fn force_collapse(&mut self) {
        self.current = 0;
        self.start_value = 0;
        self.target = 0;
        self.start_time = None;
    }

    /// Immediately snaps to the expanded value without animation.
    ///
    /// Intended for tests that need to skip animation.
    pub fn force_expand(&mut self) {
        self.current = self.expanded;
        self.start_value = self.expanded;
        self.target = self.expanded;
        self.start_time = None;
    }

    /// Whether the animation's target is expanded. Unlike `is_visible`
    /// (current > 0) and `is_expanded` (current == target), this reflects
    /// the intended logical visibility.
    pub fn target_visible(&self) -> bool {
        self.target > 0
    }
}

/// ease_out_cubic maps t ∈ [0, 1] -> [0, 1] with deceleration near the end.
///
/// Values outside [0,1] are acceptable; callers clamp at 1.
fn ease_out_cubic(t: f64) -> f64 {
    // (t-1)^3 + 1
    (t - 1.0) * (t - 1.0) * (t - 1.0) + 1.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn toggle_starts_animation() {
        let mut anim = AnimatedValue::new(false, 40);
        anim.toggle();
        assert!(anim.is_animating());
        while anim.is_animating() {
            std::thread::sleep(Duration::from_millis(20));
            anim.update(Instant::now());
        }
        assert!(anim.is_visible());
        assert!(anim.is_expanded());
        assert_eq!(anim.value(), 40);

        anim.toggle();
        assert!(anim.is_animating());
        while anim.is_animating() {
            std::thread::sleep(Duration::from_millis(20));
            anim.update(Instant::now());
        }
        assert!(anim.is_collapsed());
        assert!(!anim.is_visible());
        assert_eq!(anim.value(), 0);
    }

    #[test]
    fn update_animates_to_completion() {
        let mut anim = AnimatedValue::new(false, 50);

        let mut values_seen = std::collections::HashSet::new();
        let max_iterations = 100;
        let mut iterations = 0;

        anim.toggle();

        while anim.is_animating() && iterations < max_iterations {
            let complete = anim.update(Instant::now());
            values_seen.insert(anim.value());

            if !complete {
                std::thread::sleep(Duration::from_millis(10));
            }
            iterations += 1;
        }

        // Should have seen multiple intermediate values.
        assert!(
            values_seen.len() > 2,
            "animation should progress through multiple values"
        );
        assert_eq!(anim.value(), 50, "should end at target value");
        assert!(!anim.is_animating(), "animation should be complete");
    }

    #[test]
    fn toggle_during_animation() {
        let mut anim = AnimatedValue::new(false, 50);
        anim.toggle();

        // Let it animate partway.
        std::thread::sleep(Duration::from_millis(50));
        anim.update(Instant::now());

        let partial_value = anim.value();
        assert!(partial_value > 0, "should have started expanding");
        assert!(partial_value < 50, "should not be fully expanded");

        // Toggle during animation should revert back to the original state.
        anim.toggle();
        while anim.is_animating() {
            std::thread::sleep(Duration::from_millis(10));
            anim.update(Instant::now());
        }
        assert_eq!(anim.value(), 0);
    }

    #[test]
    fn set_expanded_snaps_when_already_expanded() {
        let mut anim = AnimatedValue::new(true, 40); // expanded at 40
        assert!(anim.is_expanded());
        assert_eq!(anim.value(), 40);

        anim.set_expanded(80); // first WindowSizeMsg computes larger target

        // Should snap immediately because we were stably expanded.
        assert!(anim.is_expanded());
        assert_eq!(anim.value(), 80);
    }

    #[test]
    fn set_expanded_does_not_snap_when_collapsed() {
        let mut anim = AnimatedValue::new(false, 40); // collapsed
        assert!(!anim.is_visible());

        anim.set_expanded(80);
        // Still collapsed; only the future target changed.
        assert!(!anim.is_visible());
        assert_eq!(anim.value(), 0);
    }

    #[test]
    fn set_expanded_during_animation_rebases_smoothly() {
        let mut anim = AnimatedValue::new(false, 40);
        let now = Instant::now();

        anim.toggle();
        anim.update(now + Duration::from_millis(40));
        let partial = anim.value();
        assert!(partial > 0);
        assert!(partial < 40);

        anim.set_expanded(80);
        anim.update(now + Duration::from_millis(60));
        assert!(anim.value() >= partial);
        assert!(anim.value() <= 80);

        anim.update(now + 2 * ANIMATION_DURATION);
        assert_eq!(anim.value(), 80);
        assert!(anim.is_expanded());
    }
}
