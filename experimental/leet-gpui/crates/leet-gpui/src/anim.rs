//! Pane show and hide animation, the curve and duration of leet's
//! `AnimatedValue` (`core/internal/leet/animation.go`).

use std::time::{Duration, Instant};

pub const DURATION: Duration = Duration::from_millis(150);

/// A value easing from 0 (hidden) to 1 (shown) or back; retargeting mid-way
/// starts from the current value.
pub struct Animated {
    start: f32,
    target: f32,
    since: Instant,
}

impl Animated {
    pub fn new(shown: bool) -> Self {
        let value = if shown { 1.0 } else { 0.0 };
        Animated {
            start: value,
            target: value,
            since: Instant::now(),
        }
    }

    pub fn set(&mut self, shown: bool) {
        let target = if shown { 1.0 } else { 0.0 };
        if target != self.target {
            self.start = self.value_at(Instant::now());
            self.target = target;
            self.since = Instant::now();
        }
    }

    pub fn value(&self) -> f32 {
        self.value_at(Instant::now())
    }

    fn value_at(&self, now: Instant) -> f32 {
        let t = (now.duration_since(self.since).as_secs_f32() / DURATION.as_secs_f32()).min(1.0);
        let eased = 1.0 - (1.0 - t).powi(3);
        self.start + (self.target - self.start) * eased
    }

    pub fn animating(&self) -> bool {
        self.start != self.target && self.since.elapsed() < DURATION
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eases_toward_the_target_and_retargets_from_the_current_value() {
        let mut anim = Animated::new(false);
        anim.set(true);
        let half = anim.since + DURATION / 2;
        let midway = anim.value_at(half);
        assert!((0.8..0.9).contains(&midway), "{midway}");
        assert_eq!(anim.value_at(anim.since + DURATION), 1.0);

        anim.since = Instant::now() - DURATION / 2;
        anim.set(false);
        assert!((0.8..0.9).contains(&anim.start), "{}", anim.start);
        assert_eq!(anim.target, 0.0);
    }
}
