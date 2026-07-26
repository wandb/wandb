//! Port of `core/internal/leet/systemmetricsgrid.go` and
//! `systemmetricsfilter.go` (the `SystemMetricsGrid` filter methods; see
//! PORTING.md module mapping).
//!
//! The system-metrics chart grid: owns per-metric-family charts (created from
//! `leet_data::system_metrics` MetricDef matches), maintains filter and
//! pagination state, and computes/renders the current page/grid layout.
//! Percentage metrics get a line/french-fries toggle chart
//! (`leet_charts::FrenchFriesToggleChart`); everything else a plain
//! `TimeSeriesLineChart`.
//!
//! Concurrency: unlike `MetricsGrid` (S9), Go's `SystemMetricsGrid` carries no
//! mutex — it is Update-thread-only already, so the port is a plain struct.
//!
//! Shared ownership: Go shares `systemMetricChart` interface values between
//! `byBaseKey`, `ordered`, `filtered`, `currentPage` and `lastDrawnCharts`;
//! the port mirrors that aliasing with `Rc<RefCell<SystemChart>>`
//! (single-threaded, CONCURRENCY.md §2.6). `*Focus`, `*Filter` and
//! `*ConfigManager` are shared with the parent view — the Workspace passes
//! ONE `systemMetricsFilter`/`systemMetricsFocus` to every per-run grid
//! (workspace.go:953-960) — so they port as `Rc<RefCell<_>>`.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::time::SystemTime;

use leet_charts::french_fries_chart::{FrenchFriesChart, FrenchFriesChartParams};
use leet_charts::french_fries_toggle_chart::{FrenchFriesToggleChart, SystemMetricChart};
use leet_charts::styles::{AdaptiveColor, french_fries_colors, graph_colors};
use leet_charts::timeseries_line_chart::{
    ColorProvider, TimeSeriesLineChart, TimeSeriesLineChartParams,
};
use leet_data::config::{COLOR_MODE_PER_SERIES, ConfigManager};
use leet_data::system_metrics::{
    MetricDef, extract_base_key, extract_series_name, match_metric_def,
};
use leet_data::width::text_width;
use ratatui::text::Text;

use crate::event::StatsMsg;
use crate::filter::{Filter, FilterMatchMode};
use crate::key::KeyEvent;
use crate::layout::{
    GoStyle, LEFT, TOP, border_style, focused_border_style, join_horizontal, join_vertical,
    nav_info_style, place, series_count_style, text_from_str, title_style,
};
use crate::metrics_grid::{GridConfigFn, blit_canvas};
use crate::panel_grid::{
    Focus, FocusType, GridDims, GridNavigator, GridSize, GridSpec, compute_grid_dims,
    effective_grid_size, items_per_page,
};

// PARITY: MinMetricChartWidth/MinMetricChartHeight live in styles.go in Go;
// the Rust styles module hosts them as i64 — cast once here so the grid math
// stays isize (panel_grid.rs convention).
pub(crate) const MIN_METRIC_CHART_WIDTH: isize =
    leet_charts::styles::MIN_METRIC_CHART_WIDTH as isize;
pub(crate) const MIN_METRIC_CHART_HEIGHT: isize =
    leet_charts::styles::MIN_METRIC_CHART_HEIGHT as isize;

/// Go stores `systemMetricChart` interface values (systemmetricchart.go).
/// `createMetricChart` only ever produces these two concrete types, so the
/// port stores an enum — Go's type switches (testhelpers.go `TestChartAt`,
/// `TestFrenchFriesChartAt`) become `match`es. The enum reuses the
/// [`SystemMetricChart`] trait hosted in leet-charts (see the DIVERGENCE
/// note in french_fries_toggle_chart.rs); it does not re-declare it.
// Charts only ever live heap-allocated behind Rc<RefCell<_>> (one allocation
// per chart, like Go's interface-boxed pointers), so the variant size skew
// costs nothing.
#[allow(clippy::large_enum_variant)]
pub enum SystemChart {
    Line(TimeSeriesLineChart),
    Toggle(FrenchFriesToggleChart),
}

impl SystemChart {
    fn as_dyn(&self) -> &dyn SystemMetricChart {
        match self {
            SystemChart::Line(c) => c,
            SystemChart::Toggle(c) => c,
        }
    }

    fn as_dyn_mut(&mut self) -> &mut dyn SystemMetricChart {
        match self {
            SystemChart::Line(c) => c,
            SystemChart::Toggle(c) => c,
        }
    }
}

/// Pure delegation so grid call sites read like Go's interface calls.
impl SystemMetricChart for SystemChart {
    fn title(&self) -> String {
        self.as_dyn().title()
    }

    fn title_detail(&mut self) -> String {
        self.as_dyn_mut().title_detail()
    }

    fn view(&mut self) -> &leet_charts::canvas::Canvas {
        self.as_dyn_mut().view()
    }

    fn resize(&mut self, width: i64, height: i64) {
        self.as_dyn_mut().resize(width, height);
    }

    fn draw_if_needed(&mut self) {
        self.as_dyn_mut().draw_if_needed();
    }

    fn park(&mut self) {
        self.as_dyn_mut().park();
    }

    fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        self.as_dyn_mut()
            .add_data_point(series_name, timestamp, value);
    }

    fn graph_width(&mut self) -> i64 {
        self.as_dyn_mut().graph_width()
    }

    fn graph_height(&mut self) -> i64 {
        self.as_dyn_mut().graph_height()
    }

    fn graph_start_x(&mut self) -> i64 {
        self.as_dyn_mut().graph_start_x()
    }

    fn graph_start_y(&mut self) -> i64 {
        self.as_dyn_mut().graph_start_y()
    }

    fn handle_zoom(&mut self, direction: &str, mouse_x: i64) {
        self.as_dyn_mut().handle_zoom(direction, mouse_x);
    }

    fn toggle_y_scale(&mut self) -> bool {
        self.as_dyn_mut().toggle_y_scale()
    }

    fn is_log_y(&self) -> bool {
        self.as_dyn().is_log_y()
    }

    fn supports_heatmap(&self) -> bool {
        self.as_dyn().supports_heatmap()
    }

    fn toggle_heatmap_mode(&mut self) -> bool {
        self.as_dyn_mut().toggle_heatmap_mode()
    }

    fn is_heatmap_mode(&self) -> bool {
        self.as_dyn().is_heatmap_mode()
    }

    fn view_mode_label(&mut self) -> String {
        self.as_dyn_mut().view_mode_label()
    }

    fn scale_label(&self) -> String {
        self.as_dyn().scale_label()
    }

    fn start_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        self.as_dyn_mut().start_inspection_at(mouse_x, mouse_y);
    }

    fn update_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        self.as_dyn_mut().update_inspection_at(mouse_x, mouse_y);
    }

    fn end_inspection(&mut self) {
        self.as_dyn_mut().end_inspection();
    }

    fn is_inspecting(&self) -> bool {
        self.as_dyn().is_inspecting()
    }

    fn inspection_data(&self) -> (f64, f64, bool) {
        self.as_dyn().inspection_data()
    }

    fn inspect_at_data_x(&mut self, target_x: f64) {
        self.as_dyn_mut().inspect_at_data_x(target_x);
    }
}

/// A shared chart handle (Go `systemMetricChart` interface value).
pub type SystemChartRef = Rc<RefCell<SystemChart>>;

/// SystemMetricsGrid manages the grid of system metric charts.
pub struct SystemMetricsGrid {
    // Configuration and logging.
    // PARITY: Go also carries an *observability.CoreLogger; the port logs via
    // `tracing` at the same call sites, so there is no logger field.
    config: Rc<RefCell<ConfigManager>>,
    grid_config: GridConfigFn,

    // Viewport dimensions.
    width: isize,
    height: isize,

