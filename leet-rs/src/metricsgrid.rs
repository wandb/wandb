//! The main run metrics chart grid.
//!
//! Owns charts (create, index, update), maintains filter and pagination
//! state, and computes/renders the current page/grid layout.

use std::collections::{HashMap, HashSet};

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::widgets::{Block, BorderType, Widget};

use crate::chart::epoch::{EpochLineChart, ZoomDirection, truncate_title};
use crate::filter::{Filter, FilterKey, FilterMatchMode};
use crate::grid::{
    Focus, FocusType, GridDims, GridNavigator, GridSize, GridSpec, clamp_i32, compute_grid_dims,
    effective_grid_size, items_per_page,
};
use crate::msg::HistoryMsg;
use crate::theme::{
    self, Adaptive, CHART_HEADER_HEIGHT, COLOR_MODE_PER_PLOT, CONTENT_PADDING,
    CONTENT_PADDING_COLS, DEFAULT_COLOR_SCHEME, MIN_CHART_HEIGHT, MIN_CHART_WIDTH,
};

const METRICS_HEADER: &str = "Metrics";

/// Provides stable colors for series keys (e.g. workspace run paths).
pub type SeriesColorProvider = Box<dyn Fn(&str) -> Adaptive>;

/// Renders a styled "Metrics" header with a hint message, used when the
/// grid has no charts to show.
pub fn render_metrics_empty_state(area: Rect, buf: &mut Buffer, hint: &str) {
    if area.width == 0 || area.height == 0 {
        return;
    }
    let x = area.x + theme::CONTENT_PADDING;
    let w = area.width.saturating_sub(theme::CONTENT_PADDING_COLS) as usize;
    buf.set_stringn(x, area.y, "Metrics", w, theme::header_style());
    if area.height > 2 {
        buf.set_stringn(
            x,
            area.y + 2,
            hint,
            w,
            Style::new().fg(theme::COLOR_SUBTLE.color()),
        );
    }
}

pub struct MetricsGrid {
    /// Configured grid shape (updated by the app when config changes).
    grid_rows: i32,
    grid_cols: i32,

    /// Viewport dimensions.
    width: i32,
    height: i32,

    /// Pagination state.
    nav: GridNavigator,

    /// All charts, kept sorted by title.
    charts: Vec<EpochLineChart>,
    /// Title -> index into `charts`.
    by_title: HashMap<String, usize>,
    /// Subset matching the filter (mirrors all when filter empty).
    filtered: Vec<usize>,

    /// Chart indices visible on the current page grid.
    current_page: Vec<Vec<Option<usize>>>,

    /// Titles of charts drawn on the last visible page, for parking.
    last_drawn: HashSet<String>,

    /// Chart focus (row/col meaningful relative to `current_page`).
    pub focus: Focus,

    /// Filter state.
    filter: Filter,

    /// Stable color assignment.
    color_of_title: HashMap<String, Adaptive>,
    next_color_idx: usize,

    /// Palette for main metrics charts.
    palette: Vec<Adaptive>,
    /// Palette for per-plot mode in single-run view.
    per_plot_palette: Vec<Adaptive>,

    /// When `per_plot`, single-series charts are colored per chart title.
    single_series_color_mode: String,

    /// Optional per-series color override keyed by series name (for example
    /// workspace run paths).
    series_color_for_key: Option<SeriesColorProvider>,

    /// Synchronized inspection session state (active between press/release).
    sync_inspect_active: bool,
}

impl MetricsGrid {
    pub fn new(
        grid_rows: i32,
        grid_cols: i32,
        color_scheme: &str,
        per_plot_color_scheme: &str,
    ) -> Self {
        Self {
            grid_rows,
            grid_cols,
            width: 0,
            height: 0,
            nav: GridNavigator::default(),
            charts: Vec::new(),
            by_title: HashMap::new(),
            filtered: Vec::new(),
            current_page: Vec::new(),
            last_drawn: HashSet::new(),
            focus: Focus::new(),
            filter: Filter::new(),
            color_of_title: HashMap::new(),
            next_color_idx: 0,
            palette: theme::graph_colors(color_scheme).to_vec(),
            per_plot_palette: theme::graph_colors(per_plot_color_scheme).to_vec(),
            single_series_color_mode: theme::COLOR_MODE_PER_SERIES.to_string(),
            series_color_for_key: None,
            sync_inspect_active: false,
        }
    }

