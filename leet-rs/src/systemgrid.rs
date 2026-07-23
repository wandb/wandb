//! The grid of system metric charts.

use std::collections::{HashMap, HashSet};

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::widgets::{Block, BorderType, Widget};

use crate::chart::epoch::{ZoomDirection, truncate_title};
use crate::chart::frenchfries::{FrenchFriesChart, FrenchFriesChartParams};
use crate::chart::timeseries::{TimeSeriesLineChart, TimeSeriesLineChartParams};
use crate::filter::{Filter, FilterKey, FilterMatchMode};
use crate::grid::{
    Focus, FocusType, GridDims, GridNavigator, GridSize, GridSpec, clamp_i32, compute_grid_dims,
    effective_grid_size, items_per_page,
};
use crate::msg::StatsMsg;
use crate::systemmetrics::{MetricDef, extract_base_key, extract_series_name, match_metric_def};
use crate::theme::{
    self, Adaptive, CHART_TITLE_HEIGHT, COLOR_MODE_PER_SERIES, MIN_METRIC_CHART_HEIGHT,
    MIN_METRIC_CHART_WIDTH,
};

/// Config-derived settings for the system metrics grid.
#[derive(Debug, Clone)]
pub struct SystemGridSettings {
    pub rows: i32,
    pub cols: i32,
    pub color_scheme: String,
    /// `per_plot` or `per_series`.
    pub color_mode: String,
    pub french_fries_scheme: String,
    pub tail_window_secs: f64,
}

/// Keeps the time-series line chart as the source of truth for time-window
/// behavior while optionally rendering the same metric as a heatmap-style
/// French Fries chart.
pub struct FrenchFriesToggleChart {
    line: TimeSeriesLineChart,
    fries: FrenchFriesChart,
    heatmap_mode: bool,
}

impl FrenchFriesToggleChart {
    fn new(line: TimeSeriesLineChart, fries: FrenchFriesChart) -> Self {
        let mut chart = Self {
            line,
            fries,
            heatmap_mode: false,
        };
        chart.sync_view_window();
        chart
    }

    fn sync_view_window(&mut self) {
        self.fries.set_view_window(
            self.line.chart.model.view_min_x(),
            self.line.chart.model.view_max_x(),
        );
    }
}

/// A rendered system-metric chart: either a plain time-series line chart or
/// one that can toggle into a heatmap.
#[allow(clippy::large_enum_variant)] // Few charts; indirection not worth it.
pub enum SystemMetricChart {
    Line(TimeSeriesLineChart),
    Toggle(FrenchFriesToggleChart),
}

impl SystemMetricChart {
    fn line(&self) -> &TimeSeriesLineChart {
        match self {
            Self::Line(c) => c,
            Self::Toggle(t) => &t.line,
        }
    }

    fn line_mut(&mut self) -> &mut TimeSeriesLineChart {
        match self {
            Self::Line(c) => c,
            Self::Toggle(t) => &mut t.line,
        }
    }

    pub fn title(&self) -> &str {
        self.line().chart.title()
    }

    pub fn title_detail(&self) -> String {
        match self {
            Self::Line(c) => c.title_detail(),
            Self::Toggle(t) if t.heatmap_mode => t.fries.title_detail(),
            Self::Toggle(t) => t.line.title_detail(),
        }
    }

    pub fn set_tail_window(&mut self, window_secs: f64) {
        self.line_mut().set_tail_window(window_secs);
        if let Self::Toggle(t) = self {
            t.sync_view_window();
        }
    }

    /// Minimizes memory for the underlying chart(s).
    pub fn park(&mut self) {
        match self {
            Self::Line(c) => c.park(),
            Self::Toggle(t) => {
                t.line.park();
                t.fries.park();
            }
        }
    }

    pub fn resize(&mut self, width: usize, height: usize) {
        match self {
            Self::Line(c) => c.resize(width, height),
            Self::Toggle(t) => {
                t.line.resize(width, height);
                t.fries.resize(width, height);
                t.sync_view_window();
            }
        }
    }

    pub fn draw_if_needed(&mut self) {
        match self {
            Self::Line(c) => c.chart.draw_if_needed(),
            Self::Toggle(t) => {
                t.sync_view_window();
                if t.heatmap_mode {
                    t.fries.draw_if_needed();
                } else {
                    t.line.chart.draw_if_needed();
                }
            }
        }
    }

