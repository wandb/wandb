//! Port of `core/internal/leet/focusmanager.go`.
//!
//! Go's `FocusRegionDef` hooks are closures capturing `*Run` (or test locals).
//! Storing self-referential closures inside the model is not expressible under
//! single-threaded ownership (CONCURRENCY.md §2.6 — no `Rc<RefCell>` self
//! capture), so the hooks are plain `fn` pointers over an explicit context `C`
//! (the eventual `Run`), and every `FocusManager` method takes `ctx: &mut C`.
//! This is the mechanical equivalent: Go's closures captured exactly one
//! receiver, which is now the explicit parameter.

/// FocusTarget identifies a focusable UI region.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FocusTarget {
    // PARITY: Go zero value is FocusTargetNone (focusmanager.go:7).
    #[default]
    None,
    RunsList,
    Overview,
    MetricsGrid,
    SystemMetrics,
    Media,
    ConsoleLogs,
}

/// FocusRegionDef defines a focusable region with availability and activation hooks.
pub struct FocusRegionDef<C> {
    pub target: FocusTarget,

    /// Available reports whether the region is currently focusable for normal
    /// navigation.
    // PARITY: nil-able in Go (`regionAvailable` nil-checks it) -> Option.
    pub available: Option<fn(&C) -> bool>,

    /// AvailableTarget reports whether the region should be considered focusable
    /// immediately after a visibility toggle. When `None`, `available` is used.
    pub available_target: Option<fn(&C) -> bool>,

    // PARITY: Activate/Deactivate are called unconditionally in Go (nil would
    // panic); required fields enforce that contract at compile time.
    pub activate: fn(&mut C, isize),
    pub deactivate: fn(&mut C),
}

/// FocusManager is the single source of truth for which UI component holds focus.
///
/// It tracks one FocusTarget at a time, supports Tab cycling through available
/// regions, and resolves focus after visibility changes. All focus state changes
/// flow through this manager.
pub struct FocusManager<C> {
    current: FocusTarget,
    regions: Vec<FocusRegionDef<C>>,
}

impl<C> Default for FocusManager<C> {
    fn default() -> Self {
        Self {
            current: FocusTarget::None,
            regions: Vec::new(),
        }
    }
}

impl<C> FocusManager<C> {
    /// Creates a FocusManager with the given region definitions.
    /// The regions slice defines the Tab-cycling order.
    pub fn new(regions: Vec<FocusRegionDef<C>>) -> Self {
        Self {
            current: FocusTarget::None,
            regions,
        }
    }

    /// Returns the currently focused target.
    pub fn current(&self) -> FocusTarget {
        self.current
    }

    /// Returns true if t is the currently focused target.
    pub fn is_target(&self, t: FocusTarget) -> bool {
        self.current == t
    }

    /// Updates the global focus target after a region has already applied its
    /// own local mouse-driven focus state.
    ///
    /// Unlike `set_target`, it deactivates only the other regions so the target
    /// region's freshly chosen local focus (for example a clicked chart cell) is
    /// preserved.
    pub fn adopt_target(&mut self, ctx: &mut C, t: FocusTarget) {
        if t == FocusTarget::None {
            self.clear_all(ctx);
            return;
        }

        let mut found = false;
        for region in &self.regions {
            if region.target == t {
                found = true;
                continue;
            }
            (region.deactivate)(ctx);
        }
        if !found {
            self.current = FocusTarget::None;
            return;
        }

        self.current = t;
    }

    /// Deactivates all regions and activates the given target.
    /// direction is +1 (forward/Tab) or -1 (backward/Shift+Tab) and is passed
    /// to the Activate callback so components like overview sidebar can focus
    /// their first or last section.
    pub fn set_target(&mut self, ctx: &mut C, t: FocusTarget, direction: isize) {
        self.deactivate_all(ctx);
        for region in &self.regions {
            if region.target == t {
                self.current = t;
                (region.activate)(ctx, direction);
                return;
            }
        }
        self.current = FocusTarget::None;
    }

    /// Deactivates all regions and sets focus to none.
    pub fn clear_all(&mut self, ctx: &mut C) {
        self.deactivate_all(ctx);
        self.current = FocusTarget::None;
    }

    /// Cycles focus to the next available region in the given direction.
    /// direction is +1 for Tab and -1 for Shift+Tab.
    pub fn tab(&mut self, ctx: &mut C, direction: isize) {
        let n = self.regions.len() as isize;
        if n == 0 {
            return;
        }

        let mut cur_idx = self.index_of(self.current);
        if cur_idx == -1 {
            cur_idx = if direction >= 0 { -1 } else { 0 };
        }

        for step in 1..=n {
            let next_idx = (((cur_idx + direction * step) % n + n) % n) as usize;
            if Self::region_available(ctx, &self.regions[next_idx]) {
                self.deactivate_all(ctx);
                self.current = self.regions[next_idx].target;
                (self.regions[next_idx].activate)(ctx, direction);
                return;
            }
        }
    }