    /// Updates the configured grid shape (rows, cols).
    pub fn set_grid_shape(&mut self, rows: i32, cols: i32) {
        self.grid_rows = rows;
        self.grid_cols = cols;
    }

    /// Controls coloring for single-series charts (single-run view only).
    pub fn set_single_series_color_mode(&mut self, mode: &str) {
        self.single_series_color_mode = if mode == COLOR_MODE_PER_PLOT {
            mode
        } else {
            theme::COLOR_MODE_PER_SERIES
        }
        .to_string();
    }

    /// Installs an optional stable color provider for series keys.
    ///
    /// Set this before processing data so newly created series render with
    /// the intended colors from their first frame.
    pub fn set_series_color_provider(&mut self, provider: Option<SeriesColorProvider>) {
        self.series_color_for_key = provider;
    }

    /// The total number of metrics charts.
    pub fn chart_count(&self) -> usize {
        self.charts.len()
    }

    fn focused_chart_idx(&self) -> Option<usize> {
        if self.focus.ty != FocusType::MainChart || self.focus.row < 0 || self.focus.col < 0 {
            return None;
        }
        *self
            .current_page
            .get(self.focus.row as usize)?
            .get(self.focus.col as usize)?
    }

    pub fn focused_chart(&self) -> Option<&EpochLineChart> {
        self.focused_chart_idx().map(|i| &self.charts[i])
    }