    pub fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        match self {
            Self::Line(c) => c.add_data_point(series_name, timestamp, value),
            Self::Toggle(t) => {
                t.line.add_data_point(series_name, timestamp, value);
                t.fries.add_data_point(series_name, timestamp, value);
                t.sync_view_window();
            }
        }
    }

    pub fn graph_width(&self) -> i32 {
        match self {
            Self::Toggle(t) if t.heatmap_mode => t.fries.graph_width() as i32,
            _ => self.line().chart.model.graph_width(),
        }
    }

    pub fn graph_height(&self) -> i32 {
        match self {
            Self::Toggle(t) if t.heatmap_mode => t.fries.graph_height() as i32,
            _ => self.line().chart.model.graph_height(),
        }
    }

    /// The first graph column inside the rendered chart cell.
    pub fn graph_start_x(&self) -> i32 {
        match self {
            Self::Toggle(t) if t.heatmap_mode => t.fries.graph_start_x() as i32,
            _ => self.line().graph_start_x(),
        }
    }

    /// The first graph row inside the rendered chart cell.
    pub fn graph_start_y(&self) -> i32 {
        1 + CHART_TITLE_HEIGHT
    }

    pub fn handle_zoom(&mut self, direction: ZoomDirection, mouse_x: i32) {
        match self {
            Self::Line(c) => c.handle_zoom(direction, mouse_x),
            Self::Toggle(t) => {
                t.line.handle_zoom(direction, mouse_x);
                t.sync_view_window();
                self.draw_if_needed();
            }
        }
    }

    pub fn toggle_y_scale(&mut self) -> bool {
        match self {
            Self::Line(c) => c.toggle_y_scale(),
            Self::Toggle(t) if t.heatmap_mode => false,
            Self::Toggle(t) => t.line.toggle_y_scale(),
        }
    }

    pub fn is_log_y(&self) -> bool {
        match self {
            Self::Toggle(t) if t.heatmap_mode => false,
            _ => self.line().chart.is_log_y(),
        }
    }

    pub fn supports_heatmap(&self) -> bool {
        matches!(self, Self::Toggle(_))
    }

    pub fn toggle_heatmap_mode(&mut self) -> bool {
        let Self::Toggle(t) = self else {
            return false;
        };
        t.heatmap_mode = !t.heatmap_mode;
        t.sync_view_window();
        self.draw_if_needed();
        true
    }

    pub fn is_heatmap_mode(&self) -> bool {
        matches!(self, Self::Toggle(t) if t.heatmap_mode)
    }

    pub fn view_mode_label(&self) -> String {
        self.line().view_mode_label()
    }

    pub fn scale_label(&self) -> &'static str {
        match self {
            Self::Toggle(t) if t.heatmap_mode => "heatmap",
            _ => self.line().chart.scale_label(),
        }
    }

    pub fn start_inspection_at(&mut self, mouse_x: i32, _mouse_y: i32) {
        match self {
            Self::Line(c) => c.chart.start_inspection(mouse_x),
            Self::Toggle(t) => {
                t.sync_view_window();
                if t.heatmap_mode {
                    t.fries.start_inspection_at(mouse_x);
                } else {
                    t.line.chart.start_inspection(mouse_x);
                }
            }
        }
    }

    pub fn update_inspection_at(&mut self, mouse_x: i32, _mouse_y: i32) {
        match self {
            Self::Line(c) => c.chart.update_inspection(mouse_x),
            Self::Toggle(t) => {
                t.sync_view_window();
                if t.heatmap_mode {
                    t.fries.update_inspection_at(mouse_x);
                } else {
                    t.line.chart.update_inspection(mouse_x);
                }
            }
        }
    }

    pub fn end_inspection(&mut self) {
        match self {
            Self::Line(c) => c.chart.end_inspection(),
            Self::Toggle(t) => {
                t.line.chart.end_inspection();
                t.fries.end_inspection();
            }
        }
    }

    pub fn is_inspecting(&self) -> bool {
        match self {
            Self::Toggle(t) if t.heatmap_mode => t.fries.is_inspecting(),
            _ => self.line().chart.is_inspecting(),
        }
    }

    pub fn inspection_data(&self) -> (f64, f64, bool) {
        match self {
            Self::Toggle(t) if t.heatmap_mode => t.fries.inspection_data(),
            _ => self.line().chart.inspection_data(),
        }
    }

    pub fn inspect_at_data_x(&mut self, target_x: f64) {
        match self {
            Self::Line(c) => c.chart.inspect_at_data_x(target_x),
            Self::Toggle(t) => {
                t.sync_view_window();
                if t.heatmap_mode {
                    t.fries.inspect_at_data_x(target_x);
                } else {
                    t.line.chart.inspect_at_data_x(target_x);
                }
            }
        }
    }

    /// Renders the active chart's canvas into `area`.
    fn render_canvas(&mut self, area: Rect, buf: &mut Buffer) {
        match self {
            Self::Toggle(t) if t.heatmap_mode => t.fries.canvas().render(area, buf),
            _ => self.line().chart.model.canvas.render(area, buf),
        }
    }
}

