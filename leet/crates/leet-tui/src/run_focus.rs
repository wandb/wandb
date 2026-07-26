//! Port of `core/internal/leet/runfocus.go`.
//!
//! `buildRunFocusManager` constructs the FocusManager for the single-run view.
//!
//! The region order follows the spatial layout so Tab flows naturally:
//! left sidebar (overview) → main column top-to-bottom (metrics, media,
//! logs) → right sidebar (system metrics).

use crate::focus_manager::FocusTarget;

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

// PHASE-5: the remainder of runfocus.go is `*Run` methods and lands as
// `impl Run` blocks in this module once `run.rs` (Run model) and its
// components exist. Deferred items:
//
// - `Run::build_run_focus_manager` (runfocus.go:11-49): returns
//   `FocusManager<Run>` built from `RUN_FOCUS_REGION_ORDER` wired to the
//   hooks below; called once from `Run::new` after all UI components are
//   initialized.
// - Availability hooks (runfocus.go:53-94):
//   `overview_focus_available` / `overview_focus_target_available`,
//   `metrics_grid_focus_available` / `metrics_grid_focus_target_available`,
//   `system_metrics_focus_available` / `system_metrics_focus_target_available`,
//   `media_focus_available` / `media_focus_target_available`,
//   `logs_focus_available` / `logs_focus_target_available`.
//   Need: `RunOverviewSidebar` (`focusable_section_bounds`, `anim_state`),
//   `MetricsGrid::chart_count`, `RightSidebar`, `MediaPane`,
//   `ConsoleLogsPane`, `animation::AnimationState`
//   (`is_expanded` / `target_visible`).
// - Activate hooks (runfocus.go:98-131):
//   `activate_overview_focus` (direction >= 0 → first section, else last),
//   `activate_metrics_grid_focus`, `activate_system_metrics_focus`,
//   `activate_media_focus`, `activate_logs_focus`.
//   Need: `panel_grid::{Focus, FocusType}` (`FocusMainChart` /
//   `FocusSystemChart`) and `MetricsGrid::navigate_focus`. No local
//   stand-in for `FocusType` is defined here — it belongs to
//   `panel_grid.rs` (Phase 4) and a duplicate would drift.
// - Deactivate hooks (runfocus.go:135-157):
//   `deactivate_overview_focus`, `deactivate_metrics_grid_focus`,
//   `deactivate_system_metrics_focus`, `deactivate_media_focus`,
//   `deactivate_logs_focus`.
// - `Run::cycle_run_overview_section` (runfocus.go:163-177): the
//   `tab_within_or_advance` within-fn; returns false at section boundaries
//   so Tab advances to the next region.

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
