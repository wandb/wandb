//! Collapsible, animated pane rendering system metrics in the workspace view.

use std::time::Instant;

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;

use crate::animation::AnimatedValue;
use crate::systemgrid::SystemMetricsGrid;
use crate::textwrap::truncate_value;
use crate::theme::{
    self, CHART_BORDER_SIZE, CHART_TITLE_HEIGHT, CONTENT_PADDING, CONTENT_PADDING_COLS,
    MIN_METRIC_CHART_HEIGHT,
};

pub const SYSTEM_METRICS_PANE_HEADER_LINES: i32 = 1;
pub const SYSTEM_METRICS_PANE_MIN_HEIGHT: i32 = SYSTEM_METRICS_PANE_HEADER_LINES
    + MIN_METRIC_CHART_HEIGHT as i32
    + CHART_BORDER_SIZE as i32
    + CHART_TITLE_HEIGHT;

pub const WORKSPACE_SYSTEM_METRICS_PANE_HEADER: &str = "System Metrics";

pub struct SystemMetricsPane {
    pub anim_state: AnimatedValue,
}

impl SystemMetricsPane {
    pub fn new(anim_state: AnimatedValue) -> Self {
        Self { anim_state }
    }

    pub fn height(&self) -> i32 {
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

    pub fn update(&mut self, now: Instant) -> bool {
        self.anim_state.update(now)
    }

    pub fn set_expanded_height(&mut self, height: i32) {
        self.anim_state
            .set_expanded(height.max(SYSTEM_METRICS_PANE_MIN_HEIGHT));
    }

    /// Renders the system metrics pane into `area`.
    pub fn render(
        &self,
        area: Rect,
        buf: &mut Buffer,
        run_label: &str,
        grid: Option<&mut SystemMetricsGrid>,
        hint: &str,
    ) {
        let width = area.width as i32;
        let height = self.height().min(area.height as i32);
        if width <= CONTENT_PADDING_COLS as i32 || height < SYSTEM_METRICS_PANE_MIN_HEIGHT {
            return;
        }

        let inner = Rect {
            x: area.x + CONTENT_PADDING,
            y: area.y,
            width: (width - CONTENT_PADDING_COLS as i32) as u16,
            height: height as u16,
        };

        render_system_metrics_header(
            Rect { height: 1, ..inner },
            buf,
            WORKSPACE_SYSTEM_METRICS_PANE_HEADER,
            run_label,
            grid.as_deref(),
        );

        let grid_h = (height - SYSTEM_METRICS_PANE_HEADER_LINES).max(0);
        if grid_h > 0 {
            let body = Rect {
                y: inner.y + SYSTEM_METRICS_PANE_HEADER_LINES as u16,
                height: grid_h as u16,
                ..inner
            };
            render_system_metrics_body(body, buf, grid, hint, "No matching system metrics.");
        }
    }
}

/// Renders the shared header used by both the workspace system metrics pane
/// and the standalone SYMON view: title and optional run label on the left,
/// chart pagination state on the right.
pub fn render_system_metrics_header(
    area: Rect,
    buf: &mut Buffer,
    title_text: &str,
    run_label: &str,
    grid: Option<&SystemMetricsGrid>,
) {
    let content_width = area.width as i32;
    let nav_info = build_system_metrics_navigation_info(grid);

    let title_w = title_text.chars().count() as i32;
    let nav_w = nav_info.chars().count() as i32;

    let (x, _) = buf.set_stringn(
        area.x,
        area.y,
        title_text,
        content_width.max(0) as usize,
        theme::header_style(),
    );
    let mut left_end = x;

    if !run_label.is_empty() {
        let sep = " • ";
        let max_run_width = content_width - title_w - nav_w - sep.chars().count() as i32;
        if max_run_width > 0 {
            let label = format!("{sep}{}", truncate_value(run_label, max_run_width as usize));
            let (x, _) = buf.set_stringn(
                left_end,
                area.y,
                &label,
                (content_width - title_w).max(0) as usize,
                theme::nav_info_style(),
            );
            left_end = x;
        }
    }

    if nav_w > 0 {
        let nav_x = area.x + (content_width - nav_w).max(0) as u16;
        if nav_x >= left_end {
            buf.set_stringn(
                nav_x,
                area.y,
                &nav_info,
                nav_w as usize,
                theme::nav_info_style(),
            );
        }
    }
}

/// Renders either an informative empty state or the system metrics grid.
pub fn render_system_metrics_body(
    area: Rect,
    buf: &mut Buffer,
    grid: Option<&mut SystemMetricsGrid>,
    empty_hint: &str,
    no_match_hint: &str,
) {
    let empty_hint = if empty_hint.is_empty() {
        "No system metrics."
    } else {
        empty_hint
    };
    let no_match_hint = if no_match_hint.is_empty() {
        "No matching system metrics."
    } else {
        no_match_hint
    };

    let hint_line = |buf: &mut Buffer, text: &str| {
        buf.set_stringn(
            area.x,
            area.y,
            text,
            area.width as usize,
            theme::nav_info_style(),
        );
    };

    let Some(grid) = grid else {
        hint_line(buf, empty_hint);
        return;
    };
    if grid.chart_count() == 0 {
        hint_line(buf, empty_hint);
        return;
    }
    if !grid.filter_query().is_empty() && grid.filtered_chart_count() == 0 {
        hint_line(buf, no_match_hint);
        return;
    }

    grid.resize(area.width as i32, area.height as i32);
    grid.render(area, buf);
}

/// Reports the visible chart range for the current page.
pub fn build_system_metrics_navigation_info(grid: Option<&SystemMetricsGrid>) -> String {
    let Some((start, end, filtered, total)) = grid.and_then(|g| g.pagination_info()) else {
        return String::new();
    };
    if filtered != total {
        format!(" [{start}-{end} of {filtered} filtered from {total} total]")
    } else {
        format!(" [{start}-{end} of {filtered}]")
    }
}