/// Manages the grid of system metric charts.
pub struct SystemMetricsGrid {
    settings: SystemGridSettings,

    /// Viewport dimensions.
    width: i32,
    height: i32,

    /// Pagination state.
    nav: GridNavigator,

    /// Chart storage; indices are stable (charts are never removed).
    charts: Vec<SystemMetricChart>,
    /// baseKey -> index into `charts`.
    by_base_key: HashMap<String, usize>,
    /// Chart indices sorted by title.
    ordered: Vec<usize>,
    /// Indices matching the current filter.
    filtered: Vec<usize>,
    /// Current page view.
    current_page: Vec<Vec<Option<usize>>>,

    /// Filter state.
    filter: Filter,

    /// Chart focus management.
    pub focus: Focus,

    /// Next palette index for per-plot mode.
    next_color: usize,

    /// Charts from the last visible page, for parking.
    last_drawn: HashSet<usize>,

    /// Synchronized inspection session state (active between press/release).
    sync_inspect_active: bool,
}

impl SystemMetricsGrid {
    pub fn new(width: i32, height: i32, settings: SystemGridSettings) -> Self {
        let mut grid = Self {
            settings,
            width,
            height,
            nav: GridNavigator::default(),
            charts: Vec::new(),
            by_base_key: HashMap::new(),
            ordered: Vec::new(),
            filtered: Vec::new(),
            current_page: Vec::new(),
            filter: Filter::new(),
            focus: Focus::new(),
            next_color: 0,
            last_drawn: HashSet::new(),
            sync_inspect_active: false,
        };
        let size = grid.effective_grid_size();
        grid.current_page = vec![vec![None; size.cols as usize]; size.rows as usize];
        grid
    }

    /// Updates config-derived settings (grid shape, palettes, tail window).
    pub fn set_settings(&mut self, settings: SystemGridSettings) {
        let tail_changed = settings.tail_window_secs != self.settings.tail_window_secs;
        self.settings = settings;
        if tail_changed {
            for chart in &mut self.charts {
                chart.set_tail_window(self.settings.tail_window_secs);
            }
        }
    }

    fn grid_spec(&self) -> GridSpec {
        GridSpec {
            rows: self.settings.rows,
            cols: self.settings.cols,
            min_cell_w: MIN_METRIC_CHART_WIDTH as i32,
            min_cell_h: MIN_METRIC_CHART_HEIGHT as i32,
            header_lines: 0,
        }
    }

    /// Dimensions for system metric charts.
    pub fn calculate_chart_dimensions(&self) -> GridDims {
        compute_grid_dims(self.width, self.height, self.grid_spec())
    }

    /// The grid size that can fit in the current viewport.
    fn effective_grid_size(&self) -> GridSize {
        effective_grid_size(self.width, self.height, self.grid_spec())
    }

    /// The next color from the active system palette.
    fn next_palette_color(&mut self) -> Adaptive {
        let palette = theme::graph_colors(&self.settings.color_scheme);
        let color = palette[self.next_color % palette.len()];
        self.next_color += 1;
        color
    }

    /// A provider that yields colors relative to a given base index in the
    /// current palette. The first call returns the color after the base
    /// color, so the base can be used for the first series.
    fn anchored_series_color_provider(&self, base_idx: usize) -> Box<dyn FnMut() -> Adaptive> {
        let palette = theme::graph_colors(&self.settings.color_scheme);
        let mut idx = base_idx + 1;
        Box::new(move || {
            let c = palette[idx % palette.len()];
            idx += 1;
            c
        })
    }

    /// Creates a time series chart for a system metric.
    fn create_metric_chart(&mut self, def: &'static MetricDef) -> SystemMetricChart {
        let dims = self.calculate_chart_dimensions();
        let chart_width = dims.cell_w.max(MIN_METRIC_CHART_WIDTH as i32) as usize;
        let chart_height = dims.cell_h.max(MIN_METRIC_CHART_HEIGHT as i32) as usize;

        // Base color by color mode.
        let palette = theme::graph_colors(&self.settings.color_scheme);
        let (base_color, base_idx) = if self.settings.color_mode == COLOR_MODE_PER_SERIES {
            (palette[0], 0)
        } else {
            let color = self.next_palette_color();
            (color, (self.next_color - 1) % palette.len())
        };

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);

