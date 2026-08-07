//! Port of `core/internal/leet/systemmetricsview.go` — the shared header /
//! body / navigation-info renderers used by both the workspace system
//! metrics pane and the standalone SYMON view.
//!
//! Go's free functions take a nilable `*SystemMetricsGrid`; the port takes
//! `Option<&SystemMetricsGrid>` (`Option<&mut _>` where Go's callee resizes
//! the grid). All functions additionally take `dark` to resolve adaptive
//! colors (Go reads the `darkBackground` package global at render time; see
//! layout.rs module doc).

use ratatui::text::Text;

use crate::layout::{
    LEFT, TOP, block_width, header_style, join_horizontal, nav_info_style, place, text_from_str,
};
use crate::panel_grid::items_per_page;
use crate::run_overview_sidebar::truncate_value;
use crate::system_metrics_grid::SystemMetricsGrid;

/// renderSystemMetricsHeader renders the shared header used by both the
/// workspace system metrics pane and the standalone SYMON view.
///
/// The left side shows the title and optional run label. The right side shows
/// the current chart pagination state.
pub fn render_system_metrics_header(
    content_width: isize,
    title_text: &str,
    run_label: &str,
    grid: Option<&SystemMetricsGrid>,
    dark: bool,
) -> Text<'static> {
    let title = header_style(dark).render(title_text);
    let nav_info = nav_info_style(dark).render(&build_system_metrics_navigation_info(grid));

    let mut left = title.clone();
    if !run_label.is_empty() {
        let sep = " • ";
        // PARITY: Go subtracts len(sep) — the BYTE length (5), not the
        // display width (3) — so the run label gets two fewer columns than
        // strictly necessary.
        let max_run_width = content_width
            - block_width(&title) as isize
            - block_width(&nav_info) as isize
            - sep.len() as isize;
        if max_run_width > 0 {
            left = join_horizontal(
                LEFT,
                vec![
                    title,
                    nav_info_style(dark).render(&format!(
                        "{sep}{}",
                        truncate_value(run_label, max_run_width)
                    )),
                ],
            );
        }
    }

    let filler_width =
        content_width - block_width(&left) as isize - block_width(&nav_info) as isize;
    let filler = text_from_str(&" ".repeat(filler_width.max(0) as usize));
    join_horizontal(LEFT, vec![left, filler, nav_info])
}

/// renderSystemMetricsBody renders either an informative empty state or the
/// system metrics chart grid itself.
pub fn render_system_metrics_body(
    content_width: isize,
    grid_height: isize,
    grid: Option<&mut SystemMetricsGrid>,
    empty_hint: &str,
    no_match_hint: &str,
    dark: bool,
) -> Text<'static> {
    let mut empty_hint = empty_hint;
    if empty_hint.is_empty() {
        empty_hint = "No system metrics.";
    }
    let mut no_match_hint = no_match_hint;
    if no_match_hint.is_empty() {
        no_match_hint = "No matching system metrics.";
    }

    let no_charts = match &grid {
        None => true,
        Some(g) => g.chart_count() == 0,
    };
    if no_charts {
        return place(
            content_width as i64,
            grid_height as i64,
            LEFT,
            TOP,
            nav_info_style(dark).render(empty_hint),
        );
    }
    let grid = grid.expect("checked above");

    if !grid.filter_query().is_empty() && grid.filtered_chart_count() == 0 {
        return place(
            content_width as i64,
            grid_height as i64,
            LEFT,
            TOP,
            nav_info_style(dark).render(no_match_hint),
        );
    }

    grid.resize(content_width, grid_height);
    grid.view(dark)
}

/// buildSystemMetricsNavigationInfo reports the visible chart range for the
/// current page.
pub fn build_system_metrics_navigation_info(grid: Option<&SystemMetricsGrid>) -> String {
    let Some(grid) = grid else {
        return String::new();
    };
    let total_count = grid.chart_count();
    let filtered_count = grid.filtered_chart_count();
    if total_count == 0 || filtered_count == 0 {
        return String::new();
    }

    let size = grid.effective_grid_size();
    let items_per_page = items_per_page(size);
    if items_per_page <= 0 {
        return String::new();
    }
    let (mut start, end) = grid
        .nav
        .page_bounds(filtered_count as isize, items_per_page);
    start += 1; // Convert to 1-indexed.

    if filtered_count != total_count {
        return format!(" [{start}-{end} of {filtered_count} filtered from {total_count} total]");
    }

    format!(" [{start}-{end} of {filtered_count}]")
}