    pub fn focused_chart_scale_label(&self) -> &'static str {
        self.focused_chart().map_or("", |c| c.scale_label())
    }

    pub fn toggle_focused_chart_log_y(&mut self) -> bool {
        let Some(idx) = self.focused_chart_idx() else {
            return false;
        };
        if !self.charts[idx].toggle_y_scale() {
            return false;
        }
        self.charts[idx].draw_if_needed();
        true
    }

    fn grid_spec(&self) -> GridSpec {
        GridSpec {
            rows: self.grid_rows,
            cols: self.grid_cols,
            min_cell_w: MIN_CHART_WIDTH as i32,
            min_cell_h: MIN_CHART_HEIGHT as i32,
            header_lines: CHART_HEADER_HEIGHT,
        }
    }

    /// Computes chart dimensions for the given window size.
    pub fn calculate_chart_dimensions(&self, window_width: i32, window_height: i32) -> GridDims {
        // Subtract the content padding that render() adds around the grid.
        let inner_w = (window_width - CONTENT_PADDING_COLS as i32).max(0);
        compute_grid_dims(inner_w, window_height, self.grid_spec())
    }

    /// The grid size that can fit in the current viewport.
    fn effective_grid_size(&self) -> GridSize {
        effective_grid_size(self.width, self.height, self.grid_spec())
    }

    /// Ingests a batch of history samples (single step across metrics),
    /// creating charts as needed, resorting, reapplying filters, and
    /// reloading the page. Preserves focus on the previously focused chart
    /// when possible. Returns true if there was anything to draw.
    pub fn process_history(&mut self, msg: &HistoryMsg) -> bool {
        if msg.metrics.is_empty() {
            return false;
        }

        // Remember focused chart title (only if valid).
        let prev_title = self.save_focus_title();

        let series_style: Option<Style> = match (&self.series_color_for_key, msg.run_path.as_str())
        {
            (Some(provider), path) if !path.is_empty() => {
                Some(Style::new().fg(provider(path).color()))
            }
            _ => None,
        };

        let mut needs_sort = false;

        for (name, data) in &msg.metrics {
            let idx = match self.by_title.get(name) {
                Some(&i) => i,
                None => {
                    let mut chart = EpochLineChart::new(name);
                    chart.set_palette(&self.palette);
                    self.charts.push(chart);
                    let i = self.charts.len() - 1;
                    self.by_title.insert(name.clone(), i);
                    needs_sort = true;
                    i
                }
            };
            self.charts[idx].add_data(&msg.run_path, data);
            if let Some(style) = series_style {
                self.charts[idx].set_series_style(&msg.run_path, style);
            }
        }

        // Keep ordering, colors, maps and filtered set in sync.
        if needs_sort {
            self.sort_charts();
            self.apply_filter_internal();
        } else {
            // No new charts; keep pagination but refresh visible page.
            self.load_current_page();
        }

        // Restore focus by title (if previously valid and still visible).
        self.restore_focus(&prev_title);
        true
    }

    /// The count used for nav/pagination.
    fn effective_chart_count(&self) -> usize {
        if self.filter.query().is_empty() {
            self.charts.len()
        } else {
            self.filtered.len()
        }
    }

    /// A stable color for a given metric title.
    fn color_for(&mut self, title: &str) -> Adaptive {
        if let Some(&c) = self.color_of_title.get(title) {
            return c;
        }
        // Select palette based on color mode.
        let palette: &[Adaptive] = if self.single_series_color_mode == COLOR_MODE_PER_PLOT
            && !self.per_plot_palette.is_empty()
        {
            &self.per_plot_palette
        } else if !self.palette.is_empty() {
            &self.palette
        } else {
            theme::graph_colors(DEFAULT_COLOR_SCHEME)
        };
        let c = palette[self.next_color_idx % palette.len()];
        self.color_of_title.insert(title.to_string(), c);
        self.next_color_idx += 1;
        c
    }

    /// Sorts charts alphabetically, rebuilds indices, and (re)assigns colors.
    fn sort_charts(&mut self) {
        self.charts.sort_by(|a, b| a.title().cmp(b.title()));

        self.by_title.clear();
        for i in 0..self.charts.len() {
            let title = self.charts[i].title().to_string();

            // Stable color per title (no reshuffling when new charts arrive).
            let color = self.color_for(&title);
            if self.single_series_color_mode == COLOR_MODE_PER_PLOT {
                self.charts[i].set_graph_style(Style::new().fg(color.color()));
            }

            self.by_title.insert(title, i);
        }
    }

    /// Loads the chart indices for the current page into the grid.
    fn load_current_page(&mut self) {
        let size = self.effective_grid_size();

        // Rebuild grid structure.
        self.current_page = vec![vec![None; size.cols as usize]; size.rows as usize];

        let charts_to_show = if self.filter.query().is_empty() {
            (0..self.charts.len()).collect::<Vec<_>>()
        } else {
            self.filtered.clone()
        };

        let (start, end) = self
            .nav
            .page_bounds(charts_to_show.len(), items_per_page(size));

        let mut idx = start;
        'outer: for row in 0..size.rows as usize {
            for col in 0..size.cols as usize {
                if idx >= end {
                    break 'outer;
                }
                self.current_page[row][col] = Some(charts_to_show[idx]);
                idx += 1;
            }
        }
    }

    /// Ensures grid geometry matches the viewport, so rendering never uses
    /// pagination or canvases computed for a stale size.
    pub fn sync_dimensions(&mut self, content_width: i32, content_height: i32) {
        if self.width != content_width || self.height != content_height {
            self.update_dimensions(content_width, content_height);
        }
    }

    /// Updates chart sizes based on the content viewport.
    pub fn update_dimensions(&mut self, content_width: i32, content_height: i32) {
        self.width = content_width;
        self.height = content_height;

        // Keep pagination in sync with what fits now.
        let size = self.effective_grid_size();
        let chart_count = self.effective_chart_count();
        self.nav
            .update_total_pages(chart_count, items_per_page(size));
        self.load_current_page();

        // Only resize/draw charts that are currently visible.
        self.draw_visible();
    }

    /// Renders the header and chart grid into `area`.
    pub fn render(&mut self, area: Rect, buf: &mut Buffer, dims: GridDims) {
        let size = self.effective_grid_size();

        let x0 = area.x + CONTENT_PADDING;
        let inner_w = area.width.saturating_sub(CONTENT_PADDING_COLS);

        self.render_header(x0, area.y, inner_w, buf, size);

        let grid_area = Rect {
            x: x0,
            y: area.y + CHART_HEADER_HEIGHT as u16,
            width: inner_w,
            height: area
                .height
                .saturating_sub(CHART_HEADER_HEIGHT as u16)
                .min((size.rows * dims.cell_h_with_padding).max(0) as u16),
        };
        self.render_grid(grid_area, buf, dims, size);
    }

    fn render_header(&self, x: u16, y: u16, w: u16, buf: &mut Buffer, size: GridSize) {
        let chart_count = self.effective_chart_count();
        let total_count = self.charts.len();
        let items = items_per_page(size);
        let total_pages = self.nav.total_pages();

        let mut nav_info = String::new();
        if total_pages > 0 && chart_count > 0 {
            let (start, end) = self.nav.page_bounds(chart_count, items);
            if !self.filter.query().is_empty() {
                nav_info = format!(
                    " [{}-{} of {} filtered from {} total]",
                    start + 1,
                    end,
                    chart_count,
                    total_count
                );
            } else {
                nav_info = format!(" [{}-{} of {}]", start + 1, end, chart_count);
            }
        }

        let header_w = METRICS_HEADER.len() as u16;
        buf.set_stringn(x, y, METRICS_HEADER, w as usize, theme::header_style());
        if !nav_info.is_empty() && w > header_w {
            buf.set_stringn(
                x + header_w,
                y,
                &nav_info,
                (w - header_w) as usize,
                theme::nav_info_style(),
            );
        }
    }

    fn render_grid(&mut self, area: Rect, buf: &mut Buffer, dims: GridDims, size: GridSize) {
        if self.charts.is_empty() {
            let msg = "No metric data for selected runs.";
            let grid_h = (size.rows * dims.cell_h_with_padding).max(1) as u16;
            let y = area.y + grid_h.min(area.height).saturating_sub(1) / 2;
            let x = area.x + area.width.saturating_sub(msg.len() as u16) / 2;
            buf.set_stringn(x, y, msg, area.width as usize, theme::nav_info_style());
            return;
        }

        for row in 0..size.rows {
            for col in 0..size.cols {
                self.render_grid_cell(area, buf, row, col, dims);
            }
        }
    }

    /// Renders a single grid cell.
    fn render_grid_cell(
        &mut self,
        area: Rect,
        buf: &mut Buffer,
        row: i32,
        col: i32,
        dims: GridDims,
    ) {
        let Some(&Some(idx)) = self
            .current_page
            .get(row as usize)
            .and_then(|r| r.get(col as usize))
        else {
            return;
        };

        let slot_x = area.x as i32 + col * dims.cell_w_with_padding;
        let slot_y = area.y as i32 + row * dims.cell_h_with_padding;
        if slot_x < 0 || slot_y < 0 {
            return;
        }

        let focused =
            self.focus.ty == FocusType::MainChart && row == self.focus.row && col == self.focus.col;
        let border_style = if focused {
            theme::focused_border_style()
        } else {
            theme::border_style()
        };

        let chart = &self.charts[idx];
        let box_w = (dims.cell_w + 2).max(0) as u16;
        let box_h = (dims.cell_h + 3).max(0) as u16;
        let box_area = Rect {
            x: slot_x as u16,
            y: slot_y as u16,
            width: box_w.min(area.right().saturating_sub(slot_x as u16)),
            height: box_h.min(area.bottom().saturating_sub(slot_y as u16)),
        };
        if box_area.width < 2 || box_area.height < 2 {
            return;
        }

        Block::bordered()
            .border_type(BorderType::Rounded)
            .border_style(border_style)
            .render(box_area, buf);

        // Title line.
        let title_suffix = if chart.is_log_y() { " [log]" } else { "" };
        let available_title_width =
            (dims.cell_w_with_padding - 4 - title_suffix.len() as i32).max(10) as usize;
        let display_title = truncate_title(chart.title(), available_title_width);
        let inner_w = (box_area.width - 2) as usize;
        buf.set_stringn(
            box_area.x + 1,
            box_area.y + 1,
            &display_title,
            inner_w,
            theme::title_style(),
        );
        let title_w = display_title.chars().count() as u16;
        if !title_suffix.is_empty() && inner_w > title_w as usize {
            buf.set_stringn(
                box_area.x + 1 + title_w,
                box_area.y + 1,
                title_suffix,
                inner_w - title_w as usize,
                theme::nav_info_style(),
            );
        }

        // Chart canvas.
        let chart_area = Rect {
            x: box_area.x + 1,
            y: box_area.y + 2,
            width: (box_area.width - 2).min(dims.cell_w.max(0) as u16),
            height: box_area
                .height
                .saturating_sub(3)
                .min(dims.cell_h.max(0) as u16),
        };
        self.charts[idx].model.canvas.render(chart_area, buf);
    }

    /// Changes the current page.
    pub fn navigate(&mut self, direction: i32) {
        if !self.nav.navigate(direction) {
            return;
        }
        self.after_page_change();
    }

    /// Jumps to the first page.
    pub fn navigate_home(&mut self) {
        if !self.nav.go_home() {
            return;
        }
        self.after_page_change();
    }

    /// Jumps to the last page.
    pub fn navigate_end(&mut self) {
        if !self.nav.go_end() {
            return;
        }
        self.after_page_change();
    }

    fn after_page_change(&mut self) {
        self.clear_focus();
        self.load_current_page();
        self.draw_visible();
        self.navigate_focus(0, 0);
    }

    /// Draws charts that are currently visible; parks charts that are no
    /// longer visible to reduce memory usage.
    pub fn draw_visible(&mut self) {
        let dims = self.calculate_chart_dimensions(self.width, self.height);

        let mut current: HashSet<String> = HashSet::new();
        let mut visible_idx: Vec<usize> = Vec::new();
        for row in &self.current_page {
            for cell in row {
                if let Some(idx) = *cell {
                    current.insert(self.charts[idx].title().to_string());
                    visible_idx.push(idx);
                }
            }
        }
        let last_drawn = std::mem::replace(&mut self.last_drawn, current);

        for title in &last_drawn {
            if !self.last_drawn.contains(title)
                && let Some(&idx) = self.by_title.get(title)
            {
                self.charts[idx].park();
            }
        }

        for idx in visible_idx {
            self.charts[idx].resize(dims.cell_w.max(0) as usize, dims.cell_h.max(0) as usize);
            self.charts[idx].draw_if_needed();
        }
    }

    /// The title of the currently focused main-grid chart, or empty.
    fn save_focus_title(&self) -> String {
        self.focused_chart()
            .map(|c| c.title().to_string())
            .unwrap_or_default()
    }

    /// Tries to restore focus to the chart with the given title.
    fn restore_focus(&mut self, previous_title: &str) {
        if previous_title.is_empty() || self.focus.ty != FocusType::MainChart {
            return;
        }
        let mut found: Option<(i32, i32)> = None;
        'outer: for (r, cells) in self.current_page.iter().enumerate() {
            for (c, cell) in cells.iter().enumerate() {
                if let Some(idx) = *cell
                    && self.charts[idx].title() == previous_title
                {
                    found = Some((r as i32, c as i32));
                    break 'outer;
                }
            }
        }
        if let Some((r, c)) = found {
            self.set_focus(r, c);
        }
    }

    /// Handles clicks in the main chart grid.
    pub fn handle_click(&mut self, row: i32, col: i32) {
        // Unfocus if clicking the already-focused chart.
        if self.focus.ty == FocusType::MainChart && row == self.focus.row && col == self.focus.col {
            self.clear_focus();
            return;
        }

        let valid = row >= 0
            && col >= 0
            && self
                .current_page
                .get(row as usize)
                .and_then(|r| r.get(col as usize))
                .is_some_and(|c| c.is_some());
        if !valid {
            return;
        }

        self.clear_focus();
        self.set_focus(row, col);
    }

    /// Sets focus to a main grid chart.
    fn set_focus(&mut self, row: i32, col: i32) -> bool {
        let Some(&Some(idx)) = self
            .current_page
            .get(row as usize)
            .and_then(|r| r.get(col as usize))
        else {
            return false;
        };

        // Unfocus old chart.
        if let Some(old) = self.focused_chart_idx() {
            self.charts[old].set_focused(false);
        }

        let title = self.charts[idx].title().to_string();
        self.focus.set(FocusType::MainChart, row, col, &title);
        self.charts[idx].set_focused(true);
        true
    }

    /// Moves chart focus by (dr, dc) within the current page. On partial
    /// pages, clamps to the last populated cell in the target row. Returns
    /// true if navigation occurred.
    pub fn navigate_focus(&mut self, dr: i32, dc: i32) -> bool {
        if self.current_page.is_empty() {
            return false;
        }

        let (row, col) = (self.focus.row, self.focus.col);
        if row < 0 || col < 0 || self.focused_chart_idx().is_none() {
            // No current focus — find the first non-nil cell.
            for r in 0..self.current_page.len() {
                for c in 0..self.current_page[r].len() {
                    if self.current_page[r][c].is_some() {
                        return self.set_focus(r as i32, c as i32);
                    }
                }
            }
            return false;
        }

        let new_row = clamp_i32(row + dr, 0, self.current_page.len() as i32 - 1);
        let Some(last_col) = self.last_non_nil_col(new_row) else {
            return false;
        };
        let new_col = clamp_i32(col + dc, 0, last_col);

        if self.current_page[new_row as usize][new_col as usize].is_none() {
            return false;
        }
        if new_row == row && new_col == col {
            return false;
        }
        self.set_focus(new_row, new_col)
    }

    fn last_non_nil_col(&self, row: i32) -> Option<i32> {
        let cells = self.current_page.get(row as usize)?;
        cells.iter().rposition(|c| c.is_some()).map(|c| c as i32)
    }

    /// Clears focus only from main charts.
    pub fn clear_focus(&mut self) {
        if self.focus.ty == FocusType::MainChart {
            if let Some(idx) = self.focused_chart_idx() {
                self.charts[idx].set_focused(false);
            }
            self.focus.reset();
        }
    }

    /// Performs zoom handling on a main-grid chart at (row, col).
    pub fn handle_wheel(
        &mut self,
        adjusted_x: i32,
        row: i32,
        col: i32,
        dims: GridDims,
        wheel_up: bool,
    ) {
        let Some((idx, rel_x, need_focus)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims)
        else {
            return;
        };
        if rel_x < 0 || rel_x >= self.charts[idx].model.graph_width() {
            return;
        }
        if need_focus {
            self.clear_focus();
            self.set_focus(row, col);
        }

        let dir = if wheel_up {
            ZoomDirection::In
        } else {
            ZoomDirection::Out
        };
        self.charts[idx].handle_zoom(dir, rel_x);
        self.charts[idx].draw_if_needed();
    }

    /// True if the metrics grid is currently in filter input mode.
    pub fn is_filter_mode(&self) -> bool {
        self.filter.is_active()
    }

    /// True if the metrics grid has an applied filter.
    pub fn is_filtering(&self) -> bool {
        !self.filter.is_active() && !self.filter.query().is_empty()
    }

    /// The current filter pattern.
    pub fn filter_query(&self) -> &str {
        self.filter.query()
    }

    /// The chart under (row, col) with relative graph-local X.
    ///
    /// Returns (chart index, rel_x, need_focus); need_focus is true if this
    /// chart differs from current focus. None if row/col doesn't map to a
    /// visible chart.
    fn hit_chart_and_rel_x(
        &self,
        adjusted_x: i32,
        row: i32,
        col: i32,
        dims: GridDims,
    ) -> Option<(usize, i32, bool)> {
        let size = self.effective_grid_size();
        if row < 0 || row >= size.rows || col < 0 || col >= size.cols {
            return None;
        }
        let idx = (*self.current_page.get(row as usize)?.get(col as usize)?)?;
        let chart = &self.charts[idx];

        let chart_start_x = col * dims.cell_w_with_padding;
        let mut graph_start_x = chart_start_x + 1;
        if chart.model.y_step() > 0 {
            graph_start_x += chart.model.origin().0 + 1;
        }
        let rel_x = adjusted_x - graph_start_x;

        let need_focus =
            self.focus.ty != FocusType::MainChart || self.focus.row != row || self.focus.col != col;
        Some((idx, rel_x, need_focus))
    }

    /// Focuses the chart and begins inspection if inside the graph.
    ///
    /// If `synced` is true (Alt+right-press), a synchronized inspection
    /// session starts: the anchor X from the focused chart is broadcast to
    /// all visible charts.
    pub fn start_inspection(
        &mut self,
        adjusted_x: i32,
        row: i32,
        col: i32,
        dims: GridDims,
        synced: bool,
    ) {
        let Some((idx, rel_x, need_focus)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims)
        else {
            return;
        };

        // Clamp to graph bounds at the chart level, but ignore wildly
        // out-of-bounds here.
        if rel_x < -2 || rel_x > self.charts[idx].model.graph_width() + 1 {
            return;
        }

        if need_focus {
            self.clear_focus();
            self.set_focus(row, col);
        }

        self.charts[idx].start_inspection(rel_x);
        self.charts[idx].draw_if_needed();

        if synced {
            self.sync_inspect_active = true;
            let (x, _, active) = self.charts[idx].inspection_data();
            if active {
                self.broadcast_inspect_at_data_x(x);
            }
        }
    }

    /// Updates the crosshair position on the focused chart.
    ///
    /// If a synchronized inspection session is active, broadcasts the
    /// position to all visible charts on the current page.
    pub fn update_inspection(&mut self, adjusted_x: i32, row: i32, col: i32, dims: GridDims) {
        let Some((idx, rel_x, _)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims) else {
            return;
        };
        if !self.charts[idx].is_inspecting() {
            return;
        }

        self.charts[idx].start_inspection(rel_x);
        self.charts[idx].draw_if_needed();

        if self.sync_inspect_active {
            let (x, _, active) = self.charts[idx].inspection_data();
            if active {
                self.broadcast_inspect_at_data_x(x);
            }
        }
    }

    /// Clears inspection mode.
    ///
    /// If a synchronized session is active, clears inspection on all visible
    /// charts; otherwise clears only the focused chart.
    pub fn end_inspection(&mut self) {
        if self.sync_inspect_active {
            self.broadcast_end_inspection();
            self.sync_inspect_active = false;
            return;
        }

        if let Some(idx) = self.focused_chart_idx() {
            self.charts[idx].end_inspection();
            self.charts[idx].draw_if_needed();
        }
    }

    /// Applies `inspect_at_data_x` to all visible charts on the current page.
    fn broadcast_inspect_at_data_x(&mut self, anchor_x: f64) {
        for idx in self.visible_chart_indices() {
            self.charts[idx].inspect_at_data_x(anchor_x);
            self.charts[idx].draw_if_needed();
        }
    }

    /// Clears inspection on all visible charts on the current page.
    fn broadcast_end_inspection(&mut self) {
        for idx in self.visible_chart_indices() {
            if self.charts[idx].is_inspecting() {
                self.charts[idx].end_inspection();
                self.charts[idx].draw_if_needed();
            }
        }
    }

    fn visible_chart_indices(&self) -> Vec<usize> {
        self.current_page
            .iter()
            .flatten()
            .filter_map(|c| *c)
            .collect()
    }

    /// Processes a key event while the metrics filter is active.
    pub fn handle_filter_key(&mut self, key: FilterKey) {
        if self.filter.handle_key(key) {
            self.apply_filter();
            self.draw_visible();
        }
    }

    /// Applies the filter pattern to charts.
    pub fn apply_filter(&mut self) {
        self.apply_filter_internal();
    }

    fn apply_filter_internal(&mut self) {
        let matcher = self.filter.matcher();
        self.filtered = (0..self.charts.len())
            .filter(|&i| matcher.matches(self.charts[i].title()))
            .collect();

        // Keep pagination in sync with what fits now.
        let size = self.effective_grid_size();
        self.nav
            .update_total_pages(self.filtered.len(), items_per_page(size));

        self.load_current_page();
    }

    /// The number of charts matching the current filter.
    pub fn filtered_chart_count(&self) -> usize {
        self.filtered.len()
    }

    /// Enters filter input mode.
    pub fn enter_filter_mode(&mut self) {
        self.filter.activate();
    }

    /// Updates the in-progress filter text (for live preview).
    pub fn update_filter_draft(&mut self, key: FilterKey) {
        self.filter.update_draft(key);
    }

    /// Exits filter input mode and optionally applies the filter.
    pub fn exit_filter_mode(&mut self, apply: bool) {
        if apply {
            self.filter.commit();
        } else {
            self.filter.cancel();
        }
        self.apply_filter();
        self.draw_visible();
    }

    /// Removes the active filter.
    pub fn clear_filter(&mut self) {
        self.filter.clear();
        self.apply_filter();
        self.draw_visible();
    }

    /// Flips regex <-> glob and reapplies the current preview/applied filter.
    pub fn toggle_filter_match_mode(&mut self) {
        self.filter.toggle_mode();
        self.apply_filter();
        self.draw_visible();
    }

    /// The current filter match mode.
    pub fn filter_mode(&self) -> FilterMatchMode {
        self.filter.mode()
    }

    /// Removes the series with the given key from all charts, pruning charts
    /// that end up with no series.
    pub fn remove_series(&mut self, key: &str) {
        if key.is_empty() || self.charts.is_empty() {
            return;
        }

        for chart in &mut self.charts {
            chart.remove_series(key);
        }
        self.charts.retain(|c| c.series_count() > 0);

        // Rebuild index by title to stay consistent.
        self.by_title = self
            .charts
            .iter()
            .enumerate()
            .map(|(i, c)| (c.title().to_string(), i))
            .collect();

        // Reapply filter + nav on the pruned chart set.
        self.apply_filter_internal();
        self.draw_visible();
    }

    /// Ensures the given series key is drawn last in all charts. Used by the
    /// workspace to keep a pinned run visually on top.
    pub fn promote_series_to_top(&mut self, series_key: &str) {
        if series_key.is_empty() {
            return;
        }
        for chart in &mut self.charts {
            chart.promote_series_to_top(series_key);
        }
    }
}