    // Pagination state.
    pub(crate) nav: GridNavigator, // pub(crate): system_metrics_view reads PageBounds

    // Charts state.
    by_base_key: HashMap<String, SystemChartRef>, // baseKey -> chart
    ordered: Vec<SystemChartRef>,                 // charts sorted by title
    filtered: Vec<SystemChartRef>,                // charts matching current filter
    current_page: Vec<Vec<Option<SystemChartRef>>>, // current page view

    // Filter state.
    filter: Rc<RefCell<Filter>>,

    // Chart focus management.
    focus: Rc<RefCell<Focus>>,

    // Coloring state for per-plot mode.
    next_color: usize, // next palette index

    /// last_drawn_charts holds charts from the last visible page for parking.
    // PARITY: Go keys a map by interface value (map[systemMetricChart]struct{});
    // the port holds Rc handles and tests membership with Rc::ptr_eq — a page
    // has at most rows*cols entries.
    last_drawn_charts: Vec<SystemChartRef>,

    // synchronized inspection session state (active only between press/release)
    sync_inspect_active: bool,
}

impl SystemMetricsGrid {
    /// Port of Go `NewSystemMetricsGrid` (the logger parameter is dropped;
    /// see the struct-level PARITY note).
    pub fn new(
        width: isize,
        height: isize,
        config: Rc<RefCell<ConfigManager>>,
        grid_config: GridConfigFn,
        focus_state: Rc<RefCell<Focus>>,
        filter: Rc<RefCell<Filter>>,
    ) -> SystemMetricsGrid {
        let mut smg = SystemMetricsGrid {
            config,
            grid_config,
            width,
            height,
            nav: GridNavigator::default(),
            by_base_key: HashMap::new(),
            ordered: Vec::new(),
            filtered: Vec::new(),
            current_page: Vec::new(),
            filter,
            focus: focus_state,
            next_color: 0,
            last_drawn_charts: Vec::new(),
            sync_inspect_active: false,
        };

        let size = smg.effective_grid_size();
        smg.current_page = vec![vec![None; size.cols.max(0) as usize]; size.rows.max(0) as usize];

        tracing::debug!(
            "SystemMetricsGrid: created with dimensions {width}x{height} (grid {}x{})",
            size.rows,
            size.cols
        );

        smg
    }

    /// calculateChartDimensions computes dimensions for system metric charts.
    // pub(crate): the right sidebar's mouse mapping reads the grid dims
    // (rightsidebar.go — same package in Go).
    pub(crate) fn calculate_chart_dimensions(&self) -> GridDims {
        let (cfg_rows, cfg_cols) = (self.grid_config)();
        compute_grid_dims(
            self.width,
            self.height,
            GridSpec {
                rows: cfg_rows as isize,
                cols: cfg_cols as isize,
                min_cell_w: MIN_METRIC_CHART_WIDTH,
                min_cell_h: MIN_METRIC_CHART_HEIGHT,
                header_lines: 0,
            },
        )
    }

    /// effectiveGridSize returns the grid size that can fit in the current viewport.
    pub(crate) fn effective_grid_size(&self) -> GridSize {
        let (cfg_rows, cfg_cols) = (self.grid_config)();
        effective_grid_size(
            self.width,
            self.height,
            GridSpec {
                rows: cfg_rows as isize,
                cols: cfg_cols as isize,
                min_cell_w: MIN_METRIC_CHART_WIDTH,
                min_cell_h: MIN_METRIC_CHART_HEIGHT,
                header_lines: 0,
            },
        )
    }

    /// nextPaletteColor returns the next color from the active system palette.
    fn next_palette_color(&mut self) -> AdaptiveColor {
        let palette = {
            let cfg = self.config.borrow();
            graph_colors(cfg.system_color_scheme())
        };
        let color = palette[self.next_color % palette.len()];
        self.next_color += 1;
        color
    }

    /// anchoredSeriesColorProvider returns a provider that yields colors
    /// relative to a given base index in the current palette.
    ///
    /// The first call returns the color after the base color,
    /// so the base can be used for the first series.
    fn anchored_series_color_provider(&self, base_idx: usize) -> ColorProvider {
        let palette = {
            let cfg = self.config.borrow();
            graph_colors(cfg.system_color_scheme())
        };
        let mut idx = base_idx + 1;
        Box::new(move || {
            let c = palette[idx % palette.len()];
            idx += 1;
            c
        })
    }

