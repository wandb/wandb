//! Single source of truth for which UI component holds focus.

/// Identifies a focusable UI region.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FocusTarget {
    #[default]
    None,
    RunsList,
    Overview,
    MetricsGrid,
    SystemMetrics,
    Media,
    ConsoleLogs,
}

/// Availability and activation hooks for the focusable regions of a view.
///
/// The owning view implements this; the [`FocusManager`] is taken out of the
/// view (it is cheap to move) while its methods run against the view.
pub trait FocusContext {
    /// Whether the region is currently focusable for normal navigation.
    fn available(&self, target: FocusTarget) -> bool;

    /// Whether the region should be considered focusable immediately after a
    /// visibility toggle. Defaults to `available`.
    fn available_target(&self, target: FocusTarget) -> bool {
        self.available(target)
    }

    /// Activates the region; `direction` is +1 (forward/Tab) or -1
    /// (backward/Shift+Tab) so components like the overview sidebar can
    /// focus their first or last section.
    fn activate(&mut self, target: FocusTarget, direction: i32);

    /// Deactivates the region.
    fn deactivate(&mut self, target: FocusTarget);
}

/// Tracks one [`FocusTarget`] at a time, supports Tab cycling through
/// available regions, and resolves focus after visibility changes. All focus
/// state changes flow through this manager.
#[derive(Debug, Clone, Default)]
pub struct FocusManager {
    current: FocusTarget,
    /// The Tab-cycling order.
    regions: Vec<FocusTarget>,
}

impl FocusManager {
    pub fn new(regions: Vec<FocusTarget>) -> Self {
        Self {
            current: FocusTarget::None,
            regions,
        }
    }

    /// The currently focused target.
    pub fn current(&self) -> FocusTarget {
        self.current
    }

    pub fn is_target(&self, t: FocusTarget) -> bool {
        self.current == t
    }

    /// Updates the global focus target after a region has already applied
    /// its own local mouse-driven focus state.
    ///
    /// Unlike `set_target`, deactivates only the other regions so the target
    /// region's freshly chosen local focus (for example a clicked chart
    /// cell) is preserved.
    pub fn adopt_target<C: FocusContext>(&mut self, ctx: &mut C, t: FocusTarget) {
        if t == FocusTarget::None {
            self.clear_all(ctx);
            return;
        }

        let mut found = false;
        for &region in &self.regions {
            if region == t {
                found = true;
                continue;
            }
            ctx.deactivate(region);
        }
        self.current = if found { t } else { FocusTarget::None };
    }

    /// Deactivates all regions and activates the given target. `direction`
    /// is passed to the activate hook.
    pub fn set_target<C: FocusContext>(&mut self, ctx: &mut C, t: FocusTarget, direction: i32) {
        self.deactivate_all(ctx);
        for &region in &self.regions {
            if region == t {
                self.current = t;
                ctx.activate(t, direction);
                return;
            }
        }
        self.current = FocusTarget::None;
    }

    /// Deactivates all regions and sets focus to none.
    pub fn clear_all<C: FocusContext>(&mut self, ctx: &mut C) {
        self.deactivate_all(ctx);
        self.current = FocusTarget::None;
    }

    /// Cycles focus to the next available region in the given direction
    /// (+1 for Tab, -1 for Shift+Tab).
    pub fn tab<C: FocusContext>(&mut self, ctx: &mut C, direction: i32) {
        let n = self.regions.len() as i32;
        if n == 0 {
            return;
        }

        let cur_idx = match self.index_of(self.current) {
            Some(i) => i as i32,
            None if direction >= 0 => -1,
            None => 0,
        };

        for step in 1..=n {
            let next_idx = (((cur_idx + direction * step) % n + n) % n) as usize;
            let target = self.regions[next_idx];
            if ctx.available(target) {
                self.deactivate_all(ctx);
                self.current = target;
                ctx.activate(target, direction);
                return;
            }
        }
    }

    /// Keeps the current focus when it is still available; otherwise
    /// activates the first currently available region. If none are
    /// available, clears focus.
    pub fn resolve_after_availability_change<C: FocusContext>(&mut self, ctx: &mut C) {
        self.resolve(ctx, false);
    }

    /// Checks whether the current target is still available under the target
    /// visibility state after a toggle. If not, activates the first region
    /// that will be available in the target state. If none are available,
    /// clears focus.
    pub fn resolve_after_visibility_change<C: FocusContext>(&mut self, ctx: &mut C) {
        self.resolve(ctx, true);
    }

    fn resolve<C: FocusContext>(&mut self, ctx: &mut C, for_visibility: bool) {
        let is_available = |ctx: &C, t: FocusTarget| {
            if for_visibility {
                ctx.available_target(t)
            } else {
                ctx.available(t)
            }
        };

        if self.current != FocusTarget::None
            && self.regions.contains(&self.current)
            && is_available(ctx, self.current)
        {
            return;
        }

        for i in 0..self.regions.len() {
            let target = self.regions[i];
            if !is_available(ctx, target) {
                continue;
            }
            self.deactivate_all(ctx);
            self.current = target;
            ctx.activate(target, 1);
            return;
        }

        self.clear_all(ctx);
    }

    fn deactivate_all<C: FocusContext>(&self, ctx: &mut C) {
        for &region in &self.regions {
            ctx.deactivate(region);
        }
    }

    fn index_of(&self, t: FocusTarget) -> Option<usize> {
        self.regions.iter().position(|&r| r == t)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Ctx {
        available: Vec<FocusTarget>,
        active: Option<FocusTarget>,
    }

    impl FocusContext for Ctx {
        fn available(&self, t: FocusTarget) -> bool {
            self.available.contains(&t)
        }
        fn activate(&mut self, t: FocusTarget, _direction: i32) {
            self.active = Some(t);
        }
        fn deactivate(&mut self, t: FocusTarget) {
            if self.active == Some(t) {
                self.active = None;
            }
        }
    }

    #[test]
    fn tab_skips_unavailable() {
        let mut fm = FocusManager::new(vec![
            FocusTarget::Overview,
            FocusTarget::MetricsGrid,
            FocusTarget::ConsoleLogs,
        ]);
        let mut ctx = Ctx {
            available: vec![FocusTarget::Overview, FocusTarget::ConsoleLogs],
            active: None,
        };
        fm.tab(&mut ctx, 1);
        assert_eq!(fm.current(), FocusTarget::Overview);
        fm.tab(&mut ctx, 1);
        assert_eq!(fm.current(), FocusTarget::ConsoleLogs);
        fm.tab(&mut ctx, 1);
        assert_eq!(fm.current(), FocusTarget::Overview);
        fm.tab(&mut ctx, -1);
        assert_eq!(fm.current(), FocusTarget::ConsoleLogs);
    }

    #[test]
    fn resolve_moves_focus_when_unavailable() {
        let mut fm = FocusManager::new(vec![FocusTarget::Overview, FocusTarget::MetricsGrid]);
        let mut ctx = Ctx {
            available: vec![FocusTarget::Overview, FocusTarget::MetricsGrid],
            active: None,
        };
        fm.set_target(&mut ctx, FocusTarget::MetricsGrid, 1);
        assert_eq!(fm.current(), FocusTarget::MetricsGrid);
        ctx.available = vec![FocusTarget::Overview];
        fm.resolve_after_availability_change(&mut ctx);
        assert_eq!(fm.current(), FocusTarget::Overview);
    }
}
