//! A collapsible right sidebar displaying system metrics.

use std::time::Instant;

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::Style;

use crate::animation::AnimatedValue;
use crate::filter::{FilterKey, FilterMatchMode};
use crate::flexlayout::{sidebar_content_width, sidebar_width_for};
use crate::grid::GridDims;
use crate::msg::StatsMsg;
use crate::systemgrid::{SystemGridSettings, SystemMetricsGrid};
use crate::theme::{
    self, BOX_LIGHT_VERTICAL, COLOR_LAYOUT, CONTENT_PADDING, MIN_METRIC_CHART_HEIGHT,
    MIN_METRIC_CHART_WIDTH, SIDEBAR_BORDER_COLS, SIDEBAR_OVERHEAD,
};

const RIGHT_SIDEBAR_HEADER: &str = "System Metrics";
const RIGHT_SIDEBAR_HEADER_LINES: u16 = 1;

/// X offset from the sidebar's left edge to the start of the grid content
/// (border + left padding).
const RIGHT_SIDEBAR_GRID_X_OFFSET: i32 = SIDEBAR_BORDER_COLS as i32 + CONTENT_PADDING as i32;

/// Height the grid is initially sized to before the first render pass.
const DEFAULT_SYSTEM_METRICS_GRID_HEIGHT: i32 = 40;

struct GridMouseTarget {
    adjusted_x: i32,
    adjusted_y: i32,
    row: i32,
    col: i32,
    dims: GridDims,
}

/// A collapsible right sidebar displaying system metrics.
pub struct RightSidebar {
    pub anim_state: AnimatedValue,
    pub metrics_grid: SystemMetricsGrid,
    /// User-set width as a fraction of the terminal width (mouse resizing);
    /// `None` uses the golden-ratio default.
    width_fraction: Option<f64>,
}

impl RightSidebar {
    pub fn new(visible: bool, settings: SystemGridSettings) -> Self {
        let init_w = MIN_METRIC_CHART_WIDTH as i32 * settings.cols.max(1);
        let init_h = MIN_METRIC_CHART_HEIGHT as i32 * settings.rows.max(1);
        Self {
            anim_state: AnimatedValue::new(visible, theme::SIDEBAR_MIN_WIDTH),
            metrics_grid: SystemMetricsGrid::new(init_w, init_h, settings),
            width_fraction: None,
        }
    }

    /// Sets the user width fraction (mouse resizing); `None` restores the
    /// default. Takes effect at the next `update_dimensions`.
    pub fn set_width_fraction(&mut self, fraction: Option<f64>) {
        self.width_fraction = fraction;
    }