    /// Tries the within_fn first (e.g., cycling overview sections).
    /// If within_fn returns true, the key was handled within the current region.
    /// Otherwise, it advances to the next region via `tab`.
    pub fn tab_within_or_advance(
        &mut self,
        ctx: &mut C,
        direction: isize,
        within_fn: Option<fn(&mut C, isize) -> bool>,
    ) {
        if let Some(within_fn) = within_fn
            && within_fn(ctx, direction)
        {
            return;
        }
        self.tab(ctx, direction);
    }

    /// Keeps the current focus when it is still available. Otherwise, it
    /// activates the first currently available region. If none are available,
    /// it clears focus.
    pub fn resolve_after_availability_change(&mut self, ctx: &mut C) {
        self.resolve(ctx, Self::region_available);
    }

    /// Checks whether the current target is still available under the target
    /// visibility state after a toggle. If not, it activates the first region
    /// that will be available in the target state. If none are available, it
    /// clears focus.
    pub fn resolve_after_visibility_change(&mut self, ctx: &mut C) {
        self.resolve(ctx, Self::region_available_for_resolve);
    }

    fn region_available(ctx: &C, r: &FocusRegionDef<C>) -> bool {
        // PARITY: Go's `r.Available != nil && r.Available()` (focusmanager.go:162).
        r.available.is_some_and(|available| available(ctx))
    }

    fn region_available_for_resolve(ctx: &C, r: &FocusRegionDef<C>) -> bool {
        if let Some(available_target) = r.available_target {
            return available_target(ctx);
        }
        Self::region_available(ctx, r)
    }

    fn resolve(&mut self, ctx: &mut C, is_available: fn(&C, &FocusRegionDef<C>) -> bool) {
        if self.current != FocusTarget::None {
            for region in &self.regions {
                if region.target != self.current {
                    continue;
                }
                if is_available(ctx, region) {
                    return;
                }
                break;
            }
        }

        for i in 0..self.regions.len() {
            if !is_available(ctx, &self.regions[i]) {
                continue;
            }
            self.deactivate_all(ctx);
            self.current = self.regions[i].target;
            (self.regions[i].activate)(ctx, 1);
            return;
        }

        self.clear_all(ctx);
    }

    fn deactivate_all(&self, ctx: &mut C) {
        for region in &self.regions {
            (region.deactivate)(ctx);
        }
    }

    fn index_of(&self, t: FocusTarget) -> isize {
        for (i, region) in self.regions.iter().enumerate() {
            if region.target == t {
                return i as isize;
            }
        }
        -1
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Context standing in for the Go test's captured locals
    /// (focusmanager_test.go:12-15).
    struct TestCtx {
        current_overview_visible: bool,
        target_overview_visible: bool,
        overview_active: bool,
        logs_active: bool,
    }

    // PARITY: transliteration of Go
    // TestFocusManagerResolveAfterVisibilityChangeUsesTargetAvailability.
    #[test]
    fn focus_manager_resolve_after_visibility_change_uses_target_availability() {
        let mut ctx = TestCtx {
            current_overview_visible: true,
            target_overview_visible: true,
            overview_active: false,
            logs_active: false,
        };

        let mut fm = FocusManager::new(vec![
            FocusRegionDef {
                target: FocusTarget::Overview,
                available: Some(|c: &TestCtx| c.current_overview_visible),
                available_target: Some(|c: &TestCtx| c.target_overview_visible),
                activate: |c, _| c.overview_active = true,
                deactivate: |c| c.overview_active = false,
            },
            FocusRegionDef {
                target: FocusTarget::ConsoleLogs,
                available: Some(|_| true),
                available_target: Some(|_| true),
                activate: |c, _| c.logs_active = true,
                deactivate: |c| c.logs_active = false,
            },
        ]);

        fm.set_target(&mut ctx, FocusTarget::Overview, 1);
        assert!(fm.is_target(FocusTarget::Overview));
        assert!(ctx.overview_active);

        ctx.target_overview_visible = false;
        fm.resolve_after_visibility_change(&mut ctx);

        assert!(fm.is_target(FocusTarget::ConsoleLogs));
        assert!(!ctx.overview_active);
        assert!(ctx.logs_active);
    }
}