        let mut line = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: chart_width,
            height: chart_height,
            def,
            base_color,
            color_provider: Some(self.anchored_series_color_provider(base_idx)),
            now,
        });
        line.set_tail_window(self.settings.tail_window_secs);

        if !def.percentage {
            return SystemMetricChart::Line(line);
        }

        let fries = FrenchFriesChart::new(FrenchFriesChartParams {
            width: chart_width,
            height: chart_height,
            def,
            colors: theme::french_fries_colors(&self.settings.french_fries_scheme).to_vec(),
            now,
        });
        SystemMetricChart::Toggle(FrenchFriesToggleChart::new(line, fries))
    }

    /// Adds a new data point to the appropriate metric chart.
    ///
    /// Drawing is deferred to render time to avoid redundant redraws when
    /// processing a batch of metrics from a single stats record.
    pub fn add_data_point(&mut self, metric_name: &str, timestamp: i64, value: f64) {
        if self.add_data_point_internal(metric_name, timestamp, value) {
            self.refresh_chart_set();
        }
    }

    /// Ingests all metrics from a single stats record, batching any chart
    /// creation/filtering/redraw work.
    pub fn process_stats(&mut self, msg: &StatsMsg) {
        if msg.metrics.is_empty() {
            return;
        }

        let mut chart_set_changed = false;
        for (metric_name, value) in &msg.metrics {
            if self.add_data_point_internal(metric_name, msg.timestamp, *value) {
                chart_set_changed = true;
            }
        }
        if chart_set_changed {
            self.refresh_chart_set();
        }
    }

    /// Adds a sample and reports whether the chart set changed.
    fn add_data_point_internal(&mut self, metric_name: &str, timestamp: i64, value: f64) -> bool {
        let Some(def) = match_metric_def(metric_name) else {
            return false;
        };

        let base_key = extract_base_key(metric_name);
        let series_name = extract_series_name(metric_name);

        let (idx, created) = self.get_or_create_chart(&base_key, def);
        self.charts[idx].add_data_point(&series_name, timestamp, value);
        created
    }

    /// Returns a chart index for the given base key, creating it if needed.
    fn get_or_create_chart(&mut self, base_key: &str, def: &'static MetricDef) -> (usize, bool) {
        if let Some(&idx) = self.by_base_key.get(base_key) {
            return (idx, false);
        }
        let chart = self.create_metric_chart(def);
        self.charts.push(chart);
        let idx = self.charts.len() - 1;
        self.by_base_key.insert(base_key.to_string(), idx);
        self.add_chart(idx);
        (idx, true)
    }

    /// Adds a chart index to the ordered list.
    fn add_chart(&mut self, idx: usize) {
        self.ordered.push(idx);
        self.ordered
            .sort_by(|&a, &b| self.charts[a].title().cmp(self.charts[b].title()));
    }

    fn refresh_chart_set(&mut self) {
        self.apply_filter();
        self.draw_visible();
    }

    /// Loads charts for the current page.
    pub fn load_current_page(&mut self) {
        let size = self.effective_grid_size();

        self.current_page = vec![vec![None; size.cols as usize]; size.rows as usize];

        let (start, end) = self
            .nav
            .page_bounds(self.filtered.len(), items_per_page(size));

        let mut idx = start;
        'outer: for row in 0..size.rows as usize {
            for col in 0..size.cols as usize {
                if idx >= end {
                    break 'outer;
                }
                self.current_page[row][col] = Some(self.filtered[idx]);
                idx += 1;
            }
        }

        self.sync_focus_to_current_page();
    }

    /// Changes pages.
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

    /// Handles mouse clicks for chart selection. Returns whether an element
    /// was focused.
    pub fn handle_mouse_click(&mut self, row: i32, col: i32) -> bool {
        if self.focus.ty == FocusType::SystemChart && row == self.focus.row && col == self.focus.col
        {
            self.clear_focus();
            return false;
        }
        self.set_focus(row, col)
    }

    fn set_focus(&mut self, row: i32, col: i32) -> bool {
        let size = self.effective_grid_size();
        if row < 0 || row >= size.rows || col < 0 || col >= size.cols {
            return false;
        }
        let Some(&Some(idx)) = self
            .current_page
            .get(row as usize)
            .and_then(|r| r.get(col as usize))
        else {
            return false;
        };

        self.clear_focus();
        let title = self.charts[idx].title().to_string();
        self.focus.set(FocusType::SystemChart, row, col, &title);
        true
    }

    /// Moves chart focus by (dr, dc) within the current page. On partial
    /// pages, vertical moves clamp to the last populated cell in the target
    /// row. Returns true if focus changed or was re-materialized.
    pub fn navigate_focus(&mut self, dr: i32, dc: i32) -> bool {
        if self.current_page.is_empty() {
            return false;
        }

        let (mut row, mut col) = (self.focus.row, self.focus.col);
        if self.focused_chart_idx().is_none() {
            let Some((r, c)) = self.first_non_nil_cell() else {
                return false;
            };
            row = r;
            col = c;
        }

        let new_row = clamp_i32(row + dr, 0, self.current_page.len() as i32 - 1);
        let Some(last_col) = self.last_non_nil_col(new_row) else {
            return false;
        };
        let new_col = clamp_i32(col + dc, 0, last_col);

        let Some(&Some(idx)) = self
            .current_page
            .get(new_row as usize)
            .and_then(|r| r.get(new_col as usize))
        else {
            return false;
        };

        if self.focus.ty == FocusType::SystemChart
            && self.focus.row == new_row
            && self.focus.col == new_col
            && self.focus.title == self.charts[idx].title()
        {
            return false;
        }

        self.set_focus(new_row, new_col)
    }

    fn first_non_nil_cell(&self) -> Option<(i32, i32)> {
        for (r, cells) in self.current_page.iter().enumerate() {
            for (c, cell) in cells.iter().enumerate() {
                if cell.is_some() {
                    return Some((r as i32, c as i32));
                }
            }
        }
        None
    }

    fn last_non_nil_col(&self, row: i32) -> Option<i32> {
        let cells = self.current_page.get(row as usize)?;
        cells.iter().rposition(|c| c.is_some()).map(|c| c as i32)
    }

    /// Removes focus from all charts.
    pub fn clear_focus(&mut self) {
        if self.focus.ty == FocusType::SystemChart {
            self.focus.reset();
        }
    }

    /// The title of the focused chart.
    pub fn focused_chart_title(&self) -> &str {
        if self.focus.ty == FocusType::SystemChart {
            &self.focus.title
        } else {
            ""
        }
    }

    /// A short description of the focused chart's X-axis mode.
    pub fn focused_chart_view_mode_label(&self) -> String {
        self.focused_chart()
            .map(|c| c.view_mode_label())
            .unwrap_or_default()
    }

    pub fn focused_chart_scale_label(&self) -> &'static str {
        self.focused_chart().map_or("", |c| c.scale_label())
    }

    pub fn focused_chart_title_detail(&self) -> String {
        self.focused_chart()
            .map(|c| c.title_detail())
            .unwrap_or_default()
    }

    fn focused_chart_idx(&self) -> Option<usize> {
        if self.focus.ty != FocusType::SystemChart || self.focus.row < 0 || self.focus.col < 0 {
            return None;
        }
        *self
            .current_page
            .get(self.focus.row as usize)?
            .get(self.focus.col as usize)?
    }

    fn focused_chart(&self) -> Option<&SystemMetricChart> {
        self.focused_chart_idx().map(|i| &self.charts[i])
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

    pub fn toggle_focused_chart_heatmap_mode(&mut self) -> bool {
        let Some(idx) = self.focused_chart_idx() else {
            return false;
        };
        if !self.charts[idx].supports_heatmap() || !self.charts[idx].toggle_heatmap_mode() {
            return false;
        }
        self.charts[idx].draw_if_needed();
        true
    }

    /// Cycles the focused chart through its display modes:
    /// linear -> log -> heatmap -> linear (where supported).
    pub fn cycle_focused_chart_mode(&mut self) -> bool {
        let Some(idx) = self.focused_chart_idx() else {
            return false;
        };
        let chart = &mut self.charts[idx];

        if !chart.supports_heatmap() {
            if !chart.toggle_y_scale() {
                return false;
            }
            chart.draw_if_needed();
            return true;
        }

        if chart.is_heatmap_mode() {
            if !chart.toggle_heatmap_mode() {
                return false;
            }
            if chart.is_log_y() {
                chart.toggle_y_scale();
            }
            chart.draw_if_needed();
            return true;
        }

        if chart.is_log_y() {
            if !chart.toggle_heatmap_mode() {
                return false;
            }
            chart.draw_if_needed();
            return true;
        }

        if chart.toggle_y_scale() {
            chart.draw_if_needed();
            return true;
        }
        if chart.toggle_heatmap_mode() {
            chart.draw_if_needed();
            return true;
        }
        false
    }

    /// Updates viewport dimensions and resizes/redraws visible charts.
    pub fn resize(&mut self, width: i32, height: i32) {
        if width <= 0 || height <= 0 {
            return;
        }

        self.width = width;
        self.height = height;

        let dims = self.calculate_chart_dimensions();
        if dims.cell_w < MIN_METRIC_CHART_WIDTH as i32
            || dims.cell_h < MIN_METRIC_CHART_HEIGHT as i32
        {
            return;
        }

        let size = self.effective_grid_size();
        self.nav
            .update_total_pages(self.filtered.len(), items_per_page(size));
        self.load_current_page();
        self.draw_visible();
    }

    /// Resizes and draws charts on the current page; parks charts that are
    /// no longer visible to reduce memory usage.
    fn draw_visible(&mut self) {
        let dims = self.calculate_chart_dimensions();

        let current: HashSet<usize> = self.visible_chart_indices().into_iter().collect();
        let last_drawn = std::mem::replace(&mut self.last_drawn, current);

        for idx in last_drawn {
            if !self.last_drawn.contains(&idx) {
                self.charts[idx].park();
            }
        }

        let visible: Vec<usize> = self.last_drawn.iter().copied().collect();
        for idx in visible {
            self.charts[idx].resize(dims.cell_w.max(0) as usize, dims.cell_h.max(0) as usize);
            self.charts[idx].draw_if_needed();
        }
    }

    fn visible_chart_indices(&self) -> Vec<usize> {
        self.current_page
            .iter()
            .flatten()
            .filter_map(|c| *c)
            .collect()
    }

    fn sync_focus_to_current_page(&mut self) {
        if self.focus.ty != FocusType::SystemChart || self.focus.title.is_empty() {
            return;
        }

        // If the chart at the current position still matches, keep it. This
        // avoids jumping when multiple charts share the same title.
        let (r, c) = (self.focus.row, self.focus.col);
        if r >= 0
            && c >= 0
            && let Some(Some(idx)) = self
                .current_page
                .get(r as usize)
                .and_then(|row| row.get(c as usize))
            && self.charts[*idx].title() == self.focus.title
        {
            return;
        }

        // Position changed (e.g. chart order shifted) — scan by title.
        for (row, cells) in self.current_page.iter().enumerate() {
            for (col, cell) in cells.iter().enumerate() {
                if let Some(idx) = cell
                    && self.charts[*idx].title() == self.focus.title
                {
                    self.focus.row = row as i32;
                    self.focus.col = col as i32;
                    return;
                }
            }
        }

        // Focused chart is not visible on this page.
        self.clear_focus();
    }

    /// Renders the system metrics grid.
    ///
    /// Dirty visible charts are drawn before rendering so that data added
    /// since the last frame is reflected without per-point draw overhead.
    pub fn render(&mut self, area: Rect, buf: &mut Buffer) {
        let dims = self.calculate_chart_dimensions();
        let size = self.effective_grid_size();

        for row in 0..size.rows {
            for col in 0..size.cols {
                self.render_cell(area, buf, row, col, dims);
            }
        }
    }

    fn render_cell(&mut self, area: Rect, buf: &mut Buffer, row: i32, col: i32, dims: GridDims) {
        let Some(&Some(idx)) = self
            .current_page
            .get(row as usize)
            .and_then(|r| r.get(col as usize))
        else {
            return;
        };

        self.charts[idx].draw_if_needed();

        let slot_x = area.x as i32 + col * dims.cell_w_with_padding;
        let slot_y = area.y as i32 + row * dims.cell_h_with_padding;
        if slot_x < 0 || slot_y < 0 {
            return;
        }

        let focused = self.focus.ty == FocusType::SystemChart
            && row == self.focus.row
            && col == self.focus.col;
        let border_style = if focused {
            theme::focused_border_style()
        } else {
            theme::border_style()
        };

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

        self.render_chart_title(&self.chart_title_parts(idx, dims.cell_w), box_area, buf);

        let chart_area = Rect {
            x: box_area.x + 1,
            y: box_area.y + 2,
            width: (box_area.width - 2).min(dims.cell_w.max(0) as u16),
            height: box_area
                .height
                .saturating_sub(3)
                .min(dims.cell_h.max(0) as u16),
        };
        self.charts[idx].render_canvas(chart_area, buf);
    }

    /// (title, detail, mode) segments for a chart header, with progressive
    /// dropping of suffixes when space is tight.
    fn chart_title_parts(&self, idx: usize, max_width: i32) -> (String, String, String) {
        let chart = &self.charts[idx];
        if max_width <= 0 {
            return (String::new(), String::new(), String::new());
        }

        let detail = match chart.title_detail() {
            d if d.is_empty() => String::new(),
            d => format!(" {d}"),
        };
        let mode = if chart.is_heatmap_mode() {
            " [heatmap]".to_string()
        } else if chart.is_log_y() {
            " [log]".to_string()
        } else {
            String::new()
        };

        let mut show_detail = !detail.is_empty();
        let mut show_mode = !mode.is_empty();
        loop {
            let mut suffix_width = 0i32;
            if show_detail {
                suffix_width += detail.chars().count() as i32;
            }
            if show_mode {
                suffix_width += mode.chars().count() as i32;
            }
            if max_width - suffix_width >= 1 {
                break;
            }
            if show_mode {
                show_mode = false;
                continue;
            }
            if show_detail {
                show_detail = false;
                continue;
            }
            break;
        }

        let mut suffix_width = 0i32;
        let detail = if show_detail { detail } else { String::new() };
        let mode = if show_mode { mode } else { String::new() };
        suffix_width += detail.chars().count() as i32 + mode.chars().count() as i32;
        let title_width = (max_width - suffix_width).max(1) as usize;
        (truncate_title(chart.title(), title_width), detail, mode)
    }

    fn render_chart_title(
        &self,
        (title, detail, mode): &(String, String, String),
        box_area: Rect,
        buf: &mut Buffer,
    ) {
        let inner_w = (box_area.width - 2) as usize;
        let mut x = box_area.x + 1;
        let y = box_area.y + 1;
        buf.set_stringn(x, y, title, inner_w, theme::title_style());
        x += title.chars().count() as u16;
        if !detail.is_empty() {
            buf.set_stringn(
                x,
                y,
                detail,
                inner_w.saturating_sub((x - box_area.x - 1) as usize),
                theme::series_count_style(),
            );
            x += detail.chars().count() as u16;
        }
        if !mode.is_empty() {
            buf.set_stringn(
                x,
                y,
                mode,
                inner_w.saturating_sub((x - box_area.x - 1) as usize),
                theme::nav_info_style(),
            );
        }
    }

    /// The number of charts on the grid.
    pub fn chart_count(&self) -> usize {
        self.ordered.len()
    }

    /// The chart under (row, col) with relative graph-local coordinates.
    ///
    /// Returns (index, rel_x, rel_y, need_focus).
    fn hit_chart_and_rel_pos(
        &self,
        adjusted_x: i32,
        adjusted_y: i32,
        row: i32,
        col: i32,
        dims: GridDims,
    ) -> Option<(usize, i32, i32, bool)> {
        let size = self.effective_grid_size();
        if row < 0 || row >= size.rows || col < 0 || col >= size.cols {
            return None;
        }
        let idx = (*self.current_page.get(row as usize)?.get(col as usize)?)?;
        let chart = &self.charts[idx];

        let chart_start_x = col * dims.cell_w_with_padding;
        let chart_start_y = row * dims.cell_h_with_padding;
        let rel_x = adjusted_x - (chart_start_x + chart.graph_start_x());
        let rel_y = adjusted_y - (chart_start_y + chart.graph_start_y());

        let need_focus = self.focus.ty != FocusType::SystemChart
            || self.focus.row != row
            || self.focus.col != col;
        Some((idx, rel_x, rel_y, need_focus))
    }

    /// Performs zoom handling on a system chart at (row, col).
    pub fn handle_wheel(
        &mut self,
        adjusted_x: i32,
        row: i32,
        col: i32,
        dims: GridDims,
        wheel_up: bool,
    ) {
        let Some((idx, rel_x, _, need_focus)) =
            self.hit_chart_and_rel_pos(adjusted_x, 0, row, col, dims)
        else {
            return;
        };
        if rel_x < 0 || rel_x >= self.charts[idx].graph_width() {
            return;
        }
        if need_focus {
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

    /// Focuses the chart and begins inspection if inside the graph.
    ///
    /// If `synced` is true (Alt+right-press), a synchronized inspection
    /// session starts: the anchor X from the focused chart is broadcast to
    /// all visible charts.
    pub fn start_inspection(
        &mut self,
        adjusted_x: i32,
        adjusted_y: i32,
        row: i32,
        col: i32,
        dims: GridDims,
        synced: bool,
    ) {
        let Some((idx, rel_x, rel_y, need_focus)) =
            self.hit_chart_and_rel_pos(adjusted_x, adjusted_y, row, col, dims)
        else {
            return;
        };
        let chart = &self.charts[idx];
        if rel_x < -2
            || rel_x > chart.graph_width() + 1
            || rel_y < -2
            || rel_y > chart.graph_height() + 1
        {
            return;
        }
        if need_focus {
            self.set_focus(row, col);
        }

        self.charts[idx].start_inspection_at(rel_x, rel_y);
        self.charts[idx].draw_if_needed();

        if !synced {
            return;
        }

        let (x, _, active) = self.charts[idx].inspection_data();
        if active {
            self.sync_inspect_active = true;
            self.broadcast_inspect_at_data_x(x);
        }
    }

    /// Updates the crosshair position on the focused chart.
    ///
    /// If a synchronized inspection session is active, broadcasts the
    /// position to all visible charts on the current page.
    pub fn update_inspection(
        &mut self,
        adjusted_x: i32,
        adjusted_y: i32,
        row: i32,
        col: i32,
        dims: GridDims,
    ) {
        let Some((idx, rel_x, rel_y, _)) =
            self.hit_chart_and_rel_pos(adjusted_x, adjusted_y, row, col, dims)
        else {
            return;
        };
        if !self.charts[idx].is_inspecting() {
            return;
        }

        self.charts[idx].update_inspection_at(rel_x, rel_y);
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

    fn broadcast_inspect_at_data_x(&mut self, anchor_x: f64) {
        for idx in self.visible_chart_indices() {
            self.charts[idx].inspect_at_data_x(anchor_x);
            self.charts[idx].draw_if_needed();
        }
    }

    fn broadcast_end_inspection(&mut self) {
        for idx in self.visible_chart_indices() {
            if self.charts[idx].is_inspecting() {
                self.charts[idx].end_inspection();
                self.charts[idx].draw_if_needed();
            }
        }
    }

    // ---- Filtering ----

    /// Applies the current filter pattern to system metric charts.
    pub fn apply_filter(&mut self) {
        let matcher = self.filter.matcher();
        self.filtered = self
            .ordered
            .iter()
            .copied()
            .filter(|&i| matcher.matches(self.charts[i].title()))
            .collect();

        let size = self.effective_grid_size();
        self.nav
            .update_total_pages(self.filtered.len(), items_per_page(size));
        self.load_current_page();
        self.draw_visible();
    }

    /// The number of charts matching the current filter.
    /// Returns pagination info for a header: (start 1-indexed, end,
    /// filtered count, total count), or None when nothing is shown.
    pub fn pagination_info(&self) -> Option<(usize, usize, usize, usize)> {
        let total = self.chart_count();
        let filtered = self.filtered.len();
        let per_page = items_per_page(self.effective_grid_size());
        if self.nav.total_pages() == 0 || filtered == 0 || per_page == 0 {
            return None;
        }
        let (start, end) = self.nav.page_bounds(filtered, per_page);
        Some((start + 1, end, filtered, total))
    }

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
    }

    /// Removes the active filter.
    pub fn clear_filter(&mut self) {
        self.filter.clear();
        self.apply_filter();
    }

    /// Flips regex <-> glob and reapplies the current preview/applied filter.
    pub fn toggle_filter_match_mode(&mut self) {
        self.filter.toggle_mode();
        self.apply_filter();
    }

    /// The current filter match mode.
    pub fn filter_mode(&self) -> FilterMatchMode {
        self.filter.mode()
    }

    /// True if we are currently typing a filter.
    pub fn is_filter_mode(&self) -> bool {
        self.filter.is_active()
    }

    /// True if we have an applied filter (not just input mode).
    pub fn is_filtering(&self) -> bool {
        !self.filter.is_active() && !self.filter.query().is_empty()
    }

    /// The current filter pattern (draft if active, applied otherwise).
    pub fn filter_query(&self) -> &str {
        self.filter.query()
    }

    /// Processes a key event while the system metrics filter is active.
    pub fn handle_filter_key(&mut self, key: FilterKey) {
        if self.filter.handle_key(key) {
            self.apply_filter();
        }
    }
}
