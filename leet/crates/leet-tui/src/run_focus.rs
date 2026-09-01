//! Port of `core/internal/leet/runfocus.go`.
//!
//! `buildRunFocusManager` constructs the FocusManager for the single-run view.
//!
//! The region order follows the spatial layout so Tab flows naturally:
//! left sidebar (overview) → main column top-to-bottom (metrics, media,
//! logs) → right sidebar (system metrics).

use crate::focus_manager::{FocusManager, FocusRegionDef, FocusTarget};
use crate::panel_grid::FocusType;
use crate::run::Run;

/// The single-run view's Tab-cycling region order.
///
/// PARITY: encodes the `FocusRegionDef` slice order of Go
/// `buildRunFocusManager` (runfocus.go:12-48). Tab flow and post-visibility
/// focus resolution depend on this exact sequence;
/// `Run::build_run_focus_manager` must construct its regions in this order.
pub const RUN_FOCUS_REGION_ORDER: [FocusTarget; 5] = [
    FocusTarget::Overview,
    FocusTarget::MetricsGrid,
    FocusTarget::Media,
    FocusTarget::ConsoleLogs,
    FocusTarget::SystemMetrics,
];

impl Run {
    /// buildRunFocusManager constructs the FocusManager for the single-run view.
    ///
    /// The region order follows the spatial layout so Tab flows naturally:
    /// left sidebar (overview) → main column top-to-bottom (metrics, media,
    /// logs) → right sidebar (system metrics).
    ///
    /// Called once from NewRun after all UI components are initialized.
    // PARITY: Go's hooks are closures capturing `*Run`; the port's hooks are
    // fn pointers over the explicit `&Run`/`&mut Run` ctx (focus_manager.rs
    // module doc), so this is an associated function rather than a method.
    pub(crate) fn build_run_focus_manager() -> FocusManager<Run> {
        FocusManager::new(vec![
            FocusRegionDef {
                target: FocusTarget::Overview,
                available: Some(Run::overview_focus_available),
                available_target: Some(Run::overview_focus_target_available),
                activate: Run::activate_overview_focus,
                deactivate: Run::deactivate_overview_focus,
            },
            FocusRegionDef {
                target: FocusTarget::MetricsGrid,
                available: Some(Run::metrics_grid_focus_available),
                available_target: Some(Run::metrics_grid_focus_target_available),
                activate: Run::activate_metrics_grid_focus,
                deactivate: Run::deactivate_metrics_grid_focus,
            },
            FocusRegionDef {
                target: FocusTarget::Media,
                available: Some(Run::media_focus_available),
                available_target: Some(Run::media_focus_target_available),
                activate: Run::activate_media_focus,
                deactivate: Run::deactivate_media_focus,
            },
            FocusRegionDef {
                target: FocusTarget::ConsoleLogs,
                available: Some(Run::logs_focus_available),
                available_target: Some(Run::logs_focus_target_available),
                activate: Run::activate_logs_focus,
                deactivate: Run::deactivate_logs_focus,
            },
            FocusRegionDef {
                target: FocusTarget::SystemMetrics,
                available: Some(Run::system_metrics_focus_available),
                available_target: Some(Run::system_metrics_focus_target_available),
                activate: Run::activate_system_metrics_focus,
                deactivate: Run::deactivate_system_metrics_focus,
            },
        ])
    }

    // ---- Availability ----

    fn overview_focus_available(&self) -> bool {
        let (first_sec, _) = self.left_sidebar.focusable_section_bounds();
        self.left_sidebar.anim_state.is_expanded() && first_sec != -1
    }

    fn overview_focus_target_available(&self) -> bool {
        let (first_sec, _) = self.left_sidebar.focusable_section_bounds();
        self.left_sidebar.anim_state.target_visible() && first_sec != -1
    }

    fn metrics_grid_focus_available(&self) -> bool {
        self.metrics_grid_anim_state.is_expanded() && self.metrics_grid.chart_count() > 0
    }

    fn metrics_grid_focus_target_available(&self) -> bool {
        self.metrics_grid_anim_state.target_visible() && self.metrics_grid.chart_count() > 0
    }

    fn system_metrics_focus_available(&self) -> bool {
        self.right_sidebar.is_visible() && self.right_sidebar.metrics_grid.chart_count() > 0
    }

    fn system_metrics_focus_target_available(&self) -> bool {
        self.right_sidebar.anim_state.target_visible()
            && self.right_sidebar.metrics_grid.chart_count() > 0
    }

    fn media_focus_available(&self) -> bool {
        self.media_pane.is_expanded() && self.media_pane.has_data()
    }

    fn media_focus_target_available(&self) -> bool {
        self.media_pane.anim_state.target_visible() && self.media_pane.has_data()
    }

