//! Port of `core/internal/leet/workspacesystemmetricspane.go` — a
//! collapsible, animated pane intended for rendering system metrics in the
//! workspace view.
//!
//! The pane owns only its [`AnimatedValue`]; the [`SystemMetricsGrid`] is
//! owned by the workspace and passed into [`SystemMetricsPane::view`] each
//! frame, exactly like Go's `View(width, runLabel, grid, hint)`.

use std::time::Instant;

use ratatui::text::Text;

use leet_charts::styles::{
    CHART_BORDER_SIZE, CHART_TITLE_HEIGHT, CONTENT_PADDING, CONTENT_PADDING_COLS,
    MIN_METRIC_CHART_HEIGHT,
};

use crate::animation::AnimatedValue;
use crate::layout::{GoStyle, LEFT, TOP, join_vertical, place, text_from_str};
use crate::system_metrics_grid::SystemMetricsGrid;
use crate::system_metrics_view::{render_system_metrics_body, render_system_metrics_header};

pub(crate) const SYSTEM_METRICS_PANE_HEADER_LINES: isize = 1;
pub(crate) const SYSTEM_METRICS_PANE_MIN_HEIGHT: isize = SYSTEM_METRICS_PANE_HEADER_LINES
    + MIN_METRIC_CHART_HEIGHT as isize
    + CHART_BORDER_SIZE as isize
    + CHART_TITLE_HEIGHT as isize;

pub const WORKSPACE_SYSTEM_METRICS_PANE_HEADER: &str = "System Metrics";

/// Go package var `systemMetricsPaneStyle` (workspacesystemmetricspane.go:17-20).
fn system_metrics_pane_style() -> GoStyle {
    GoStyle::new().padding(&[0, CONTENT_PADDING])
}

/// SystemMetricsPane is a collapsible, animated pane intended for rendering
/// system metrics in the workspace view.
// PARITY: Go holds `animState *AnimatedValue`; the pane is its single holder
// (workspace.go:167), so the port owns it. workspace.go reaches
// `w.systemMetricsPane.animState` directly (package scope) — pub(crate).
pub struct SystemMetricsPane {
    pub(crate) anim_state: AnimatedValue,
}

impl SystemMetricsPane {
    /// Port of Go `NewSystemMetricsPane`.
    pub fn new(anim_state: AnimatedValue) -> SystemMetricsPane {
        SystemMetricsPane { anim_state }
    }

    pub fn height(&self) -> isize {
        self.anim_state.value()
    }

    pub fn is_expanded(&self) -> bool {
        self.anim_state.is_expanded()
    }

    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }

    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }

    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    pub fn update(&mut self, t: Instant) -> bool {
        self.anim_state.update(t)
    }

    pub fn set_expanded_height(&mut self, height: isize) {
        self.anim_state
            .set_expanded(height.max(SYSTEM_METRICS_PANE_MIN_HEIGHT));
    }

    /// View renders the system metrics pane.
    pub fn view(
        &self,
        width: isize,
        run_label: &str,
        grid: Option<&mut SystemMetricsGrid>,
        hint: &str,
        dark: bool,
    ) -> Text<'static> {
        let height = self.height();
        if width <= CONTENT_PADDING_COLS as isize || height < SYSTEM_METRICS_PANE_MIN_HEIGHT {
            return text_from_str("");
        }

        let inner_w = (width - CONTENT_PADDING_COLS as isize).max(0);
        let inner_h = height.max(0);
        let grid_h = (inner_h - SYSTEM_METRICS_PANE_HEADER_LINES).max(0);

        let header = render_system_metrics_header(
            inner_w,
            WORKSPACE_SYSTEM_METRICS_PANE_HEADER,
            run_label,
            grid.as_deref(),
            dark,
        );
        let body = if grid_h > 0 {
            join_vertical(
                LEFT,
                vec![
                    header,
                    render_system_metrics_body(
                        inner_w,
                        grid_h,
                        grid,
                        hint,
                        "No matching system metrics.",
                        dark,
                    ),
                ],
            )
        } else {
            header
        };

        let body = place(inner_w as i64, inner_h as i64, LEFT, TOP, body);
        let padded = system_metrics_pane_style().render_text(body);

        place(width as i64, height as i64, LEFT, TOP, padded)
    }
}

// No Go test file exists for workspacesystemmetricspane.go; the cases below
// pin behavior directly from the spec (workspacesystemmetricspane.go).
#[cfg(test)]
mod tests {
    use leet_charts::styles::default_dark_background;

    use super::*;

    #[test]
    fn set_expanded_height_clamps_to_min_height() {
        // Stably expanded: SetExpanded snaps to the new size immediately.
        let mut pane = SystemMetricsPane::new(AnimatedValue::new(true, 20));

        pane.set_expanded_height(3);
        // systemMetricsPaneMinHeight = 1 header + 4 chart + 2 border + 1 title.
        assert_eq!(pane.height(), SYSTEM_METRICS_PANE_MIN_HEIGHT);
        assert_eq!(SYSTEM_METRICS_PANE_MIN_HEIGHT, 8);

        pane.set_expanded_height(30);
        assert_eq!(pane.height(), 30);
    }

    #[test]
    fn view_is_empty_when_collapsed_below_min_height() {
        let pane = SystemMetricsPane::new(AnimatedValue::new(false, 20));
        let view = pane.view(80, "run", None, "", default_dark_background());
        assert_eq!(crate::layout::text_to_string(&view), "");
    }

    #[test]
    fn view_is_empty_when_width_within_padding() {
        let pane = SystemMetricsPane::new(AnimatedValue::new(true, 20));
        // width <= ContentPaddingCols (2) renders nothing.
        let view = pane.view(
            CONTENT_PADDING_COLS as isize,
            "",
            None,
            "",
            default_dark_background(),
        );
        assert_eq!(crate::layout::text_to_string(&view), "");
    }
}