    /// createMetricChart creates a time series chart for a system metric.
    fn create_metric_chart(&mut self, def: &'static MetricDef) -> SystemChart {
        let dims = self.calculate_chart_dimensions();
        let chart_width = dims.cell_w.max(MIN_METRIC_CHART_WIDTH);
        let chart_height = dims.cell_h.max(MIN_METRIC_CHART_HEIGHT);

        tracing::debug!(
            "systemmetricsgrid: creating chart {chart_width}x{chart_height} for {def:?}"
        );

        // Base color by color mode.
        let color_mode = self.config.borrow().system_color_mode().to_string();
        let palette = {
            let cfg = self.config.borrow();
            graph_colors(cfg.system_color_scheme())
        };
        let base_color: AdaptiveColor;
        let mut base_idx: usize = 0;
        if color_mode == COLOR_MODE_PER_SERIES {
            base_color = palette[0];
        } else {
            base_color = self.next_palette_color();
            base_idx = (self.next_color - 1) % palette.len();
        }

        let now = SystemTime::now();
        let mut line_chart = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: chart_width as i64,
            height: chart_height as i64,
            // PARITY: Go stores the shared *MetricDef; the params struct
            // takes an owned def, cloned at this boundary.
            def: def.clone(),
            base_color,
            color_provider: Some(self.anchored_series_color_provider(base_idx)),
            now,
        });
        line_chart.set_tail_window(self.config.borrow().system_tail_window());

        if !def.percentage {
            return SystemChart::Line(line_chart);
        }

        let french_fries_chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: chart_width as i64,
            height: chart_height as i64,
            def,
            colors: french_fries_colors(self.config.borrow().french_fries_color_scheme()),
            now,
        });
        SystemChart::Toggle(FrenchFriesToggleChart::new(line_chart, french_fries_chart))
    }

    /// AddDataPoint adds a new data point to the appropriate metric chart.
    ///
    /// Drawing is deferred to the next View() call to avoid redundant redraws
    /// when processing a batch of metrics from a single stats record.
    pub fn add_data_point(&mut self, metric_name: &str, timestamp: i64, value: f64) {
        if self.add_data_point_inner(metric_name, timestamp, value) {
            self.refresh_chart_set();
        }
    }

    /// ProcessStats ingests all metrics from a single stats record, batching
    /// any chart creation/filtering/redraw work.
    pub fn process_stats(&mut self, msg: &StatsMsg) {
        if msg.metrics.is_empty() {
            return;
        }

        let mut chart_set_changed = false;
        // PARITY: Go iterates unordered here; sorted for determinism. Chart
        // order never depends on it (addChart re-sorts by title), but in
        // per-plot color mode the chart creation order assigns palette
        // colors, so the unsorted range order reaches the screen — a latent
        // Go bug (random map order).
        let mut metrics: Vec<(&str, f64)> = msg
            .metrics
            .iter()
            .map(|(name, value)| (name.as_str(), *value))
            .collect();
        metrics.sort_unstable_by_key(|&(name, _)| name);
        for (metric_name, value) in metrics {
            if self.add_data_point_inner(metric_name, msg.timestamp, value) {
                chart_set_changed = true;
            }
        }
        if chart_set_changed {
            self.refresh_chart_set();
        }
    }

    /// addDataPoint adds a sample and reports whether the chart set changed.
    // PARITY: Go's unexported `addDataPoint` twin of `AddDataPoint`; both
    // collapse to the same snake_case name, so the inner one is suffixed.
    fn add_data_point_inner(&mut self, metric_name: &str, timestamp: i64, value: f64) -> bool {
        tracing::debug!(
            "SystemMetricsGrid.AddDataPoint: metric={metric_name}, timestamp={timestamp}, value={value}"
        );

        let Some(def) = match_metric_def(metric_name) else {
            tracing::debug!(
                "SystemMetricsGrid.AddDataPoint: no definition for metric={metric_name}"
            );
            return false;
        };

        let base_key = extract_base_key(metric_name);
        let series_name = extract_series_name(metric_name);

        let (chart, created) = self.get_or_create_chart(&base_key, def);
        chart
            .borrow_mut()
            .add_data_point(&series_name, timestamp, value);
        created
    }

    /// getOrCreateChart returns a chart for the given baseKey.
    fn get_or_create_chart(
        &mut self,
        base_key: &str,
        def: &'static MetricDef,
    ) -> (SystemChartRef, bool) {
        if let Some(chart) = self.by_base_key.get(base_key) {
            return (Rc::clone(chart), false);
        }
        tracing::debug!("systemmetricsgrid: creating new chart for baseKey={base_key}");
        let chart = Rc::new(RefCell::new(self.create_metric_chart(def)));
        self.by_base_key
            .insert(base_key.to_string(), Rc::clone(&chart));
        self.add_chart(Rc::clone(&chart));
        (chart, true)
    }

    /// addChart adds a chart to the ordered list.
    fn add_chart(&mut self, chart: SystemChartRef) {
        self.ordered.push(chart);
        // PARITY: Go sort.Slice is UNSTABLE — charts with equal titles (two
        // base keys matching defs with the same display name) could reorder
        // arbitrarily there; the stable sort here is deterministic
        // (PORTING.md sorting rule).
        self.ordered.sort_by_key(|c| c.borrow().title());

        tracing::debug!(
            "SystemMetricsGrid.addChart: chart added, total={}",
            self.ordered.len()
        );
    }

    fn refresh_chart_set(&mut self) {
        self.apply_filter();
        self.draw_visible();
    }

    /// LoadCurrentPage loads charts for the current page.
    pub fn load_current_page(&mut self) {
        let size = self.effective_grid_size();

        // Reallocate if dimensions changed or clear existing page.
        if self.current_page.len() != size.rows.max(0) as usize
            || (!self.current_page.is_empty()
                && self.current_page[0].len() != size.cols.max(0) as usize)
        {
            self.current_page =
                vec![vec![None; size.cols.max(0) as usize]; size.rows.max(0) as usize];
        } else {
            for row in self.current_page.iter_mut() {
                for cell in row.iter_mut() {
                    *cell = None;
                }
            }
        }

        let (start_idx, end_idx) = self
            .nav
            .page_bounds(self.filtered.len() as isize, items_per_page(size));

        let mut idx = start_idx;
        'fill: for row in 0..size.rows.max(0) as usize {
            for col in 0..size.cols.max(0) as usize {
                if idx >= end_idx {
                    break 'fill;
                }
                self.current_page[row][col] = Some(Rc::clone(&self.filtered[idx as usize]));
                idx += 1;
            }
        }

        self.sync_focus_to_current_page();
    }

    /// Navigate changes pages.
    pub fn navigate(&mut self, direction: isize) {
        if !self.nav.navigate(direction) {
            return;
        }

        self.clear_focus();
        self.load_current_page();
        self.draw_visible();
        self.navigate_focus(0, 0);
    }

    /// NavigateHome jumps to the first page.
    pub fn navigate_home(&mut self) {
        if !self.nav.go_home() {
            return;
        }

        self.clear_focus();
        self.load_current_page();
        self.draw_visible();
        self.navigate_focus(0, 0);
    }

    /// NavigateEnd jumps to the last page.
    pub fn navigate_end(&mut self) {
        if !self.nav.go_end() {
            return;
        }

        self.clear_focus();
        self.load_current_page();
        self.draw_visible();
        self.navigate_focus(0, 0);
    }

    /// HandleMouseClick handles mouse clicks for chart selection.
    ///
    /// Returns a bool indicating whether an element was focused.
    pub fn handle_mouse_click(&self, row: isize, col: isize) -> bool {
        tracing::debug!("systemmetricsgrid: HandleMouseClick: row={row}, col={col}");

        {
            let f = self.focus.borrow();
            if f.focus_type == FocusType::SystemChart && row == f.row && col == f.col {
                tracing::debug!(
                    "systemmetricsgrid: HandleMouseClick: clicking on focused chart - unfocusing"
                );
                drop(f);
                self.clear_focus();
                return false;
            }
        }

        self.set_focus(row, col)
    }

    fn set_focus(&self, row: isize, col: isize) -> bool {
        let size = self.effective_grid_size();
        if row < 0
            || row >= size.rows
            || col < 0
            || col >= size.cols
            || row as usize >= self.current_page.len()
            || col as usize >= self.current_page[row as usize].len()
        {
            return false;
        }
        let Some(chart) = &self.current_page[row as usize][col as usize] else {
            return false;
        };

        let title = chart.borrow().title();
        self.clear_focus();
        self.focus
            .borrow_mut()
            .set(FocusType::SystemChart, row, col, title);
        true
    }

    /// NavigateFocus moves chart focus by (dr, dc) within the current page.
    /// On partial pages, vertical moves clamp to the last populated cell in
    /// the target row.
    ///
    /// Returns true if focus changed or was re-materialized.
    pub fn navigate_focus(&self, dr: isize, dc: isize) -> bool {
        if self.current_page.is_empty() {
            return false;
        }

        let (mut row, mut col) = {
            let f = self.focus.borrow();
            (f.row, f.col)
        };
        if self.focused_chart().is_none() {
            let Some((r, c)) = self.first_non_nil_cell() else {
                return false;
            };
            row = r;
            col = c;
        }

        let new_row = clamp(row + dr, 0, self.current_page.len() as isize - 1);
        let last_col = self.last_non_nil_col(new_row);
        if last_col < 0 {
            return false;
        }

        let new_col = clamp(col + dc, 0, last_col);
        let Some(chart) = &self.current_page[new_row as usize][new_col as usize] else {
            return false;
        };

        {
            let f = self.focus.borrow();
            if f.focus_type == FocusType::SystemChart
                && f.row == new_row
                && f.col == new_col
                && f.title == chart.borrow().title()
            {
                return false;
            }
        }

        self.set_focus(new_row, new_col)
    }

    // PARITY: Go returns (int, int, bool); the bool is `Some` here.
    fn first_non_nil_cell(&self) -> Option<(isize, isize)> {
        for (r, cells) in self.current_page.iter().enumerate() {
            for (c, ch) in cells.iter().enumerate() {
                if ch.is_some() {
                    return Some((r as isize, c as isize));
                }
            }
        }
        None
    }

    fn last_non_nil_col(&self, row: isize) -> isize {
        // PARITY: Go only guards row >= len (negative rows cannot reach it);
        // the usize cast needs the explicit `row < 0` arm.
        if row < 0 || row as usize >= self.current_page.len() {
            return -1;
        }
        let cells = &self.current_page[row as usize];
        let mut c = cells.len() as isize - 1;
        while c >= 0 {
            if cells[c as usize].is_some() {
                return c;
            }
            c -= 1;
        }
        -1
    }

    /// ClearFocus removes focus from all charts.
    pub fn clear_focus(&self) {
        let mut f = self.focus.borrow_mut();
        if f.focus_type == FocusType::SystemChart {
            f.reset();
        }
    }

    /// FocusedChartTitle returns the title of the focused chart.
    pub fn focused_chart_title(&self) -> String {
        let f = self.focus.borrow();
        if f.focus_type == FocusType::SystemChart {
            return f.title.clone();
        }
        String::new()
    }

    /// FocusedChartViewModeLabel returns a short description of the focused
    /// chart's X-axis mode.
    pub fn focused_chart_view_mode_label(&self) -> String {
        let Some(chart) = self.focused_chart() else {
            return String::new();
        };
        chart.borrow_mut().view_mode_label()
    }

    pub fn focused_chart_scale_label(&self) -> String {
        let Some(chart) = self.focused_chart() else {
            return String::new();
        };
        chart.borrow().scale_label()
    }

    pub fn focused_chart_title_detail(&self) -> String {
        let Some(chart) = self.focused_chart() else {
            return String::new();
        };
        chart.borrow_mut().title_detail()
    }

    fn focused_chart(&self) -> Option<SystemChartRef> {
        let f = self.focus.borrow();
        if f.focus_type != FocusType::SystemChart || f.row < 0 || f.col < 0 {
            return None;
        }
        if f.row as usize >= self.current_page.len()
            || f.col as usize >= self.current_page[f.row as usize].len()
        {
            return None;
        }
        self.current_page[f.row as usize][f.col as usize].clone()
    }

    // PHASE-5/6: called by the run/workspace/symon 'l' key handlers
    // (runhandlers.go, workspacehandlers.go, symon.go).
    #[allow(dead_code)]
    pub(crate) fn toggle_focused_chart_log_y(&self) -> bool {
        let Some(chart) = self.focused_chart() else {
            return false;
        };
        if !chart.borrow_mut().toggle_y_scale() {
            return false;
        }
        chart.borrow_mut().draw_if_needed();
        true
    }

    // PHASE-5/6: called by the run/workspace/symon heatmap key handlers.
    #[allow(dead_code)]
    pub(crate) fn toggle_focused_chart_heatmap_mode(&self) -> bool {
        let Some(chart) = self.focused_chart() else {
            return false;
        };
        if !chart.borrow().supports_heatmap() || !chart.borrow_mut().toggle_heatmap_mode() {
            return false;
        }
        chart.borrow_mut().draw_if_needed();
        true
    }

    // PHASE-5/6: called by the run/workspace/symon 'y' key handlers
    // (mode cycle: linear -> log -> heatmap -> linear for % metrics).
    #[allow(dead_code)]
    pub(crate) fn cycle_focused_chart_mode(&self) -> bool {
        let Some(chart) = self.focused_chart() else {
            return false;
        };

        if !chart.borrow().supports_heatmap() {
            if !chart.borrow_mut().toggle_y_scale() {
                return false;
            }
            chart.borrow_mut().draw_if_needed();
            return true;
        }

        if chart.borrow().is_heatmap_mode() {
            if !chart.borrow_mut().toggle_heatmap_mode() {
                return false;
            }
            if chart.borrow().is_log_y() {
                chart.borrow_mut().toggle_y_scale();
            }
            chart.borrow_mut().draw_if_needed();
            return true;
        }

        if chart.borrow().is_log_y() {
            if !chart.borrow_mut().toggle_heatmap_mode() {
                return false;
            }
            chart.borrow_mut().draw_if_needed();
            return true;
        }

        if chart.borrow_mut().toggle_y_scale() {
            chart.borrow_mut().draw_if_needed();
            return true;
        }
        if chart.borrow_mut().toggle_heatmap_mode() {
            chart.borrow_mut().draw_if_needed();
            return true;
        }
        false
    }

    /// Resize updates viewport dimensions and resizes/redraws visible charts.
    pub fn resize(&mut self, width: isize, height: isize) {
        if width <= 0 || height <= 0 {
            tracing::debug!(
                "systemmetricsgrid: Resize: invalid dimensions {width}x{height}, skipping"
            );
            return;
        }

        self.width = width;
        self.height = height;

        let dims = self.calculate_chart_dimensions();
        if dims.cell_w <= 0
            || dims.cell_h <= 0
            || dims.cell_w < MIN_METRIC_CHART_WIDTH
            || dims.cell_h < MIN_METRIC_CHART_HEIGHT
        {
            tracing::debug!(
                "systemmetricsgrid: Resize: calculated dimensions {}x{} invalid, skipping",
                dims.cell_w,
                dims.cell_h
            );
            return;
        }

        let size = self.effective_grid_size();
        self.nav
            .update_total_pages(self.filtered.len() as isize, items_per_page(size));
        self.load_current_page();
        self.draw_visible();
    }

    /// drawVisible resizes and draws charts on the current page.
    ///
    /// Charts no longer visible are parked to reduce memory usage.
    fn draw_visible(&mut self) {
        let dims = self.calculate_chart_dimensions();

        let mut current_charts: Vec<SystemChartRef> = Vec::new();
        for row in &self.current_page {
            for cell in row.iter().flatten() {
                if !current_charts.iter().any(|c| Rc::ptr_eq(c, cell)) {
                    current_charts.push(Rc::clone(cell));
                }
            }
        }

        let last_drawn_charts =
            std::mem::replace(&mut self.last_drawn_charts, current_charts.clone());
        for ch in &last_drawn_charts {
            let still_visible = current_charts.iter().any(|c| Rc::ptr_eq(c, ch));
            if !still_visible {
                ch.borrow_mut().park();
            }
        }

        // PARITY: Go iterates the chart set map unordered; resize/draw order
        // is not observable.
        for ch in &current_charts {
            let mut chart = ch.borrow_mut();
            chart.resize(dims.cell_w as i64, dims.cell_h as i64);
            chart.draw_if_needed();
        }
    }

    fn sync_focus_to_current_page(&self) {
        let (row, col, title) = {
            let f = self.focus.borrow();
            if f.focus_type != FocusType::SystemChart || f.title.is_empty() {
                return;
            }
            (f.row, f.col, f.title.clone())
        };

        // If the chart at the current position still matches, keep it.
        // This avoids jumping when multiple charts share the same title.
        if row >= 0
            && col >= 0
            && (row as usize) < self.current_page.len()
            && (col as usize) < self.current_page[row as usize].len()
            && let Some(ch) = &self.current_page[row as usize][col as usize]
            && ch.borrow().title() == title
        {
            return;
        }

        // Position changed (e.g. chart order shifted) — scan by title.
        for (r, cells) in self.current_page.iter().enumerate() {
            for (c, cell) in cells.iter().enumerate() {
                if let Some(ch) = cell
                    && ch.borrow().title() == title
                {
                    let mut f = self.focus.borrow_mut();
                    f.row = r as isize;
                    f.col = c as isize;
                    return;
                }
            }
        }

        // Focused chart is not visible on this page.
        self.clear_focus();
    }

    /// View renders the system metrics grid.
    ///
    /// Dirty visible charts are drawn before rendering so that data added
    /// since the last frame is reflected without per-point draw overhead.
    ///
    /// `dark` resolves adaptive colors (Go reads the `darkBackground`
    /// package global at render time; see layout.rs module doc).
    pub fn view(&self, dark: bool) -> Text<'static> {
        let dims = self.calculate_chart_dimensions();
        let size = self.effective_grid_size();

        // Draw any visible charts that received new data since the last frame.
        for row in &self.current_page {
            for cell in row.iter().flatten() {
                cell.borrow_mut().draw_if_needed();
            }
        }

        let mut rows: Vec<Text<'static>> = Vec::new();
        for row in 0..size.rows {
            let mut cols: Vec<Text<'static>> = Vec::new();
            for col in 0..size.cols {
                // PARITY: Go indexes currentPage[row][col] directly here
                // (out-of-range panics if the page lags the grid size); the
                // port keeps the same indexing.
                // Empty cell.
                if self.current_page[row as usize][col as usize].is_none() {
                    cols.push(
                        GoStyle::new()
                            .width(dims.cell_w_with_padding as i64)
                            .height(dims.cell_h_with_padding as i64)
                            .render(""),
                    );
                    continue;
                }

                let metric_chart = self.current_page[row as usize][col as usize]
                    .as_ref()
                    .expect("checked above");
                // Go `metricChart.View()` — the chart's canvas, blitted.
                let chart_view = {
                    let mut ch = metric_chart.borrow_mut();
                    blit_canvas(ch.view())
                };

                let rendered_title =
                    render_system_metric_chart_title(metric_chart, dims.cell_w, dark);

                let box_content = join_vertical(LEFT, vec![rendered_title, chart_view]);
                let mut box_style = border_style(dark);
                {
                    let f = self.focus.borrow();
                    if f.focus_type == FocusType::SystemChart && row == f.row && col == f.col {
                        box_style = focused_border_style(dark);
                    }
                }
                let boxed = box_style.render_text(box_content);
                let cell = place(
                    dims.cell_w_with_padding as i64,
                    dims.cell_h_with_padding as i64,
                    LEFT,
                    TOP,
                    boxed,
                );
                cols.push(cell);
            }
            let row_view = join_horizontal(LEFT, cols);
            rows.push(row_view);
        }

        let mut grid = join_vertical(LEFT, rows);

        // Bottom filler.
        let used = size.rows * dims.cell_h_with_padding;
        let extra = self.height - used;
        if extra > 0 {
            let filler = GoStyle::new().height(extra as i64).render("");
            grid = join_vertical(LEFT, vec![grid, filler]);
        }

        grid
    }

    /// ChartCount returns the number of charts on the grid.
    pub fn chart_count(&self) -> usize {
        self.ordered.len()
    }

    /// hitChartAndRelX returns the chart under (row, col) on the grid
    /// with relative graph-local X.
    ///
    /// The bool is Go's `needFocus` (this chart differs from current focus);
    /// `None` is Go's `ok == false` (row/col doesn't map to a visible chart).
    fn hit_chart_and_rel_x(
        &self,
        adjusted_x: isize,
        row: isize,
        col: isize,
        dims: GridDims,
    ) -> Option<(SystemChartRef, isize, bool)> {
        let (chart, rel_x, _, need_focus) =
            self.hit_chart_and_rel_pos(adjusted_x, 0, row, col, dims)?;
        Some((chart, rel_x, need_focus))
    }

    /// hitChartAndRelPos returns the chart under (row, col) on the grid
    /// with relative graph-local coordinates.
    fn hit_chart_and_rel_pos(
        &self,
        adjusted_x: isize,
        adjusted_y: isize,
        row: isize,
        col: isize,
        dims: GridDims,
    ) -> Option<(SystemChartRef, isize, isize, bool)> {
        let size = self.effective_grid_size();
        if row < 0
            || row >= size.rows
            || col < 0
            || col >= size.cols
            || row as usize >= self.current_page.len()
            || col as usize >= self.current_page[row as usize].len()
        {
            return None;
        }
        let chart = self.current_page[row as usize][col as usize].clone()?;

        let chart_start_x = col * dims.cell_w_with_padding;
        let chart_start_y = row * dims.cell_h_with_padding;
        let (graph_start_x, graph_start_y) = {
            let mut ch = chart.borrow_mut();
            (ch.graph_start_x(), ch.graph_start_y())
        };
        let rel_x = adjusted_x - (chart_start_x + graph_start_x as isize);
        let rel_y = adjusted_y - (chart_start_y + graph_start_y as isize);

        let need_focus = {
            let f = self.focus.borrow();
            f.focus_type != FocusType::SystemChart || f.row != row || f.col != col
        };
        Some((chart, rel_x, rel_y, need_focus))
    }

    /// HandleWheel performs zoom handling on a system chart at (row, col).
    pub fn handle_wheel(
        &self,
        adjusted_x: isize,
        row: isize,
        col: isize,
        dims: GridDims,
        wheel_up: bool,
    ) {
        // PARITY: Go also checks `chart == nil`; `ok` implies non-nil here.
        let Some((chart, rel_x, need_focus)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims)
        else {
            return;
        };
        if rel_x < 0 || rel_x as i64 >= chart.borrow_mut().graph_width() {
            return;
        }
        if need_focus {
            self.set_focus(row, col);
        }

        let mut direction = "out";
        if wheel_up {
            direction = "in";
        }
        chart.borrow_mut().handle_zoom(direction, rel_x as i64);
        chart.borrow_mut().draw_if_needed();
    }

    /// StartInspection focuses the chart and begins inspection if inside the
    /// graph.
    ///
    /// If synced is true (Alt+right-press), a synchronized inspection session
    /// starts: the anchor X from the focused chart is broadcast to all
    /// visible charts.
    pub fn start_inspection(
        &mut self,
        adjusted_x: isize,
        adjusted_y: isize,
        row: isize,
        col: isize,
        dims: GridDims,
        synced: bool,
    ) {
        let Some((chart, rel_x, rel_y, need_focus)) =
            self.hit_chart_and_rel_pos(adjusted_x, adjusted_y, row, col, dims)
        else {
            return;
        };
        {
            let mut ch = chart.borrow_mut();
            if rel_x < -2
                || rel_x as i64 > ch.graph_width() + 1
                || rel_y < -2
                || rel_y as i64 > ch.graph_height() + 1
            {
                return;
            }
        }
        if need_focus {
            self.set_focus(row, col);
        }

        {
            let mut ch = chart.borrow_mut();
            ch.start_inspection_at(rel_x as i64, rel_y as i64);
            ch.draw_if_needed();
        }

        if !synced {
            return;
        }

        let (x, _, active) = chart.borrow().inspection_data();
        if active {
            self.sync_inspect_active = true;
            self.broadcast_inspect_at_data_x(x);
        }
    }

    /// UpdateInspection updates the crosshair position on the focused chart.
    ///
    /// If a synchronized inspection session is active, broadcasts the
    /// position to all visible charts on the current page.
    pub fn update_inspection(
        &mut self,
        adjusted_x: isize,
        adjusted_y: isize,
        row: isize,
        col: isize,
        dims: GridDims,
    ) {
        let Some((chart, rel_x, rel_y, _)) =
            self.hit_chart_and_rel_pos(adjusted_x, adjusted_y, row, col, dims)
        else {
            return;
        };
        if !chart.borrow().is_inspecting() {
            return;
        }

        {
            let mut ch = chart.borrow_mut();
            ch.update_inspection_at(rel_x as i64, rel_y as i64);
            ch.draw_if_needed();
        }

        if self.sync_inspect_active {
            let (x, _, active) = chart.borrow().inspection_data();
            if active {
                self.broadcast_inspect_at_data_x(x);
            }
        }
    }

    /// EndInspection clears inspection mode.
    ///
    /// If a synchronized session is active, clears inspection on all visible
    /// charts; otherwise clears only the focused chart.
    pub fn end_inspection(&mut self) {
        if self.sync_inspect_active {
            self.broadcast_end_inspection();
            self.sync_inspect_active = false;
            return;
        }

        let Some(chart) = self.focused_chart() else {
            return;
        };
        chart.borrow_mut().end_inspection();
        chart.borrow_mut().draw_if_needed();
    }

    /// broadcastInspectAtDataX applies InspectAtDataX to all visible charts
    /// on the current page.
    fn broadcast_inspect_at_data_x(&self, anchor_x: f64) {
        for row in &self.current_page {
            for chart in row.iter().flatten() {
                chart.borrow_mut().inspect_at_data_x(anchor_x);
                chart.borrow_mut().draw_if_needed();
            }
        }
    }

    /// broadcastEndInspection clears inspection on all visible charts on the
    /// current page.
    fn broadcast_end_inspection(&self) {
        for row in &self.current_page {
            for chart in row.iter().flatten() {
                if chart.borrow().is_inspecting() {
                    chart.borrow_mut().end_inspection();
                    chart.borrow_mut().draw_if_needed();
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // systemmetricsfilter.go — the SystemMetricsGrid filter methods.
    // -----------------------------------------------------------------------

    /// ApplyFilter applies the current filter pattern to system metric charts.
    // PARITY: Go's nil-receiver / nil-filter guard is unrepresentable here.
    pub fn apply_filter(&mut self) {
        // PARITY: Go reuses g.filtered's backing array via `g.filtered[:0]`.
        let matcher = self.filter.borrow().matcher();
        let mut filtered = std::mem::take(&mut self.filtered);
        filtered.clear();
        for ch in &self.ordered {
            if matcher(&ch.borrow().title()) {
                filtered.push(Rc::clone(ch));
            }
        }
        self.filtered = filtered;

        let size = self.effective_grid_size();
        self.nav
            .update_total_pages(self.filtered.len() as isize, items_per_page(size));
        self.load_current_page();
        self.draw_visible();
    }

    /// FilteredChartCount returns the number of charts matching the current
    /// filter.
    pub fn filtered_chart_count(&self) -> usize {
        self.filtered.len()
    }

    /// EnterFilterMode enters filter input mode.
    pub fn enter_filter_mode(&mut self) {
        self.filter.borrow_mut().activate();
    }

    /// UpdateFilterDraft updates the in-progress filter text (for live
    /// preview).
    pub fn update_filter_draft(&mut self, msg: &KeyEvent) {
        self.filter.borrow_mut().update_draft(msg);
    }

    /// ExitFilterMode exits filter input mode and optionally applies the
    /// filter.
    pub fn exit_filter_mode(&mut self, apply: bool) {
        if apply {
            self.filter.borrow_mut().commit();
        } else {
            self.filter.borrow_mut().cancel();
        }
        self.apply_filter();
    }

    /// ClearFilter removes the active filter.
    pub fn clear_filter(&mut self) {
        self.filter.borrow_mut().clear();
        self.apply_filter();
    }

    /// ToggleFilterMatchMode flips regex <-> glob and reapplies current
    /// preview/applied.
    pub fn toggle_filter_match_mode(&mut self) {
        self.filter.borrow_mut().toggle_mode();
        self.apply_filter();
    }

    /// FilterMode exposes the current filter match mode.
    pub fn filter_mode(&self) -> FilterMatchMode {
        self.filter.borrow().mode()
    }

    /// IsFilterMode reports whether we are currently typing a filter.
    pub fn is_filter_mode(&self) -> bool {
        self.filter.borrow().is_active()
    }

    /// IsFiltering reports whether we have an applied filter (not just input
    /// mode).
    pub fn is_filtering(&self) -> bool {
        let f = self.filter.borrow();
        !f.is_active() && !f.query().is_empty()
    }

    /// FilterQuery returns the current filter pattern (draft if active,
    /// applied otherwise).
    // PARITY: Go returns the string handle; the RefCell forces a clone.
    pub fn filter_query(&self) -> String {
        self.filter.borrow().query().to_string()
    }

    /// handleFilterKey processes a key event while the system metrics filter
    /// is active.
    // PHASE-5/6: called by the workspace/symon key handlers while filter mode
    // is active (workspacehandlers.go, symon.go).
    #[allow(dead_code)]
    pub(crate) fn handle_filter_key(&mut self, msg: &KeyEvent) {
        let changed = self.filter.borrow_mut().handle_key(msg);
        if changed {
            self.apply_filter();
        }
    }
}

#[derive(Default)]
struct SystemMetricHeaderExtras {
    detail: String,
    mode: String,
}

fn render_system_metric_chart_title(
    chart: &SystemChartRef,
    max_width: isize,
    dark: bool,
) -> Text<'static> {
    // PARITY: Go also nil-checks the chart — unrepresentable here.
    if max_width <= 0 {
        return text_from_str("");
    }

    let extras = chart_header_extras(chart);
    let mut show_detail = !extras.detail.is_empty();
    let mut show_mode = !extras.mode.is_empty();
    loop {
        let mut suffix_width: isize = 0;
        if show_detail {
            suffix_width += text_width(&extras.detail) as isize;
        }
        if show_mode {
            suffix_width += text_width(&extras.mode) as isize;
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

    let mut suffix_width: isize = 0;
    if show_detail {
        suffix_width += text_width(&extras.detail) as isize;
    }
    if show_mode {
        suffix_width += text_width(&extras.mode) as isize;
    }
    let title_width = (max_width - suffix_width).max(1);
    // Go builds the label by string concatenation of one-line renders.
    let mut parts = vec![
        title_style(dark).render(&leet_charts::epoch_line_chart::truncate_title(
            &chart.borrow().title(),
            title_width as i64,
        )),
    ];
    if show_detail {
        parts.push(series_count_style(dark).render(&extras.detail));
    }
    if show_mode {
        parts.push(nav_info_style(dark).render(&extras.mode));
    }
    join_horizontal(LEFT, parts)
}

fn chart_header_extras(chart: &SystemChartRef) -> SystemMetricHeaderExtras {
    let mut extras = SystemMetricHeaderExtras::default();
    let detail = chart.borrow_mut().title_detail();
    if !detail.is_empty() {
        extras.detail = format!(" {detail}");
    }
    let ch = chart.borrow();
    if ch.is_heatmap_mode() {
        extras.mode = " [heatmap]".to_string();
    } else if ch.is_log_y() {
        extras.mode = " [log]".to_string();
    }
    extras
}

/// Port of Go `clamp` (config.go:322; package-level in Go, module-local in
/// each Rust caller).
fn clamp(val: isize, minimum: isize, maximum: isize) -> isize {
    if val < minimum {
        return minimum;
    }
    if val > maximum {
        return maximum;
    }
    val
}

// Transliteration of `systemmetricsgrid_test.go`, `systemmetricsfilter_test.go`
// and the three deferred TestSystemMetricsGrid_* cases from
// `frenchfrieschart_test.go:149-245` (PARITY.md §5.2).
#[cfg(test)]
mod tests {
    use std::time::UNIX_EPOCH;

    use leet_charts::canvas::Point;
    use leet_charts::styles::{Rgb, default_dark_background};

    use super::*;
    use crate::key::{KeyCode, KeyMods};
    use crate::layout::text_to_string;

    /// Shared setup: Go's `NewConfigManager(filepath.Join(t.TempDir(), ...))`
    /// plus the two grid-shape setters. Returns the TempDir too so the config
    /// path outlives the grid (Go's `t.TempDir()` lives for the test).
    fn test_config(rows: i64, cols: i64) -> (Rc<RefCell<ConfigManager>>, tempfile::TempDir) {
        let dir = tempfile::tempdir().expect("tempdir");
        let cfg = Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )));
        // Go: `_, _ = cfg.SetSystemRows(rows), cfg.SetSystemCols(cols)`
        // (errors deliberately ignored).
        let _ = cfg.borrow_mut().set_system_rows(rows);
        let _ = cfg.borrow_mut().set_system_cols(cols);
        (cfg, dir)
    }

    /// Go `leet.NewSystemMetricsGrid(width, height, cfg, cfg.SystemGrid,
    /// leet.NewFocus(), leet.NewFilter(), logger)`.
    fn new_grid(
        width: isize,
        height: isize,
        cfg: &Rc<RefCell<ConfigManager>>,
    ) -> SystemMetricsGrid {
        // Go passes the method value cfg.SystemGrid.
        let grid_config: GridConfigFn = {
            let cfg = Rc::clone(cfg);
            Box::new(move || cfg.borrow().system_grid())
        };
        SystemMetricsGrid::new(
            width,
            height,
            Rc::clone(cfg),
            grid_config,
            Rc::new(RefCell::new(Focus::new())),
            Rc::new(RefCell::new(Filter::new())),
        )
    }

    // Go `typeString` (over the ComponentWithContentFilter interface; only
    // the system metrics grid is exercised here).
    fn type_string(grid: &mut SystemMetricsGrid, s: &str) {
        for r in s.chars() {
            grid.update_filter_draft(&KeyEvent {
                code: KeyCode::Char(r),
                text: Some(r.to_string()),
                mods: KeyMods::NONE,
            });
        }
    }

    /// Go `time.Now().Unix()`.
    fn now_unix() -> i64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock before epoch")
            .as_secs() as i64
    }

    /// Go `SystemMetricsGrid.TestCurrentPage` (testhelpers.go:191): the
    /// current grid of charts, keeping only `*TimeSeriesLineChart` cells
    /// (the Go type assertion yields nil for toggle charts). testhelpers.go
    /// is not ported; in-module tests read `current_page` directly
    /// (PORTING.md testhelpers policy).
    fn test_current_page(grid: &SystemMetricsGrid) -> Vec<Vec<Option<SystemChartRef>>> {
        grid.current_page
            .iter()
            .map(|row| {
                row.iter()
                    .map(|cell| {
                        cell.as_ref().and_then(|ch| match &*ch.borrow() {
                            SystemChart::Line(_) => Some(Rc::clone(ch)),
                            SystemChart::Toggle(_) => None,
                        })
                    })
                    .collect()
            })
            .collect()
    }

    /// Go `SystemMetricsGrid.TestHeatmapModeAt` (testhelpers.go:237).
    fn test_heatmap_mode_at(grid: &SystemMetricsGrid, row: isize, col: isize) -> bool {
        if row < 0
            || row as usize >= grid.current_page.len()
            || col < 0
            || col as usize >= grid.current_page[row as usize].len()
        {
            return false;
        }
        match &grid.current_page[row as usize][col as usize] {
            Some(chart) => chart.borrow().is_heatmap_mode(),
            None => false,
        }
    }

    /// Go `SystemMetricsGrid.TestChartAt(row, col).IsLogY()` — the
    /// testhelpers.go:205 type switch reaches the toggle chart's inner
    /// *TimeSeriesLineChart. `FrenchFriesToggleChart.line` is private
    /// cross-crate, so in heatmap mode (where the toggle's IsLogY lies and
    /// returns false, frenchfriestogglechart.go:102-107) the probe flips
    /// heatmap mode off — a raw bool toggle with no state loss; the
    /// log-clearing lives in cycleFocusedChartMode, not the chart — reads
    /// the line chart's log state through the toggle, and flips back.
    fn test_chart_at_is_log_y(grid: &SystemMetricsGrid, row: usize, col: usize) -> bool {
        let chart = grid.current_page[row][col].as_ref().expect("chart at cell");
        let mut chart = chart.borrow_mut();
        match &mut *chart {
            SystemChart::Line(c) => SystemMetricChart::is_log_y(c),
            SystemChart::Toggle(t) => {
                if t.is_heatmap_mode() {
                    t.toggle_heatmap_mode();
                    let log_y = t.is_log_y();
                    t.toggle_heatmap_mode();
                    log_y
                } else {
                    t.is_log_y()
                }
            }
        }
    }

    /// Go `SystemMetricsGrid.TestFrenchFriesChartAt` (testhelpers.go:221):
    /// Some(chart) if the cell holds a french-fries-capable chart (the grid
    /// only ever stores toggles for percentage defs; Go's bare
    /// *FrenchFriesChart arm is unreachable from createMetricChart).
    fn test_french_fries_chart_at(
        grid: &SystemMetricsGrid,
        row: isize,
        col: isize,
    ) -> Option<SystemChartRef> {
        if row < 0
            || row as usize >= grid.current_page.len()
            || col < 0
            || col as usize >= grid.current_page[row as usize].len()
        {
            return None;
        }
        let cell = grid.current_page[row as usize][col as usize].as_ref()?;
        match &*cell.borrow() {
            SystemChart::Toggle(_) => Some(Rc::clone(cell)),
            SystemChart::Line(_) => None,
        }
    }

    // -------------------------------------------------------------------
    // systemmetricsgrid_test.go
    // -------------------------------------------------------------------

    // Go: TestSystemMetricsGrid
    #[test]
    fn system_metrics_grid() {
        let (cfg, _dir) = test_config(2, 1);

        // Give the grid enough space (any positive multiples will do).
        let mut grid = new_grid(
            2 * MIN_METRIC_CHART_WIDTH,
            2 * MIN_METRIC_CHART_HEIGHT,
            &cfg,
        );

        let ts = now_unix();
        grid.add_data_point("gpu.0.temp", ts, 50.0);
        grid.add_data_point("gpu.1.temp", ts, 55.0);

        assert_ne!(grid.chart_count(), 0, "expected charts after AddDataPoint");
    }

    // Go: TestSystemMetricsGrid_FocusToggleAndRebuild
    #[test]
    fn system_metrics_grid_focus_toggle_and_rebuild() {
        let (cfg, _dir) = test_config(2, 1);
        let (grid_rows, grid_cols) = cfg.borrow().system_grid();

        // Create grid with sufficient size
        let grid_width = MIN_METRIC_CHART_WIDTH * grid_cols as isize * 2;
        let grid_height = MIN_METRIC_CHART_HEIGHT * grid_rows as isize * 2;
        let mut grid = new_grid(grid_width, grid_height, &cfg);

        let ts = now_unix();
        // Add multiple data points to ensure chart is properly created and visible
        grid.add_data_point("gpu.0.temp", ts, 40.0);
        grid.add_data_point("gpu.0.temp", ts + 1, 41.0);
        grid.add_data_point("gpu.0.temp", ts + 2, 42.0);

        grid.load_current_page();

        // Verify chart was created
        assert_eq!(grid.chart_count(), 1);

        // First click should focus (charts array is populated by AddDataPoint)
        let ok = grid.handle_mouse_click(0, 0);
        assert!(ok, "expected focus after first click");

        // Second click on same cell should unfocus
        let ok2 = grid.handle_mouse_click(0, 0);
        assert!(!ok2, "expected unfocus (toggle off) after second click");

        grid.clear_focus();

        // Add more data after rebuild
        grid.add_data_point("gpu.0.temp", ts + 3, 43.0);

        // Should be able to focus again after rebuild
        let ok3 = grid.handle_mouse_click(0, 0);
        assert!(ok3, "expected to be able to focus after rebuild");
    }

    // Go: TestSystemMetricsGrid_NavigateWithPowerMetrics
    #[test]
    fn system_metrics_grid_navigate_with_power_metrics() {
        let (cfg, _dir) = test_config(2, 1);
        let (grid_rows, grid_cols) = cfg.borrow().system_grid();

        let grid_width = MIN_METRIC_CHART_WIDTH * grid_cols as isize * 2;
        let grid_height = MIN_METRIC_CHART_HEIGHT * grid_rows as isize * 2;
        let mut grid = new_grid(grid_width, grid_height, &cfg);

        let ts = now_unix();

        // Add metrics across multiple pages
        grid.add_data_point("cpu.powerWatts", ts, 25.5);
        grid.add_data_point("gpu.0.powerWatts", ts, 150.0);
        grid.add_data_point("gpu.1.powerWatts", ts, 145.5);
        grid.add_data_point("system.powerWatts", ts, 350.0);
        grid.add_data_point("ane.power", ts, 15.0);
        grid.add_data_point("gpu.2.powerWatts", ts, 160.0);

        // Verify initial state
        grid.load_current_page();
        assert_eq!(grid.chart_count(), 4);

        // Test navigation forward
        let initial_charts = test_current_page(&grid);
        let first_page_chart = initial_charts[0][0].clone();

        grid.navigate(1); // Move to page 2
        grid.load_current_page();

        let second_page_charts = test_current_page(&grid);
        let second_page_chart = second_page_charts[0][0].clone();

        // Verify page changed (different charts)
        // (Go require.NotEqual on two distinct *TimeSeriesLineChart values;
        // pointer identity via Rc::ptr_eq is the equivalent check.)
        if let (Some(first), Some(second)) = (&first_page_chart, &second_page_chart) {
            assert!(
                !Rc::ptr_eq(first, second),
                "navigation did not change displayed charts"
            );
        }

        // Test navigation backward (wrap around)
        grid.navigate(-1); // Back to page 1
        grid.load_current_page();

        // Test wrap-around navigation
        grid.navigate(-1); // Should wrap to last page
        grid.load_current_page();

        // Navigate forward multiple times to test full cycle
        for _ in 0..3 {
            grid.navigate(1);
            grid.load_current_page();
        }

        // Navigate auto-focuses the first chart on the new page.
        grid.navigate(1);
        assert!(
            !grid.focused_chart_title().is_empty(),
            "first chart should be focused after navigation"
        );
    }

    // -------------------------------------------------------------------
    // systemmetricsfilter_test.go
    // -------------------------------------------------------------------

    // Go: TestSystemMetricsGrid_Filter
    #[test]
    fn system_metrics_grid_filter() {
        let (cfg, _dir) = test_config(1, 2);

        let mut grid = new_grid(80, 24, &cfg);

        grid.add_data_point("gpu.0.temp", 100, 40.0);
        grid.add_data_point("cpu.0.cpu_percent", 100, 50.0);
        assert_eq!(grid.chart_count(), 2);
        assert_eq!(grid.filtered_chart_count(), 2);

        grid.enter_filter_mode();
        assert!(grid.is_filter_mode());

        type_string(&mut grid, "GPU");
        grid.apply_filter();
        assert_eq!(grid.filter_query(), "GPU");
        assert_eq!(grid.filtered_chart_count(), 1);

        // Live preview should hide non-matching charts.
        let view = text_to_string(&grid.view(true));
        assert!(view.contains("GPU Temp"));
        assert!(!view.contains("CPU Util"));

        grid.exit_filter_mode(true);
        assert!(!grid.is_filter_mode());
        assert!(grid.is_filtering());
        assert_eq!(grid.filter_query(), "GPU");
        assert_eq!(grid.filtered_chart_count(), 1);

        grid.clear_filter();
        assert!(!grid.is_filtering());
        assert_eq!(grid.filter_query(), "");
        assert_eq!(grid.filtered_chart_count(), 2);
    }

    // -------------------------------------------------------------------
    // frenchfrieschart_test.go:149-245 — the three deferred
    // TestSystemMetricsGrid_* cases (PARITY.md §5.2).
    // -------------------------------------------------------------------

    // Go: TestSystemMetricsGrid_CycleFocusedChartMode (frenchfrieschart_test.go:149)
    #[test]
    fn system_metrics_grid_cycle_focused_chart_mode() {
        let (cfg, _dir) = test_config(1, 1);

        let mut grid = new_grid(
            2 * MIN_METRIC_CHART_WIDTH,
            2 * MIN_METRIC_CHART_HEIGHT,
            &cfg,
        );

        // Go: time.Unix(1_700_000_000, 0).Unix().
        let base_ts = 1_700_000_000i64;
        for gpu in 0..4 {
            let metric = format!("gpu.{gpu}.gpu");
            grid.add_data_point(&metric, base_ts, (25 * (gpu + 1)) as f64);
        }

        assert!(grid.handle_mouse_click(0, 0));
        assert!(!test_heatmap_mode_at(&grid, 0, 0));
        assert!(!test_chart_at_is_log_y(&grid, 0, 0));

        assert!(grid.cycle_focused_chart_mode());
        assert!(!test_heatmap_mode_at(&grid, 0, 0));
        assert!(test_chart_at_is_log_y(&grid, 0, 0));

        assert!(grid.cycle_focused_chart_mode());
        assert!(test_heatmap_mode_at(&grid, 0, 0));
        assert!(test_chart_at_is_log_y(&grid, 0, 0));

        assert!(grid.cycle_focused_chart_mode());
        assert!(!test_heatmap_mode_at(&grid, 0, 0));
        assert!(!test_chart_at_is_log_y(&grid, 0, 0));
    }

    // Go: TestSystemMetricsGrid_GPUUtilizationUsesFrenchFriesChart
    // (frenchfrieschart_test.go:188)
    #[test]
    fn system_metrics_grid_gpu_utilization_uses_french_fries_chart() {
        let (cfg, _dir) = test_config(1, 1);

        let mut grid = new_grid(
            2 * MIN_METRIC_CHART_WIDTH,
            2 * MIN_METRIC_CHART_HEIGHT,
            &cfg,
        );

        let base_ts = 1_700_000_000i64;
        for gpu in 0..4 {
            let metric = format!("gpu.{gpu}.gpu");
            grid.add_data_point(&metric, base_ts, (25 * gpu) as f64);
        }

        let chart = test_french_fries_chart_at(&grid, 0, 0);
        assert!(chart.is_some());
    }

    // Go: TestSystemMetricsGrid_FrenchFriesUsesConfiguredPalette
    // (frenchfrieschart_test.go:214)
    #[test]
    fn system_metrics_grid_french_fries_uses_configured_palette() {
        let (cfg, _dir) = test_config(1, 1);
        cfg.borrow_mut()
            .set_french_fries_color_scheme("plasma")
            .expect("SetFrenchFriesColorScheme");

        let mut grid = new_grid(
            2 * MIN_METRIC_CHART_WIDTH,
            2 * MIN_METRIC_CHART_HEIGHT,
            &cfg,
        );

        let base_ts = 1_700_000_000i64;
        for gpu in 0..2 {
            let metric = format!("gpu.{gpu}.gpu");
            grid.add_data_point(&metric, base_ts, (50 * gpu) as f64);
        }

        let chart = test_french_fries_chart_at(&grid, 0, 0);
        let chart = chart.expect("french fries chart at (0, 0)");

        // Go probes chart.TestColorForValue(0)/(100) against the
        // plasma-styled "█" cells. colorForValue is crate-private to
        // leet-charts (its value-0 → palette[0] / value-100 → palette[last]
        // mapping is pinned there by french_fries_chart_uses_provided_palette);
        // DIVERGENCE(test): this port pins the ConfigManager plumbing through
        // the public surface instead — every heatmap cell the chart draws
        // must resolve from the plasma palette, and the value-0 series must
        // render with plasma[0].
        let palette = french_fries_colors("plasma");
        let dark = default_dark_background();
        let plasma: Vec<Rgb> = palette.iter().map(|c| c.resolve(dark)).collect();

        let mut chart = chart.borrow_mut();
        let SystemChart::Toggle(toggle) = &mut *chart else {
            panic!("expected toggle chart");
        };
        assert!(SystemMetricChart::toggle_heatmap_mode(toggle));
        let canvas = SystemMetricChart::view(toggle);

        let mut seen: Vec<Rgb> = Vec::new();
        for y in 0..canvas.height() {
            for x in 0..canvas.width() {
                let cell = canvas.cell(Point { x, y });
                if cell.ch == '█' {
                    seen.push(cell.fg.expect("heatmap cell must be colored"));
                }
            }
        }
        assert!(!seen.is_empty(), "expected drawn heatmap cells");
        assert!(
            seen.contains(&plasma[0]),
            "value-0 series must render with plasma[0]"
        );
        for fg in &seen {
            assert!(
                plasma.contains(fg),
                "heatmap cell color {fg:?} is not from the plasma palette"
            );
        }
    }
}