    fn logs_focus_available(&self) -> bool {
        self.console_logs_pane.is_expanded()
    }

    fn logs_focus_target_available(&self) -> bool {
        self.console_logs_pane.anim_state.target_visible()
    }

    // ---- Activate ----

    fn activate_overview_focus(&mut self, direction: isize) {
        let (first_sec, last_sec) = self.left_sidebar.focusable_section_bounds();
        if direction >= 0 {
            self.left_sidebar.set_active_section(first_sec);
        } else {
            self.left_sidebar.set_active_section(last_sec);
        }
    }

    fn activate_metrics_grid_focus(&mut self, _direction: isize) {
        {
            let mut focus = self.focus.borrow_mut();
            focus.focus_type = FocusType::MainChart;
            if focus.row < 0 || focus.col < 0 {
                focus.row = 0;
                focus.col = 0;
            }
        }
        self.metrics_grid.navigate_focus(0, 0);
    }

    fn activate_system_metrics_focus(&mut self, _direction: isize) {
        {
            let mut focus = self.focus.borrow_mut();
            focus.focus_type = FocusType::SystemChart;
            if focus.row < 0 || focus.col < 0 {
                focus.row = 0;
                focus.col = 0;
            }
        }
        self.right_sidebar.metrics_grid.navigate_focus(0, 0);
    }

    fn activate_media_focus(&mut self, _direction: isize) {
        self.media_pane.set_active(true);
    }

    fn activate_logs_focus(&mut self, _direction: isize) {
        self.console_logs_pane.set_active(true);
    }

    // ---- Deactivate ----

    fn deactivate_overview_focus(&mut self) {
        self.left_sidebar.deactivate_all_sections();
    }

    fn deactivate_metrics_grid_focus(&mut self) {
        let mut focus = self.focus.borrow_mut();
        if focus.focus_type == FocusType::MainChart {
            focus.reset();
        }
    }

    fn deactivate_system_metrics_focus(&mut self) {
        let mut focus = self.focus.borrow_mut();
        if focus.focus_type == FocusType::SystemChart {
            focus.reset();
        }
    }

    fn deactivate_media_focus(&mut self) {
        self.media_pane.set_active(false);
    }

    fn deactivate_logs_focus(&mut self) {
        self.console_logs_pane.set_active(false);
    }

    // ---- Within-region cycling ----

    /// cycleRunOverviewSection tries to move within overview sections.
    /// Returns true if the navigation was handled (i.e. we're not at a boundary).
    pub(crate) fn cycle_run_overview_section(&mut self, direction: isize) -> bool {
        let (first_sec, last_sec) = self.left_sidebar.focusable_section_bounds();
        if !self.left_sidebar.anim_state.is_expanded() || first_sec == -1 {
            return false;
        }

        let at_boundary = (direction == 1 && self.left_sidebar.active_section == last_sec)
            || (direction == -1 && self.left_sidebar.active_section == first_sec);
        if at_boundary {
            return false;
        }

        self.left_sidebar.navigate_section(direction);
        true
    }
}

#[cfg(test)]
mod tests {
    use crate::focus_manager::{FocusManager, FocusRegionDef, FocusTarget};

    use super::*;

    struct NoCtx;

    /// No Go counterpart: Go pins the single-run Tab order implicitly in
    /// `buildRunFocusManager`'s slice literal (runfocus.go:12-48); this pins
    /// `RUN_FOCUS_REGION_ORDER` by cycling a FocusManager built from it.
    #[test]
    fn run_focus_region_order_tab_cycles_in_go_build_order() {
        let regions: Vec<FocusRegionDef<NoCtx>> = RUN_FOCUS_REGION_ORDER
            .iter()
            .map(|&target| FocusRegionDef {
                target,
                available: Some(|_| true),
                available_target: None,
                activate: |_, _| {},
                deactivate: |_| {},
            })
            .collect();
        let mut fm = FocusManager::new(regions);
        let mut ctx = NoCtx;

        // Forward Tab from no focus walks the spatial layout order and wraps.
        let mut seq = Vec::new();
        for _ in 0..6 {
            fm.tab(&mut ctx, 1);
            seq.push(fm.current());
        }
        assert_eq!(
            seq,
            vec![
                FocusTarget::Overview,
                FocusTarget::MetricsGrid,
                FocusTarget::Media,
                FocusTarget::ConsoleLogs,
                FocusTarget::SystemMetrics,
                FocusTarget::Overview,
            ]
        );

        // Shift+Tab wraps backwards from the first region to the last.
        fm.tab(&mut ctx, -1);
        assert!(fm.is_target(FocusTarget::SystemMetrics));
    }
}