    /// Updates the sidebar dimensions based on terminal width and the
    /// visibility of the left sidebar.
    pub fn update_dimensions(&mut self, terminal_width: i32, left_sidebar_visible: bool) {
        self.anim_state.set_expanded(sidebar_width_for(
            terminal_width,
            left_sidebar_visible,
            self.width_fraction,
        ));

        let grid_width = sidebar_content_width(self.anim_state.value());
        if grid_width > 0 {
            self.metrics_grid
                .resize(grid_width, DEFAULT_SYSTEM_METRICS_GRID_HEIGHT);
        }
    }

    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    pub fn width(&self) -> i32 {
        self.anim_state.value()
    }

    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }

    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }

    /// Advances the sidebar animation. Returns true when it completed.
    pub fn update(&mut self, now: Instant) -> bool {
        self.anim_state.update(now)
    }

    pub fn process_stats(&mut self, msg: &StatsMsg) {
        self.metrics_grid.process_stats(msg);
    }

    // ---- Mouse handling (sidebar-local coordinates) ----

    fn grid_mouse_target(&self, x: i32, y: i32) -> Option<GridMouseTarget> {
        if !self.anim_state.is_visible() {
            return None;
        }

        let adjusted_x = x - RIGHT_SIDEBAR_GRID_X_OFFSET;
        let adjusted_y = y - RIGHT_SIDEBAR_HEADER_LINES as i32;
        if adjusted_x < 0 || adjusted_y < 0 {
            return None;
        }

        let dims = self.metrics_grid.calculate_chart_dimensions();
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return None;
        }
        Some(GridMouseTarget {
            adjusted_x,
            adjusted_y,
            row: adjusted_y / dims.cell_h_with_padding,
            col: adjusted_x / dims.cell_w_with_padding,
            dims,
        })
    }

    /// Handles mouse clicks in the sidebar; returns true if focus changed.
    pub fn handle_mouse_click(&mut self, x: i32, y: i32) -> bool {
        match self.grid_mouse_target(x, y) {
            Some(t) => self.metrics_grid.handle_mouse_click(t.row, t.col),
            None => false,
        }
    }

    /// Zooms the chart under the mouse cursor.
    pub fn handle_wheel(&mut self, x: i32, y: i32, wheel_up: bool) {
        if let Some(t) = self.grid_mouse_target(x, y) {
            self.metrics_grid
                .handle_wheel(t.adjusted_x, t.row, t.col, t.dims, wheel_up);
        }
    }

    /// Begins chart inspection under the mouse cursor.
    pub fn start_inspection(&mut self, x: i32, y: i32, synced: bool) {
        if let Some(t) = self.grid_mouse_target(x, y) {
            self.metrics_grid.start_inspection(
                t.adjusted_x,
                t.adjusted_y,
                t.row,
                t.col,
                t.dims,
                synced,
            );
        }
    }

    /// Moves the inspection cursor.
    pub fn update_inspection(&mut self, x: i32, y: i32) {
        if let Some(t) = self.grid_mouse_target(x, y) {
            self.metrics_grid
                .update_inspection(t.adjusted_x, t.adjusted_y, t.row, t.col, t.dims);
        }
    }

    pub fn end_inspection(&mut self) {
        self.metrics_grid.end_inspection();
    }

    // ---- Focus / filter delegation ----

    pub fn focused_chart_title(&self) -> &str {
        self.metrics_grid.focused_chart_title()
    }

    pub fn focused_chart_view_mode_label(&self) -> String {
        self.metrics_grid.focused_chart_view_mode_label()
    }

    pub fn clear_focus(&mut self) {
        self.metrics_grid.clear_focus();
    }

    pub fn handle_filter_key(&mut self, key: FilterKey) {
        self.metrics_grid.handle_filter_key(key);
    }

    pub fn is_filter_mode(&self) -> bool {
        self.metrics_grid.is_filter_mode()
    }

    pub fn is_filtering(&self) -> bool {
        self.metrics_grid.is_filtering()
    }

    pub fn filter_mode(&self) -> FilterMatchMode {
        self.metrics_grid.filter_mode()
    }

    pub fn filter_query(&self) -> &str {
        self.metrics_grid.filter_query()
    }

    // ---- Rendering ----

    /// Renders the sidebar into `area`, whose width should be the current
    /// animated width.
    pub fn render(&mut self, area: Rect, buf: &mut Buffer) {
        let width = self.anim_state.value();
        if area.height == 0 || width <= SIDEBAR_OVERHEAD {
            return;
        }
        let width = (width as u16).min(area.width);

        // Left border column.
        let border_style = Style::new().fg(COLOR_LAYOUT.color());
        for y in area.top()..area.bottom() {
            buf[(area.x, y)]
                .set_char(BOX_LIGHT_VERTICAL)
                .set_style(border_style);
        }

        let content_w = sidebar_content_width(width as i32);
        let grid_height = area.height as i32 - RIGHT_SIDEBAR_HEADER_LINES as i32;
        if content_w <= 0 || grid_height <= 0 {
            return;
        }

        let content_x = area.x + RIGHT_SIDEBAR_GRID_X_OFFSET as u16;
        self.render_header(
            Rect {
                x: content_x,
                y: area.y,
                width: content_w as u16,
                height: RIGHT_SIDEBAR_HEADER_LINES,
            },
            buf,
        );

        self.metrics_grid.resize(content_w, grid_height);
        self.metrics_grid.render(
            Rect {
                x: content_x,
                y: area.y + RIGHT_SIDEBAR_HEADER_LINES,
                width: content_w as u16,
                height: grid_height as u16,
            },
            buf,
        );
    }

    fn render_header(&self, area: Rect, buf: &mut Buffer) {
        let (x, _) = buf.set_stringn(
            area.x,
            area.y,
            RIGHT_SIDEBAR_HEADER,
            area.width as usize,
            theme::header_style(),
        );
        if let Some((start, end, filtered, total)) = self.metrics_grid.pagination_info() {
            let nav = if filtered != total {
                format!(" [{start}-{end} of {filtered} filtered from {total} total]")
            } else {
                format!(" [{start}-{end} of {filtered}]")
            };
            buf.set_stringn(
                x,
                area.y,
                &nav,
                (area.right().saturating_sub(x)) as usize,
                theme::nav_info_style(),
            );
        }
    }
}
