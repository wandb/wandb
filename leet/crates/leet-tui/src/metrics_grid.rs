//! Port of `core/internal/leet/metricsgrid.go` and `metricsfilter.go` (the
//! `MetricsGrid` filter methods; see PORTING.md module mapping).
//!
//! The main run-metrics chart grid: owns `EpochLineChart`s (create, index,
//! update), maintains filter and pagination state, and computes/renders the
//! current page/grid layout.
//!
//! Concurrency: Go guards chart slices/maps and filter state with
//! `mu sync.RWMutex` (S9, metricsgrid.go:23) because Bubble Tea may render
//! View concurrently with Update. Update and view share one thread here, so
//! the lock is deleted (CONCURRENCY.md §2.6) and each `xxx`/`xxxNoLock` pair
//! collapses into one method under the base name. The `setFocusLocked` /
//! `focusedChartLocked` / `lastNonNilColLocked` methods are NOT lock
//! variants of `setFocus`/`focusedChart` — they differ behaviorally — so
//! they keep their Go names (the `Locked` suffix is historical).
//!
//! Shared ownership: Go shares `*EpochLineChart` pointers between `all`,
//! `byTitle`, `filtered`, `currentPage` and `lastDrawnCharts`; the port
//! mirrors that aliasing with `Rc<RefCell<EpochLineChart>>` (single-threaded,
//! CONCURRENCY.md §2.6). `*Focus` and `*ConfigManager` are likewise shared
//! with the Run/Workspace models and port as `Rc<RefCell<_>>`.
//
// PHASE-5: Go's `suppressDraw` batching (B3, runhandlers.go:847-865) lives in
// the Run model, not here: `handleHistoryMsg` calls `ProcessHistory` and only
// invokes `drawVisible` when `!r.suppressDraw` (runhandlers.go:101-103), and
// `handleRecordsBatch` sets `suppressDraw` around a batch and issues a single
// `drawVisible` after it. `process_history` therefore never draws by itself;
// the Run port owns the flag and the per-batch `draw_visible` call.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use leet_charts::canvas::{Canvas, Point};
use leet_charts::epoch_line_chart::{
    EpochLineChart, MetricData as ChartMetricData, SeriesStyle, truncate_title,
};
use leet_charts::styles::{AdaptiveColor, CONTENT_PADDING, graph_colors};
use leet_data::config::{
    COLOR_MODE_PER_PLOT, COLOR_MODE_PER_SERIES, ConfigManager, DEFAULT_COLOR_SCHEME,
    GridConfigTarget,
};
use leet_data::width::text_width;
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span, Text};

use crate::event::HistoryMsg;
use crate::filter::{Filter, FilterMatchMode};
use crate::key::KeyEvent;
use crate::layout::{
    CENTER, GoStyle, LEFT, TOP, border_style, focused_border_style, grid_container_style,
    header_container_style, header_style, join_horizontal, join_vertical, nav_info_style, place,
    rgb_to_color, text_from_str, title_style,
};
use crate::panel_grid::{
    Focus, FocusType, GridDims, GridNavigator, GridSize, GridSpec, compute_grid_dims,
    effective_grid_size, items_per_page,
};

const METRICS_HEADER: &str = "Metrics";

// PARITY: these layout constants live in styles.go in Go; the Rust styles
// module hosts them as i64 — cast once here so the grid math stays isize
// (panel_grid.rs convention).
const CONTENT_PADDING_COLS: isize = leet_charts::styles::CONTENT_PADDING_COLS as isize;
const MIN_CHART_WIDTH: isize = leet_charts::styles::MIN_CHART_WIDTH as isize;
const MIN_CHART_HEIGHT: isize = leet_charts::styles::MIN_CHART_HEIGHT as isize;
const CHART_HEADER_HEIGHT: isize = leet_charts::styles::CHART_HEADER_HEIGHT as isize;

/// A shared chart handle (Go `*EpochLineChart`).
pub type ChartRef = Rc<RefCell<EpochLineChart>>;

/// Go `gridConfig func() (int, int)` — returns (rows, cols). Callers pass
/// e.g. `ConfigManager::metrics_grid` as a closure over the shared config.
pub type GridConfigFn = Box<dyn Fn() -> (i64, i64)>;

/// Go `seriesColorForKey func(string) AdaptiveColor`.
pub type SeriesColorFn = Box<dyn Fn(&str) -> AdaptiveColor>;

/// MetricsGrid manages the main run metrics charts.
///
/// It owns charts (create, index, update), maintains filter and pagination
/// state, and computes/renders the current page/grid layout.
pub struct MetricsGrid {
    // Configuration and logging.
    // PARITY: Go also carries an *observability.CoreLogger; the port logs via
    // `tracing` at the same call sites, so there is no logger field.
    config: Rc<RefCell<ConfigManager>>,
    grid_config: GridConfigFn,

    // Viewport dimensions.
    width: isize,
    height: isize,

    // Pagination state.
    nav: GridNavigator,

    // Charts state.
    all: Vec<ChartRef>,                  // all charts, sorted by Title()
    by_title: HashMap<String, ChartRef>, // Title() -> chart
    filtered: Vec<ChartRef>,             // subset matching filter (mirrors all when filter empty)

    // Charts visible on the current page grid.
    current_page: Vec<Vec<Option<ChartRef>>>,

    /// last_drawn_charts holds charts from the last visible page for parking.
    // PARITY: Go keys a map by chart pointer (map[*EpochLineChart]struct{});
    // the port holds Rc handles (keeping pointer identity valid) and tests
    // membership with Rc::ptr_eq — a page has at most rows*cols entries.
    last_drawn_charts: Vec<ChartRef>,

    // Chart focus management.
    focus: Rc<RefCell<Focus>>, // focus.row/col only meaningful relative to current_page

    // Filter state.
    filter: Filter,

    // Stable color assignment.
    color_of_title: HashMap<String, AdaptiveColor>,
    next_color_idx: usize,

    // Palette for main metrics charts (derived from config.ColorScheme()).
    palette: Vec<AdaptiveColor>,

    // Palette for per-plot mode in single-run view (derived from config.PerPlotColorScheme()).
    per_plot_palette: Vec<AdaptiveColor>,

    // When set to ColorModePerPlot, single-series charts are colored per chart title.
    // Default is ColorModePerSeries (stable run-id color).
    single_series_color_mode: String,

    // series_color_for_key optionally overrides per-series colors keyed by series
    // name (for example workspace run paths). Intended for workspace multi-run
    // view.
    series_color_for_key: Option<SeriesColorFn>,

    // synchronized inspection session state (active only between press/release)
    sync_inspect_active: bool,
}

impl MetricsGrid {
    /// Port of Go `NewMetricsGrid` (the logger parameter is dropped; see the
    /// struct-level PARITY note).
    pub fn new(
        config: Rc<RefCell<ConfigManager>>,
        grid_config: GridConfigFn,
        focus: Rc<RefCell<Focus>>,
    ) -> MetricsGrid {
        let (grid_rows, grid_cols) = grid_config();
        let palette = graph_colors(config.borrow().color_scheme()).to_vec();
        let per_plot_palette = graph_colors(config.borrow().per_plot_color_scheme()).to_vec();

        MetricsGrid {
            config,
            grid_config,
            width: 0,
            height: 0,
            nav: GridNavigator::default(),
            all: Vec::new(),
            by_title: HashMap::new(),
            filtered: Vec::new(),
            current_page: vec![vec![None; grid_cols.max(0) as usize]; grid_rows.max(0) as usize],
            last_drawn_charts: Vec::new(),
            focus,
            filter: Filter::new(),
            color_of_title: HashMap::new(),
            next_color_idx: 0,
            palette,
            per_plot_palette,
            single_series_color_mode: COLOR_MODE_PER_SERIES.to_string(),
            series_color_for_key: None,
            sync_inspect_active: false,
        }
    }

    /// SetSingleSeriesColorMode controls coloring for single-series charts in this grid.
    /// Intended for single-run view (Run) only.
    pub fn set_single_series_color_mode(&mut self, mode: &str) {
        let mut mode = mode;
        if mode != COLOR_MODE_PER_PLOT && mode != COLOR_MODE_PER_SERIES {
            mode = COLOR_MODE_PER_SERIES;
        }
        self.single_series_color_mode = mode.to_string();
    }

    /// SetSeriesColorProvider installs an optional stable color provider for series
    /// keys (for example workspace run paths).
    ///
    /// Callers should set this before processing data so newly created series render
    /// with the intended colors from their first frame.
    pub fn set_series_color_provider(&mut self, provider: SeriesColorFn) {
        self.series_color_for_key = Some(provider);
    }

    /// ChartCount returns the total number of metrics charts.
    pub fn chart_count(&self) -> usize {
        self.all.len()
    }

    /// Go `focusedChart` — the focused main-grid chart, if the focus state
    /// points at a valid one.
    pub(crate) fn focused_chart(&self) -> Option<ChartRef> {
        let f = self.focus.borrow();
        if f.focus_type != FocusType::MainChart || f.row < 0 || f.col < 0 {
            return None;
        }
        if f.row as usize >= self.current_page.len()
            || f.col as usize >= self.current_page[f.row as usize].len()
        {
            return None;
        }
        self.current_page[f.row as usize][f.col as usize].clone()
    }

    // PHASE-5: called by the Run model's status-bar rendering (run.go).
    #[allow(dead_code)]
    pub(crate) fn focused_chart_scale_label(&self) -> &'static str {
        let Some(chart) = self.focused_chart() else {
            return "";
        };
        chart.borrow().scale_label()
    }

    // PHASE-5: called by the Run model's `l` key handler (runhandlers.go).
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

    /// CalculateChartDimensions computes chart dimensions.
    pub fn calculate_chart_dimensions(
        &self,
        window_width: isize,
        window_height: isize,
    ) -> GridDims {
        let (grid_rows, grid_cols) = (self.grid_config)();
        // Subtract the content padding that View will add around the grid.
        let inner_w = (window_width - CONTENT_PADDING_COLS).max(0);
        compute_grid_dims(
            inner_w,
            window_height,
            GridSpec {
                rows: grid_rows as isize,
                cols: grid_cols as isize,
                min_cell_w: MIN_CHART_WIDTH,
                min_cell_h: MIN_CHART_HEIGHT,
                header_lines: CHART_HEADER_HEIGHT,
            },
        )
    }

    /// ProcessHistory ingests a batch of history samples (single step across metrics),
    /// creating charts as needed, resorting, reapplying filters, and reloading the page.
    /// It preserves focus on the previously focused chart when possible.
    /// Returns true if there was anything to draw.
    pub fn process_history(&mut self, msg: &HistoryMsg) -> bool {
        let metrics = &msg.metrics;
        if metrics.is_empty() {
            return false;
        }

        // Remember focused chart title (only if a main chart is actually focused & valid).
        let prev_title = self.save_focus_title();

        let mut needs_sort = false;

        let mut series_style: Option<SeriesStyle> = None;
        if let Some(provider) = &self.series_color_for_key
            && !msg.run_path.is_empty()
        {
            // Go: lipgloss.NewStyle().Foreground(provider(RunPath)).
            series_style = Some(SeriesStyle {
                fg: provider(&msg.run_path),
            });
        }

        // PARITY: Go ranges the metrics map unordered; creation order never
        // reaches the screen (sortCharts orders `all` and assigns colors over
        // the sorted slice), so the HashMap's arbitrary order is kept.
        for (name, data) in metrics {
            let chart = match self.by_title.get(name) {
                Some(existing) => Rc::clone(existing),
                None => {
                    let mut new_chart = EpochLineChart::new(name);
                    new_chart.set_palette(&self.palette);
                    let chart = Rc::new(RefCell::new(new_chart));
                    self.all.push(Rc::clone(&chart));
                    self.by_title.insert(name.clone(), Rc::clone(&chart));
                    needs_sort = true;

                    // PARITY: Go `len(mg.all)%1000 == 0`.
                    if self.all.len().is_multiple_of(1000) {
                        tracing::debug!("metricsgrid: created {} charts", self.all.len());
                    }
                    chart
                }
            };
            // PARITY: crate::event::MetricData mirrors messages.go MetricData;
            // the chart API takes leet-data's identical struct — converted at
            // this boundary (Go passes the one shared type).
            chart.borrow_mut().add_data(
                &msg.run_path,
                ChartMetricData {
                    x: data.x.clone(),
                    y: data.y.clone(),
                },
            );
            if let Some(style) = series_style {
                chart.borrow_mut().set_series_style(&msg.run_path, style);
            }
        }

        // Keep ordering, colors, maps and filtered set in sync.
        if needs_sort {
            self.sort_charts(); // re-sorts + assigns stable colors
            self.apply_filter(); // keep filtered mirror / subset
        } else {
            // No new charts; keep pagination but refresh visible page contents.
            self.load_current_page();
        }

        // Restore focus by title (if previously valid and still visible).
        self.restore_focus(&prev_title);
        true
    }

    /// effectiveGridSize returns the grid size that can fit in the current viewport.
    fn effective_grid_size(&self) -> GridSize {
        let (grid_rows, grid_cols) = (self.grid_config)();
        effective_grid_size(
            self.width,
            self.height,
            GridSpec {
                rows: grid_rows as isize,
                cols: grid_cols as isize,
                min_cell_w: MIN_CHART_WIDTH,
                min_cell_h: MIN_CHART_HEIGHT,
                header_lines: CHART_HEADER_HEIGHT,
            },
        )
    }

    /// Go `chartsToShowNoLock` — the slice backing the current view.
    fn charts_to_show(&self) -> &[ChartRef] {
        if self.filter.query().is_empty() {
            return &self.all;
        }
        &self.filtered
    }

    /// Go `effectiveChartCountNoLock` — the count used for nav/pagination.
    fn effective_chart_count(&self) -> isize {
        if self.filter.query().is_empty() {
            return self.all.len() as isize;
        }
        self.filtered.len() as isize
    }

    /// Go `colorForNoLock` — a stable color for a given metric title.
    fn color_for(&mut self, title: &str) -> AdaptiveColor {
        if let Some(c) = self.color_of_title.get(title) {
            return *c;
        }
        // Select palette based on color mode.
        let mut palette: &[AdaptiveColor] = &self.palette;
        if self.single_series_color_mode == COLOR_MODE_PER_PLOT && !self.per_plot_palette.is_empty()
        {
            palette = &self.per_plot_palette;
        }
        if palette.is_empty() {
            palette = graph_colors(DEFAULT_COLOR_SCHEME);
        }
        let c = palette[self.next_color_idx % palette.len()];
        self.color_of_title.insert(title.to_string(), c);
        self.next_color_idx += 1;
        c
    }

    /// Go `sortChartsNoLock` — sorts charts alphabetically, rebuilds indices,
    /// and (re)assigns colors.
    fn sort_charts(&mut self) {
        // PARITY: Go sort.Slice is unstable, but titles are unique (byTitle
        // keys), so the ordering is total and stability is irrelevant.
        self.all
            .sort_by(|a, b| a.borrow().title().cmp(b.borrow().title()));

        self.by_title = HashMap::with_capacity(self.all.len());
        for i in 0..self.all.len() {
            let chart = Rc::clone(&self.all[i]);
            let title = chart.borrow().title().to_string();

            // Stable color per title (no reshuffling when new charts arrive).
            let col = self.color_for(&title);
            if self.single_series_color_mode == COLOR_MODE_PER_PLOT {
                // Go: lipgloss.NewStyle().Foreground(col).
                chart.borrow_mut().set_graph_style(SeriesStyle { fg: col });
            }

            self.by_title.insert(title, chart);
        }

        // Ensure filtered mirrors all when filter is empty.
        if self.filter.query().is_empty() {
            self.filtered = self.all.clone();
        }
    }

    /// loadCurrentPage loads the charts for the current page into the grid.
    // PARITY: collapses Go's loadCurrentPage/loadCurrentPageNoLock pair (S9).
    fn load_current_page(&mut self) {
        let size = self.effective_grid_size();

        // Rebuild grid structure
        self.current_page = vec![vec![None; size.cols.max(0) as usize]; size.rows.max(0) as usize];

        let per_page = items_per_page(size);
        let count = self.charts_to_show().len() as isize;
        let (start_idx, end_idx) = self.nav.page_bounds(count, per_page);

        // The page slice is cloned (cheap Rc handles) to keep the borrow on
        // `self.all`/`self.filtered` from overlapping the page mutation.
        let page_charts: Vec<ChartRef> = {
            let charts = self.charts_to_show();
            let mut v = Vec::new();
            let mut idx = start_idx;
            while idx >= 0 && idx < end_idx {
                v.push(Rc::clone(&charts[idx as usize]));
                idx += 1;
            }
            v
        };

        let mut idx = 0usize;
        'fill: for row in self.current_page.iter_mut() {
            for cell in row.iter_mut() {
                if idx >= page_charts.len() {
                    break 'fill;
                }
                *cell = Some(Rc::clone(&page_charts[idx]));
                idx += 1;
            }
        }
    }

    /// UpdateDimensions updates chart sizes based on content viewport.
    pub fn update_dimensions(&mut self, content_width: isize, content_height: isize) {
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

    /// View creates the chart grid view.
    ///
    /// `dark` resolves adaptive colors (Go reads the `darkBackground`
    /// package global at render time; see layout.rs module doc).
    pub fn view(&self, dims: GridDims, dark: bool) -> Text<'static> {
        let size = self.effective_grid_size();

        let header = self.render_header(size, dark);
        let grid = self.render_grid(dims, size, dark);

        // Ensure exact height by placing in a box sized to the grid's actual
        // allocated height (rows * cellH + header). This prevents phantom filler
        // lines when mg.height drifts from the dims passed in by the caller.
        let inner_w = (self.width - CONTENT_PADDING_COLS).max(0);
        let total_h = CHART_HEADER_HEIGHT + size.rows * dims.cell_h_with_padding;
        let result = join_vertical(LEFT, vec![header, grid]);
        let result = place(inner_w as i64, total_h as i64, LEFT, TOP, result);
        GoStyle::new()
            .padding(&[0, CONTENT_PADDING])
            .render_text(result)
    }

    fn render_header(&self, size: GridSize, dark: bool) -> Text<'static> {
        let header = header_style(dark).render(METRICS_HEADER);

        let mut nav_info = text_from_str("");

        let chart_count = self.effective_chart_count();
        let total_count = self.all.len();

        let per_page = items_per_page(size);
        let total_pages = self.nav.total_pages();

        if total_pages > 0 && chart_count > 0 {
            let (mut start_idx, end_idx) = self.nav.page_bounds(chart_count, per_page);
            start_idx += 1; // Display as 1-indexed

            if !self.filter.query().is_empty() {
                nav_info = nav_info_style(dark).render(&format!(
                    " [{start_idx}-{end_idx} of {chart_count} filtered from {total_count} total]"
                ));
            } else {
                nav_info = nav_info_style(dark)
                    .render(&format!(" [{start_idx}-{end_idx} of {chart_count}]"));
            }
        }

        let header_line = join_horizontal(LEFT, vec![header, nav_info]);
        header_container_style().render_text(header_line)
    }

    fn render_grid(&self, dims: GridDims, size: GridSize, dark: bool) -> Text<'static> {
        let no_data = self.all.is_empty();

        if no_data {
            let inner_w = (self.width - CONTENT_PADDING_COLS).max(0);
            let grid_h = (size.rows * dims.cell_h_with_padding).max(1);
            return place(
                inner_w as i64,
                grid_h as i64,
                CENTER,
                CENTER,
                nav_info_style(dark).render("No metric data for selected runs."),
            );
        }

        let mut rows = Vec::new();
        for row in 0..size.rows {
            let mut cols = Vec::new();
            for col in 0..size.cols {
                let cell_content = self.render_grid_cell(row, col, dims, dark);
                cols.push(cell_content);
            }
            let row_view = join_horizontal(LEFT, cols);
            rows.push(row_view);
        }
        let grid_content = join_vertical(LEFT, rows);
        grid_container_style().render_text(grid_content)
    }

    /// renderGridCell renders a single grid cell.
    fn render_grid_cell(
        &self,
        row: isize,
        col: isize,
        dims: GridDims,
        dark: bool,
    ) -> Text<'static> {
        if row >= 0
            && col >= 0
            && (row as usize) < self.current_page.len()
            && (col as usize) < self.current_page[row as usize].len()
            && self.current_page[row as usize][col as usize].is_some()
        {
            let chart = self.current_page[row as usize][col as usize]
                .as_ref()
                .expect("checked above");
            let ch = chart.borrow();
            // Go `chart.View()` — the chart's canvas viewport, blitted.
            let chart_view = blit_canvas(&ch.canvas);

            let mut box_style = border_style(dark);
            {
                let f = self.focus.borrow();
                if f.focus_type == FocusType::MainChart && row == f.row && col == f.col {
                    box_style = focused_border_style(dark);
                }
            }

            let mut title_suffix = "";
            if ch.is_log_y() {
                title_suffix = " [log]";
            }

            let available_title_width =
                (dims.cell_w_with_padding - 4 - text_width(title_suffix) as isize).max(10);
            let display_title = truncate_title(ch.title(), available_title_width as i64);
            // Go: titleStyle.Render(displayTitle) + navInfoStyle.Render(titleSuffix)
            // (string concatenation of two one-line renders).
            let title_text = join_horizontal(
                LEFT,
                vec![
                    title_style(dark).render(&display_title),
                    nav_info_style(dark).render(title_suffix),
                ],
            );

            let box_content = join_vertical(LEFT, vec![title_text, chart_view]);

            let boxed = box_style.render_text(box_content);

            return place(
                dims.cell_w_with_padding as i64,
                dims.cell_h_with_padding as i64,
                LEFT,
                TOP,
                boxed,
            );
        }

        GoStyle::new()
            .width(dims.cell_w_with_padding as i64)
            .height(dims.cell_h_with_padding as i64)
            .render("")
    }

    /// Navigate changes the current page.
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

    /// drawVisible draws charts that are currently visible.
    ///
    /// Charts no longer visible are parked to reduce memory usage.
    // PHASE-5: the Run model calls this once per record batch (suppressDraw
    // seam, see the module doc).
    pub(crate) fn draw_visible(&mut self) {
        let dims = self.calculate_chart_dimensions(self.width, self.height);

        let mut current_charts: Vec<ChartRef> = Vec::new();
        for row in &self.current_page {
            for cell in row {
                if let Some(ch) = cell
                    && !current_charts.iter().any(|c| Rc::ptr_eq(c, ch))
                {
                    current_charts.push(Rc::clone(ch));
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

        // Resize and draw visible charts. (Go additionally holds mu here to
        // serialize with ProcessHistory's AddData — single-threaded now.)
        for ch in &current_charts {
            let mut chart = ch.borrow_mut();
            chart.resize(dims.cell_w as i64, dims.cell_h as i64);
            chart.draw();
        }
    }

    /// saveFocusTitle returns the title of the currently focused main-grid chart,
    /// or an empty string if nothing valid is focused.
    fn save_focus_title(&self) -> String {
        if self.focus.borrow().focus_type != FocusType::MainChart {
            return String::new();
        }
        let (row, col) = {
            let f = self.focus.borrow();
            (f.row, f.col)
        };
        if row >= 0
            && col >= 0
            && (row as usize) < self.current_page.len()
            && (col as usize) < self.current_page[row as usize].len()
            && let Some(ch) = &self.current_page[row as usize][col as usize]
        {
            return ch.borrow().title().to_string();
        }
        String::new()
    }

    /// restoreFocus tries to restore focus to the chart with the given title.
    fn restore_focus(&self, previous_title: &str) {
        if previous_title.is_empty() || self.focus.borrow().focus_type != FocusType::MainChart {
            return;
        }
        let size = self.effective_grid_size();

        let (mut found_row, mut found_col) = (-1isize, -1isize);
        'outer: for row in 0..size.rows {
            for col in 0..size.cols {
                if (row as usize) < self.current_page.len()
                    && (col as usize) < self.current_page[row as usize].len()
                    && let Some(ch) = &self.current_page[row as usize][col as usize]
                    && ch.borrow().title() == previous_title
                {
                    found_row = row;
                    found_col = col;
                    break 'outer;
                }
            }
        }

        if found_row != -1 {
            self.set_focus(found_row, found_col);
        }
    }

    /// HandleClick handles clicks in the main chart grid.
    pub fn handle_click(&self, row: isize, col: isize) {
        // Unfocus if clicking the already-focused chart.
        let already_focused = {
            let f = self.focus.borrow();
            f.focus_type == FocusType::MainChart && row == f.row && col == f.col
        };
        if already_focused {
            self.clear_focus();
            return;
        }

        let size = self.effective_grid_size();

        let valid = row >= 0
            && row < size.rows
            && col >= 0
            && col < size.cols
            && (row as usize) < self.current_page.len()
            && (col as usize) < self.current_page[row as usize].len()
            && self.current_page[row as usize][col as usize].is_some();

        if !valid {
            return;
        }

        self.clear_focus();
        self.set_focus(row, col);
    }

    /// setFocus sets focus to a main grid chart.
    // PARITY: unlike setFocusLocked, Go's setFocus does NOT unfocus the
    // previously focused chart and returns nothing. Both port with their Go
    // names; the lock the Go variant took internally is gone (S9).
    // pub(crate): the run tests replace testhelpers.go
    // `TestSetMainChartFocus` (testhelpers.go:92-94) with direct access.
    pub(crate) fn set_focus(&self, row: isize, col: isize) {
        if row >= 0
            && col >= 0
            && (row as usize) < self.current_page.len()
            && (col as usize) < self.current_page[row as usize].len()
            && let Some(chart) = self.current_page[row as usize][col as usize].clone()
        {
            self.focus.borrow_mut().set(
                FocusType::MainChart,
                row,
                col,
                chart.borrow().title().to_string(),
            );
            chart.borrow_mut().set_focused(true);
        }
    }

    /// NavigateFocus moves chart focus by (dr, dc) within the current page.
    /// On partial pages, clamps to the last populated cell in the target row.
    /// Returns true if navigation occurred.
    pub fn navigate_focus(&self, dr: isize, dc: isize) -> bool {
        if self.current_page.is_empty() {
            return false;
        }

        let (row, col) = {
            let f = self.focus.borrow();
            (f.row, f.col)
        };
        if row < 0 || col < 0 || self.focused_chart_locked().is_none() {
            // No current focus — find the first non-nil cell.
            for (r, cells) in self.current_page.iter().enumerate() {
                for (c, ch) in cells.iter().enumerate() {
                    if ch.is_some() {
                        return self.set_focus_locked(r as isize, c as isize);
                    }
                }
            }
            return false;
        }

        let new_row = clamp(row + dr, 0, self.current_page.len() as isize - 1);
        let last_col = self.last_non_nil_col_locked(new_row);
        if last_col < 0 {
            return false;
        }
        let new_col = clamp(col + dc, 0, last_col);

        if self.current_page[new_row as usize][new_col as usize].is_none() {
            return false;
        }

        if new_row == row && new_col == col {
            return false;
        }

        self.set_focus_locked(new_row, new_col)
    }

    /// Go `setFocusLocked` — sets focus to (row, col), unfocusing the
    /// previously focused chart first. (The name is historical: Go's caller
    /// held mg.mu; the lock is deleted, see module doc.)
    fn set_focus_locked(&self, row: isize, col: isize) -> bool {
        if row < 0
            || row as usize >= self.current_page.len()
            || col < 0
            || col as usize >= self.current_page[row as usize].len()
        {
            return false;
        }
        let Some(chart) = self.current_page[row as usize][col as usize].clone() else {
            return false;
        };

        // Unfocus old chart.
        {
            let (old_row, old_col) = {
                let f = self.focus.borrow();
                (f.row, f.col)
            };
            if old_row >= 0
                && old_col >= 0
                && (old_row as usize) < self.current_page.len()
                && (old_col as usize) < self.current_page[old_row as usize].len()
                && let Some(old) = &self.current_page[old_row as usize][old_col as usize]
            {
                old.borrow_mut().set_focused(false);
            }
        }

        self.focus.borrow_mut().set(
            FocusType::MainChart,
            row,
            col,
            chart.borrow().title().to_string(),
        );
        chart.borrow_mut().set_focused(true);
        true
    }

    /// Go `focusedChartLocked` — the focused chart, if any. Unlike
    /// `focused_chart`, does not require focus.focus_type == MainChart.
    fn focused_chart_locked(&self) -> Option<ChartRef> {
        let (r, c) = {
            let f = self.focus.borrow();
            (f.row, f.col)
        };
        if r < 0
            || c < 0
            || r as usize >= self.current_page.len()
            || c as usize >= self.current_page[r as usize].len()
        {
            return None;
        }
        self.current_page[r as usize][c as usize].clone()
    }

    /// Go `lastNonNilColLocked`.
    fn last_non_nil_col_locked(&self, row: isize) -> isize {
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

    /// clearFocus clears focus only from main charts.
    // PARITY: pub(crate) — run.go/runhandlers.go call it directly
    // (runhandlers.go:139/:184/:235/:258), Go package-private access.
    pub(crate) fn clear_focus(&self) {
        if self.focus.borrow().focus_type == FocusType::MainChart {
            let (row, col) = {
                let f = self.focus.borrow();
                (f.row, f.col)
            };
            if row >= 0
                && col >= 0
                && (row as usize) < self.current_page.len()
                && (col as usize) < self.current_page[row as usize].len()
                && let Some(ch) = &self.current_page[row as usize][col as usize]
            {
                ch.borrow_mut().set_focused(false);
            }
            self.focus.borrow_mut().reset();
        }
    }

    /// HandleWheel performs zoom handling on a main-grid chart at (row, col).
    pub fn handle_wheel(
        &self,
        adjusted_x: isize,
        row: isize,
        col: isize,
        dims: GridDims,
        wheel_up: bool,
    ) {
        let Some((chart, rel_x, need_focus)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims)
        else {
            return;
        };
        if rel_x < 0 || rel_x as i64 >= chart.borrow().graph_width() {
            return;
        }
        if need_focus {
            self.clear_focus();
            self.set_focus(row, col);
        }

        let mut dir = "out";
        if wheel_up {
            dir = "in";
        }
        chart.borrow_mut().handle_zoom(dir, rel_x as i64);
        chart.borrow_mut().draw_if_needed();
    }

    /// IsFilterMode returns true if the metrics grid is currently in filter input mode.
    pub fn is_filter_mode(&self) -> bool {
        self.filter.is_active()
    }

    /// IsFiltering returns true if the metrics grid has an applied filter.
    pub fn is_filtering(&self) -> bool {
        !self.filter.is_active() && !self.filter.query().is_empty()
    }

    /// FilterQuery returns the current filter pattern.
    pub fn filter_query(&self) -> &str {
        self.filter.query()
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
    ) -> Option<(ChartRef, isize, bool)> {
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
        let mut graph_start_x = chart_start_x + 1;
        {
            let ch = chart.borrow();
            if ch.y_step() > 0 {
                graph_start_x += ch.origin().x as isize + 1;
            }
        }
        let rel_x = adjusted_x - graph_start_x;

        let need_focus = {
            let f = self.focus.borrow();
            f.focus_type != FocusType::MainChart || f.row != row || f.col != col
        };
        Some((chart, rel_x, need_focus))
    }

    /// StartInspection focuses the chart and begins inspection if inside the graph.
    ///
    /// If synced==true (Alt+right-press), a synchronized inspection session starts:
    /// the anchor X from the focused chart is broadcast to all visible charts.
    pub fn start_inspection(
        &mut self,
        adjusted_x: isize,
        row: isize,
        col: isize,
        dims: GridDims,
        synced: bool,
    ) {
        let Some((chart, rel_x, need_focus)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims)
        else {
            return;
        };

        // Clamp to graph bounds at the chart level, but ignore wildly out-of-bounds here.
        if rel_x < -2 || rel_x as i64 > chart.borrow().graph_width() + 1 {
            return;
        }

        if need_focus {
            self.clear_focus();
            self.set_focus(row, col);
        }

        chart.borrow_mut().start_inspection(rel_x as i64);
        chart.borrow_mut().draw_if_needed();

        if synced {
            self.sync_inspect_active = true;
            let (x, _, active) = chart.borrow().inspection_data();
            if active {
                self.broadcast_inspect_at_data_x(x);
            }
        }
    }

    /// UpdateInspection updates the crosshair position on the focused chart.
    ///
    /// If a synchronized inspection session is active, broadcasts the position
    /// to all visible charts on the current page.
    pub fn update_inspection(&mut self, adjusted_x: isize, row: isize, col: isize, dims: GridDims) {
        let Some((chart, rel_x, _)) = self.hit_chart_and_rel_x(adjusted_x, row, col, dims) else {
            return;
        };
        if !chart.borrow().is_inspecting() {
            return;
        }

        chart.borrow_mut().start_inspection(rel_x as i64);
        chart.borrow_mut().draw_if_needed();

        if self.sync_inspect_active {
            let (x, _, active) = chart.borrow().inspection_data();
            if active {
                self.broadcast_inspect_at_data_x(x);
            }
        }
    }

    /// EndInspection clears inspection mode.
    ///
    /// If a synchronized session is active, clears inspection on all visible charts;
    /// otherwise clears only the focused chart.
    pub fn end_inspection(&mut self) {
        if self.sync_inspect_active {
            self.broadcast_end_inspection();
            self.sync_inspect_active = false;
            return;
        }

        {
            let f = self.focus.borrow();
            if f.focus_type != FocusType::MainChart || f.row < 0 || f.col < 0 {
                return;
            }
        }
        let (row, col) = {
            let f = self.focus.borrow();
            (f.row, f.col)
        };
        let mut chart: Option<ChartRef> = None;
        if (row as usize) < self.current_page.len()
            && (col as usize) < self.current_page[row as usize].len()
        {
            chart = self.current_page[row as usize][col as usize].clone();
        }
        if let Some(chart) = chart {
            chart.borrow_mut().end_inspection();
            chart.borrow_mut().draw_if_needed();
        }
    }

    /// broadcastInspectAtDataX applies InspectAtDataX to all visible charts on the current page.
    fn broadcast_inspect_at_data_x(&self, anchor_x: f64) {
        for row in &self.current_page {
            for ch in row.iter().flatten() {
                ch.borrow_mut().inspect_at_data_x(anchor_x);
                ch.borrow_mut().draw_if_needed();
            }
        }
    }

    /// broadcastEndInspection clears inspection on all visible charts on the current page.
    fn broadcast_end_inspection(&self) {
        for row in &self.current_page {
            for cell in row {
                if let Some(ch) = cell
                    && ch.borrow().is_inspecting()
                {
                    ch.borrow_mut().end_inspection();
                    ch.borrow_mut().draw_if_needed();
                }
            }
        }
    }

    /// handleFilterKey processes a key event while the metrics filter is active.
    // PHASE-5: called by the Run/Workspace key handlers while filter mode is
    // active (runhandlers.go / workspacehandlers.go).
    #[allow(dead_code)]
    pub(crate) fn handle_filter_key(&mut self, msg: &KeyEvent) {
        let changed = self.filter.handle_key(msg);

        if changed {
            self.apply_filter();
            self.draw_visible();
        }
    }

    /// Grid-layout config handler.
    // PHASE-5: Go passes the Run's `layout Layout` (run.go:700) and reads
    // `layout.mainContentAreaWidth`/`layout.height`; `Layout` belongs to the
    // run.rs port, so the two fields are passed directly until it lands.
    #[allow(dead_code)]
    pub(crate) fn handle_grid_config_number_key(
        &mut self,
        msg: &KeyEvent,
        main_content_area_width: isize,
        height: isize,
    ) {
        // PARITY: Go defers config.SetPendingGridConfig(gridConfigNone) so it
        // runs on every exit path; the labeled block routes all returns
        // through the tail call below.
        'body: {
            if msg.key_string() == "esc" {
                break 'body;
            }

            let Ok(num) = msg.key_string().parse::<i64>() else {
                break 'body;
            };

            let result = self.config.borrow_mut().set_grid_config(num);
            match result {
                Err(err) => {
                    tracing::error!("model: failed to update config: {err}");
                    break 'body;
                }
                Ok(status_msg) => {
                    self.update_dimensions(main_content_area_width, height);
                    tracing::info!("{status_msg}");
                }
            }
        }
        self.config
            .borrow_mut()
            .set_pending_grid_config(GridConfigTarget::None);
    }

    // PARITY: Go's nil-receiver guard (`if mg == nil`) is unrepresentable.
    pub fn remove_series(&mut self, key: &str) {
        if key.is_empty() {
            return;
        }

        if self.all.is_empty() {
            return;
        }

        // PARITY: Go filters in place via the `mg.all[:0]` aliasing idiom.
        let mut filtered: Vec<ChartRef> = Vec::with_capacity(self.all.len());
        for ch in std::mem::take(&mut self.all) {
            ch.borrow_mut().remove_series(key);
            if ch.borrow().series_count() > 0 {
                filtered.push(ch);
            }
        }
        self.all = filtered;

        // Rebuild index by title to stay consistent.
        self.by_title = HashMap::with_capacity(self.all.len());
        for ch in &self.all {
            let title = ch.borrow().title().to_string();
            self.by_title.insert(title, Rc::clone(ch));
        }

        // Reapply filter + nav on the pruned chart set.
        self.apply_filter();

        self.draw_visible();
    }

    /// PromoteSeriesToTop ensures the given series key is drawn last in all charts.
    /// Used by the workspace to keep a pinned run visually on top.
    // PARITY: Go's nil-receiver and nil-chart guards are unrepresentable.
    pub fn promote_series_to_top(&mut self, series_key: &str) {
        if series_key.is_empty() {
            return;
        }

        if self.all.is_empty() {
            return;
        }

        for ch in &self.all {
            ch.borrow_mut().promote_series_to_top(series_key);
        }
    }

    // -----------------------------------------------------------------------
    // metricsfilter.go — the MetricsGrid filter methods.
    // -----------------------------------------------------------------------

    /// ApplyFilter applies the filter pattern to charts.
    // PARITY: collapses Go's ApplyFilter/applyFilterNoLock pair (S9).
    pub fn apply_filter(&mut self) {
        // Fresh slice, no alias with allCharts.
        let matcher = self.filter.matcher();
        let mut filtered: Vec<ChartRef> = Vec::with_capacity(self.all.len());
        for ch in &self.all {
            if matcher(ch.borrow().title()) {
                filtered.push(Rc::clone(ch));
            }
        }
        self.filtered = filtered;

        // Keep pagination in sync with what fits now.
        let size = self.effective_grid_size();
        self.nav
            .update_total_pages(self.filtered.len() as isize, items_per_page(size));

        self.load_current_page();
    }

    /// FilteredChartCount returns the number of charts matching the current filter.
    pub fn filtered_chart_count(&self) -> usize {
        self.filtered.len()
    }

    /// EnterFilterMode enters filter input mode.
    pub fn enter_filter_mode(&mut self) {
        self.filter.activate();
    }

    /// UpdateFilterDraft updates the in-progress filter text (for live preview).
    pub fn update_filter_draft(&mut self, msg: &KeyEvent) {
        self.filter.update_draft(msg);
    }

    /// ExitFilterMode exits filter input mode and optionally applies the filter.
    pub fn exit_filter_mode(&mut self, apply: bool) {
        if apply {
            self.filter.commit();
        } else {
            self.filter.cancel();
        }
        self.apply_filter();
        self.draw_visible();
    }

    /// ClearFilter removes the active filter.
    pub fn clear_filter(&mut self) {
        self.filter.clear();
        self.apply_filter();
        self.draw_visible();
    }

    /// ToggleFilterMatchMode flips regex <-> glob and reapplies current preview/applied.
    pub fn toggle_filter_match_mode(&mut self) {
        self.filter.toggle_mode();
        self.apply_filter();
        self.draw_visible();
    }

    /// FilterMode exposes the current filter match mode.
    pub fn filter_mode(&self) -> FilterMatchMode {
        self.filter.mode()
    }
}

/// Blits a chart canvas viewport into a styled text block — the Go
/// `chart.View()` equivalent (ntcharts canvas.Model.View renders the
/// viewport rows as styled runes; charts resolve adaptive colors at draw
/// time, so cells arrive with concrete Rgb styles).
///
/// Shared across the chart grids (metrics, system metrics, symon): reuse
/// this via `pub(crate)`, do not re-port.
// PARITY: Go's View starts at the canvas cursor; leet never scrolls a chart
// canvas viewport (nothing in the ported subset moves the cursor off 0,0),
// so the blit reads from the top-left. Null runes render as spaces, exactly
// like Go.
pub(crate) fn blit_canvas(canvas: &Canvas) -> Text<'static> {
    let rows = canvas.view_height.min(canvas.height());
    let cols = canvas.view_width.min(canvas.width());

    let mut lines: Vec<Line<'static>> = Vec::new();
    for y in 0..rows.max(0) {
        let mut spans: Vec<Span<'static>> = Vec::new();
        let mut run = String::new();
        let mut run_style = Style::default();
        for x in 0..cols.max(0) {
            let cell = canvas.cell(Point { x, y });
            let ch = if cell.ch == '\u{0000}' { ' ' } else { cell.ch };
            let mut style = Style::default();
            if let Some(fg) = cell.fg {
                style = style.fg(rgb_to_color(fg));
            }
            if let Some(bg) = cell.bg {
                style = style.bg(rgb_to_color(bg));
            }
            if cell.bold {
                style = style.add_modifier(Modifier::BOLD);
            }
            if style != run_style && !run.is_empty() {
                spans.push(Span::styled(std::mem::take(&mut run), run_style));
            }
            run_style = style;
            run.push(ch);
        }
        if !run.is_empty() {
            spans.push(Span::styled(run, run_style));
        }
        lines.push(Line::from(spans));
    }
    if lines.is_empty() {
        // Go View() on an empty viewport returns "" — one empty line.
        lines.push(Line::default());
    }
    Text::from(lines)
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

// Transliteration of `metricsgrid_test.go` and `metricsfilter_test.go`.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::MetricData;
    use crate::key::{KeyCode, KeyMods};
    use crate::layout::text_to_string;

    /// Go `newMetricsGrid` (metricsgrid_test.go:15-33). Returns the TempDir
    /// too so the config path outlives the grid (Go's `t.TempDir()` lives for
    /// the test).
    fn new_metrics_grid(
        rows: i64,
        cols: i64,
        width: isize,
        height: isize,
        focus: Option<Rc<RefCell<Focus>>>,
    ) -> (MetricsGrid, tempfile::TempDir) {
        let dir = tempfile::tempdir().expect("tempdir");
        let cfg = Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )));
        cfg.borrow_mut().set_metrics_rows(rows).unwrap();
        cfg.borrow_mut().set_metrics_cols(cols).unwrap();

        let focus = focus.unwrap_or_else(|| Rc::new(RefCell::new(Focus::new())));

        // Go passes the method value cfg.MetricsGrid.
        let grid_config: GridConfigFn = {
            let cfg = Rc::clone(&cfg);
            Box::new(move || cfg.borrow().metrics_grid())
        };
        let mut grid = MetricsGrid::new(cfg, grid_config, focus);
        grid.update_dimensions(width, height);
        (grid, dir)
    }

    // Go `typeString` (over the ComponentWithContentFilter interface; only
    // the metrics grid is exercised here).
    fn type_string(grid: &mut MetricsGrid, s: &str) {
        for r in s.chars() {
            grid.update_filter_draft(&KeyEvent {
                code: KeyCode::Char(r),
                text: Some(r.to_string()),
                mods: KeyMods::NONE,
            });
        }
    }

    fn metric(x: &[f64], y: &[f64]) -> MetricData {
        MetricData {
            x: x.to_vec(),
            y: y.to_vec(),
        }
    }

    fn history(metrics: Vec<(&str, MetricData)>) -> HistoryMsg {
        HistoryMsg {
            metrics: metrics
                .into_iter()
                .map(|(k, v)| (k.to_string(), v))
                .collect(),
            ..Default::default()
        }
    }

    fn view_string(grid: &MetricsGrid, dims: GridDims) -> String {
        // `dark` is arbitrary: text_to_string strips styles.
        text_to_string(&grid.view(dims, true))
    }

    /// Go `strings.Index` — byte index of the first occurrence, -1 if absent.
    fn index_of(haystack: &str, needle: &str) -> isize {
        haystack.find(needle).map_or(-1, |i| i as isize)
    }

    /// Go `require.InDelta(t, want, got, delta)`.
    fn assert_in_delta(want: f64, got: f64, delta: f64) {
        assert!(
            (want - got).abs() <= delta,
            "want {want} ± {delta}, got {got}"
        );
    }

    /// Go `MetricsGrid.TestChartAt` (testhelpers.go): the chart at (row, col)
    /// on the current page (or None). testhelpers.go is not ported; in-module
    /// tests read `current_page` directly (PORTING.md testhelpers policy).
    fn test_chart_at(grid: &MetricsGrid, row: isize, col: isize) -> Option<ChartRef> {
        if row < 0
            || row as usize >= grid.current_page.len()
            || col < 0
            || col as usize >= grid.current_page[row as usize].len()
        {
            return None;
        }
        grid.current_page[row as usize][col as usize].clone()
    }

    // -------------------------------------------------------------------
    // metricsgrid_test.go
    // -------------------------------------------------------------------

    // Go: TestCalculateChartDimensions_RespectsMinimums
    #[test]
    fn calculate_chart_dimensions_respects_minimums() {
        let (grid, _dir) = new_metrics_grid(2, 2, 200, 80, None);

        let d = grid.calculate_chart_dimensions(10, 5); // small on purpose
        assert!(d.cell_w >= MIN_CHART_WIDTH);
        assert!(d.cell_h >= MIN_CHART_HEIGHT);
    }

    // Go: TestMetricsGrid_Render_EmptyGridShowsSectionHeader
    #[test]
    fn metrics_grid_render_empty_grid_shows_section_header() {
        let (grid, _dir) = new_metrics_grid(2, 2, 200, 80, None);

        let dims = grid.calculate_chart_dimensions(200, 80);

        let out = view_string(&grid, dims);
        assert!(
            out.contains("Metrics"),
            "section header should always be present"
        );
    }

    // Go: TestMetricsGrid_Lifecycle
    #[test]
    fn metrics_grid_lifecycle() {
        // 1 row x 2 cols so 3 charts produce 2 pages.
        let (w, h) = (200, 20);
        let (mut grid, _dir) = new_metrics_grid(1, 2, w, h, None);

        let m = history(vec![
            ("zeta", metric(&[1.0], &[1.0])),
            ("alpha", metric(&[1.0], &[2.0])),
            ("beta", metric(&[1.0], &[3.0])),
        ]);
        let created = grid.process_history(&m);
        assert!(
            created,
            "ingestion should report that there is something to draw"
        );
        grid.update_dimensions(w, h);

        let dims = grid.calculate_chart_dimensions(w, h);
        let out = view_string(&grid, dims);

        let a = index_of(&out, "alpha");
        let b = index_of(&out, "beta");
        let z = index_of(&out, "zeta");
        assert!(a > 0, "alpha should be present in view");
        assert!(b > 0, "beta should be present in view");
        assert_eq!(z, -1, "zeta should not be present in view");
        assert!(
            a < b,
            "expected alpha before beta as chart should be sorted alphabetically"
        );
        assert!(
            out.contains(" [1-2 of 3]"),
            "expected nav info for 2-wide page over 3 total charts"
        );

        grid.navigate(1);
        let out = view_string(&grid, dims);
        let a = index_of(&out, "alpha");
        let b = index_of(&out, "beta");
        let z = index_of(&out, "zeta");
        assert_eq!(a, -1, "alpha should not be present in view");
        assert_eq!(b, -1, "beta should not be present in view");
        assert!(z > 0, "zeta should be present in view");
        assert!(
            out.contains(" [3-3 of 3]"),
            "expected nav info for 1-wide page over 3 total charts"
        );
    }

    // Go: TestMetricsGrid_Navigate_ClearsMainChartFocus
    #[test]
    fn metrics_grid_navigate_clears_main_chart_focus() {
        // PARITY: Go builds the zero value `&leet.Focus{}` (Row/Col 0), not
        // NewFocus() (Row/Col -1).
        let f = Rc::new(RefCell::new(Focus {
            focus_type: FocusType::None,
            row: 0,
            col: 0,
            title: String::new(),
        }));
        let (w, h) = (120, 20);
        // 1 row x 1 cols so 2 charts produce 2 pages.
        let (mut grid, _dir) = new_metrics_grid(1, 1, w, h, Some(Rc::clone(&f)));
        let m = history(vec![
            ("alpha", metric(&[1.0], &[1.0])),
            ("beta", metric(&[1.0], &[2.0])),
        ]);
        grid.process_history(&m);
        grid.update_dimensions(w, h);

        // Focus on the first metric chart.
        {
            let mut f = f.borrow_mut();
            f.focus_type = FocusType::MainChart;
            f.row = 0;
            f.col = 0;
            f.title = "alpha".to_string();
        }

        grid.navigate(1);
        let f = f.borrow();
        assert_eq!(
            f.focus_type,
            FocusType::MainChart,
            "first chart should be focused after navigation"
        );
        assert_eq!(f.row, 0);
        assert_eq!(f.col, 0);
    }

    // Go: TestMetricsGrid_NavigateHomeEnd
    #[test]
    fn metrics_grid_navigate_home_end() {
        // 1x1 grid so each chart lives on its own page.
        let (w, h) = (120, 20);
        let (mut grid, _dir) = new_metrics_grid(1, 1, w, h, None);

        grid.process_history(&history(vec![
            ("alpha", metric(&[1.0], &[1.0])),
            ("beta", metric(&[1.0], &[2.0])),
            ("gamma", metric(&[1.0], &[3.0])),
        ]));
        grid.update_dimensions(w, h);

        // Nav forward: page 0 -> 1 -> 2.
        grid.navigate(1);
        grid.navigate(1);
        let dims = grid.calculate_chart_dimensions(w, h);
        assert!(
            view_string(&grid, dims).contains("[3-3 of 3]"),
            "navigated to last page"
        );

        grid.navigate_home();
        assert!(
            view_string(&grid, dims).contains("[1-1 of 3]"),
            "NavigateHome returns to first page"
        );

        grid.navigate_end();
        assert!(
            view_string(&grid, dims).contains("[3-3 of 3]"),
            "NavigateEnd jumps to last page"
        );
    }

    // Go: TestMetricsGrid_PreservesFocusAcrossHistoryUpdates
    #[test]
    fn metrics_grid_preserves_focus_across_history_updates() {
        // PARITY: Go builds the zero value `&leet.Focus{}` (Row/Col 0), not
        // NewFocus() (Row/Col -1).
        let f = Rc::new(RefCell::new(Focus {
            focus_type: FocusType::None,
            row: 0,
            col: 0,
            title: String::new(),
        }));
        let (w, h) = (120, 20);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, Some(Rc::clone(&f)));
        let m = history(vec![
            ("alpha", metric(&[1.0], &[1.0])),
            ("beta", metric(&[1.0], &[2.0])),
        ]);
        grid.process_history(&m);
        grid.update_dimensions(w, h);

        // Focus on the first metric chart.
        {
            let mut f = f.borrow_mut();
            f.focus_type = FocusType::MainChart;
            f.row = 0;
            f.col = 0;
            f.title = "alpha".to_string();
        }

        let m = history(vec![("gamma", metric(&[2.0], &[3.0]))]);
        grid.process_history(&m);
        assert_eq!(
            f.borrow().title,
            "alpha",
            "expected focus restored to previous title"
        );
    }

    /// computeAdjustedX builds a grid-absolute X such that relX within the chart equals wantRelX.
    fn compute_adjusted_x(
        chart: &ChartRef,
        cell_w_with_pad: isize,
        col: isize,
        want_rel_x: isize,
    ) -> isize {
        let chart_start_x = col * cell_w_with_pad;
        let mut graph_start_x = chart_start_x + 1;
        let ch = chart.borrow();
        if ch.y_step() > 0 {
            graph_start_x += ch.origin().x as isize + 1;
        }
        graph_start_x + want_rel_x
    }

    /// Go `int(math.Round((anchor - ViewMinX) / (ViewMaxX - ViewMinX) * GraphWidth))`
    /// — the rel-pixel computation shared by the inspection tests.
    fn rel_px_for_anchor(chart: &ChartRef, anchor: f64) -> isize {
        let ch = chart.borrow();
        ((anchor - ch.view_min_x()) / (ch.view_max_x() - ch.view_min_x()) * ch.graph_width() as f64)
            .round() as isize
    }

    // Go: TestMetricsGrid_Inspection_FocusedOnly
    #[test]
    fn metrics_grid_inspection_focused_only() {
        let (w, h) = (240, 60);
        let (mut grid, _dir) = new_metrics_grid(1, 2, w, h, None);

        // Two charts: both share the same view initially.
        let hist = history(vec![
            (
                "alpha",
                metric(
                    &[0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                    &[10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                ),
            ),
            (
                "beta",
                metric(
                    &[0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                    &[100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
                ),
            ),
        ]);
        let created = grid.process_history(&hist);
        assert!(created);
        grid.update_dimensions(w, h);

        // Get dimensions + target chart to compute adjustedX.
        let dims = grid.calculate_chart_dimensions(w, h);
        let ch0 = test_chart_at(&grid, 0, 0).expect("chart at (0,0)");

        // Choose anchor X=3 -> rel pixel.
        let rel_px = rel_px_for_anchor(&ch0, 3.0);
        let adj_x = compute_adjusted_x(&ch0, dims.cell_w_with_padding, 0, rel_px);

        // Start non-synced inspection on (row=0,col=0).
        grid.start_inspection(adj_x, 0, 0, dims, false /*synced*/);
        assert!(ch0.borrow().is_inspecting());
        assert!(
            !test_chart_at(&grid, 0, 1).unwrap().borrow().is_inspecting(),
            "other chart should not be inspecting"
        );

        // Move to X=5; only the focused chart updates.
        let rel_px = rel_px_for_anchor(&ch0, 5.0);
        let adj_x = compute_adjusted_x(&ch0, dims.cell_w_with_padding, 0, rel_px);
        grid.update_inspection(adj_x, 0, 0, dims);

        let (x0, _, active) = ch0.borrow().inspection_data();
        assert!(active);
        assert_in_delta(5.0, x0, 1e-6);
        assert!(!test_chart_at(&grid, 0, 1).unwrap().borrow().is_inspecting());

        // End clears only the focused one.
        grid.end_inspection();
        assert!(!ch0.borrow().is_inspecting());
    }

    // Go: TestMetricsGrid_Inspection_Synchronized_BroadcastAndEnd
    #[test]
    fn metrics_grid_inspection_synchronized_broadcast_and_end() {
        let (w, h) = (240, 60);
        let (mut grid, _dir) = new_metrics_grid(1, 2, w, h, None);

        // alpha has dense steps, beta has sparse to exercise nearestIndex tie-breaks.
        let hist = history(vec![
            (
                "alpha",
                metric(
                    &[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
                    &[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
                ),
            ),
            (
                "beta",
                metric(&[0.0, 2.0, 4.0, 6.0, 8.0], &[20.0, 40.0, 60.0, 80.0, 100.0]),
            ),
        ]);
        assert!(grid.process_history(&hist));
        grid.update_dimensions(w, h);

        let dims = grid.calculate_chart_dimensions(w, h);

        let ch_a = test_chart_at(&grid, 0, 0).expect("chart at (0,0)");
        let ch_b = test_chart_at(&grid, 0, 1).expect("chart at (0,1)");

        // Start synchronized at X=3 on alpha.
        let rel_px = rel_px_for_anchor(&ch_a, 3.0);
        let adj_x = compute_adjusted_x(&ch_a, dims.cell_w_with_padding, 0, rel_px);
        grid.start_inspection(adj_x, 0, 0, dims, /*synced*/ true);
        // Go `TestSyncInspectActive` (testhelpers.go): the field is read directly.
        assert!(grid.sync_inspect_active);

        // Both charts should now be inspecting near the anchor X.
        let (x_a, _, a_active) = ch_a.borrow().inspection_data();
        let (x_b, _, b_active) = ch_b.borrow().inspection_data();
        assert!(a_active);
        assert!(b_active);
        assert_in_delta(3.0, x_a, 1e-6); // alpha matches anchor exactly

        // For beta (X: {0,2,4,6,8}), nearest to 3 is a tie (2 and 4). Implementation picks the lower (2).
        assert_in_delta(2.0, x_b, 1e-6);

        // Move synchronized anchor to ~X=7.
        let rel_px = rel_px_for_anchor(&ch_a, 7.0);
        let adj_x = compute_adjusted_x(&ch_a, dims.cell_w_with_padding, 0, rel_px);
        grid.update_inspection(adj_x, 0, 0, dims);

        let (x_a, _, _) = ch_a.borrow().inspection_data();
        let (x_b, _, _) = ch_b.borrow().inspection_data();
        assert_in_delta(7.0, x_a, 1e-6);
        // For beta, nearest to 7 is 6 (tie 6/8 -> lower).
        assert_in_delta(6.0, x_b, 1e-6);

        // End synchronized session should clear both.
        grid.end_inspection();
        assert!(!grid.sync_inspect_active);
        assert!(!ch_a.borrow().is_inspecting());
        assert!(!ch_b.borrow().is_inspecting());
    }

    // Go: TestMetricsGrid_MultiSeries_PromoteAndRemoveSeries_PrunesEmptyCharts
    #[test]
    fn metrics_grid_multi_series_promote_and_remove_series_prunes_empty_charts() {
        let (w, h) = (200, 24);
        let (mut grid, _dir) = new_metrics_grid(1, 1, w, h, None);

        // Two different series keys simulate two different runs.
        const RUN_A: &str = "/wandb/runA.wandb";
        const RUN_B: &str = "/wandb/runB.wandb";

        let mut m = history(vec![("loss", metric(&[1.0], &[1.0]))]);
        m.run_path = RUN_A.to_string();
        let created = grid.process_history(&m);
        assert!(created);

        let mut m = history(vec![("loss", metric(&[1.0], &[2.0]))]);
        m.run_path = RUN_B.to_string();
        let created = grid.process_history(&m);
        assert!(created);

        let ch = test_chart_at(&grid, 0, 0).expect("chart at (0,0)");
        assert_eq!(ch.borrow().series_count(), 2);
        assert_eq!(
            ch.borrow().draw_order(),
            vec![RUN_A.to_string(), RUN_B.to_string()],
            "expected insertion order by default"
        );

        // Promote runA to top; order should end with runA (topmost).
        grid.promote_series_to_top(RUN_A);
        assert_eq!(
            ch.borrow().draw_order(),
            vec![RUN_B.to_string(), RUN_A.to_string()]
        );

        // Remove runB: chart remains but is now single-series.
        grid.remove_series(RUN_B);
        assert_eq!(ch.borrow().series_count(), 1);
        assert_eq!(ch.borrow().draw_order(), vec![RUN_A.to_string()]);

        // Remove runA: chart should be pruned entirely from the grid.
        grid.remove_series(RUN_A);
        assert_eq!(grid.chart_count(), 0);
        assert!(
            test_chart_at(&grid, 0, 0).is_none(),
            "expected chart removed after last series removed"
        );
    }

    // -------------------------------------------------------------------
    // metricsfilter_test.go
    // -------------------------------------------------------------------

    // Go: TestMetricsGridFilter_ApplyAndClear
    #[test]
    fn metrics_grid_filter_apply_and_clear() {
        let (w, h) = (240, 80);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);

        let m = history(vec![
            ("train/loss", metric(&[1.0], &[0.9])),
            ("accuracy", metric(&[1.0], &[0.71])),
            ("val/accuracy", metric(&[1.0], &[0.69])),
        ]);
        grid.process_history(&m);

        let dims = grid.calculate_chart_dimensions(w, h);

        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(out.contains("accuracy"));

        grid.enter_filter_mode();
        type_string(&mut grid, "loss");
        grid.exit_filter_mode(true);
        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(!out.contains("accuracy"));

        grid.clear_filter();
        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(out.contains("val/accuracy"));
    }

    // Go: TestMetricsGridFilter_NewChartsRespectActiveFilter
    #[test]
    fn metrics_grid_filter_new_charts_respect_active_filter() {
        let (w, h) = (80, 60);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);

        let m = history(vec![
            ("train/loss", metric(&[1.0], &[1.0])),
            ("accuracy", metric(&[1.0], &[0.5])),
        ]);
        grid.process_history(&m);
        let dims = grid.calculate_chart_dimensions(w, h);

        grid.enter_filter_mode();
        type_string(&mut grid, "loss");
        grid.exit_filter_mode(true);

        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(!out.contains("accuracy"));

        // New charts arrive after filter applied.
        let m = history(vec![
            ("val/loss", metric(&[2.0], &[0.8])),
            ("val/accuracy", metric(&[0.8], &[0.6])),
        ]);
        grid.process_history(&m);

        let out = view_string(&grid, dims);
        assert!(out.contains("val/loss"));
        assert!(!out.contains("val/accuracy"));
    }

    // Go: TestMetricsGridFilter_SwitchFilter
    #[test]
    fn metrics_grid_filter_switch_filter() {
        let (w, h) = (240, 80);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);
        let m = history(vec![
            ("train/loss", metric(&[1.0], &[0.9])),
            ("accuracy", metric(&[1.0], &[0.7])),
            ("val/accuracy", metric(&[1.0], &[0.65])),
        ]);
        grid.process_history(&m);
        let dims = grid.calculate_chart_dimensions(w, h);

        grid.enter_filter_mode();
        type_string(&mut grid, "loss");
        grid.exit_filter_mode(true);
        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(!out.contains("accuracy"));

        // Switch to "acc".
        grid.clear_filter();
        grid.enter_filter_mode();
        type_string(&mut grid, "acc");
        grid.exit_filter_mode(true);
        let out = view_string(&grid, dims);
        assert!(!out.contains("train/loss"));
        assert!(out.contains("accuracy"));
        assert!(out.contains("val/accuracy"));
    }

    // Go: TestMetricsGridFilter_EdgeCases
    #[test]
    fn metrics_grid_filter_edge_cases() {
        struct Tc {
            name: &'static str,
            metrics: Vec<(&'static str, MetricData)>,
            filter: &'static str,
            expect_visible: &'static [&'static str],
            expect_hidden: &'static [&'static str],
        }

        let tests = vec![
            Tc {
                name: "empty_filter_shows_all",
                metrics: vec![
                    ("a", metric(&[0.0], &[1.0])),
                    ("b", metric(&[0.0], &[2.0])),
                    ("c", metric(&[0.0], &[3.0])),
                ],
                filter: "",
                expect_visible: &["a", "b", "c"],
                expect_hidden: &[],
            },
            Tc {
                name: "wildcard_star_shows_all",
                metrics: vec![
                    ("train/loss", metric(&[0.0], &[1.0])),
                    ("val/loss", metric(&[0.0], &[2.0])),
                    ("accuracy", metric(&[0.0], &[3.0])),
                ],
                filter: "*",
                expect_visible: &["train/loss", "val/loss", "accuracy"],
                expect_hidden: &[],
            },
            Tc {
                name: "glob_pattern_with_star",
                metrics: vec![
                    ("train/loss", metric(&[0.0], &[1.0])),
                    ("train/acc", metric(&[0.0], &[2.0])),
                    ("val/loss", metric(&[0.0], &[3.0])),
                    ("test", metric(&[0.0], &[4.0])),
                ],
                filter: "train/*",
                expect_visible: &["train/loss", "train/acc"],
                expect_hidden: &["val/loss", "test"],
            },
            Tc {
                name: "case_insensitive_match",
                metrics: vec![
                    ("Train/Loss", metric(&[0.0], &[1.0])),
                    ("TRAIN/ACC", metric(&[0.0], &[2.0])),
                    ("val/LOSS", metric(&[0.0], &[3.0])),
                ],
                filter: "train",
                expect_visible: &["Train/Loss", "TRAIN/ACC"],
                expect_hidden: &["val/LOSS"],
            },
        ];

        for tt in tests {
            let (w, h) = (240, 80);
            let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);
            let m = history(tt.metrics);
            grid.process_history(&m);
            let dims = grid.calculate_chart_dimensions(w, h);

            // Switch to glob match mode (defaults to regex).
            grid.toggle_filter_match_mode();
            grid.enter_filter_mode();
            type_string(&mut grid, tt.filter);
            grid.exit_filter_mode(true);
            let view = view_string(&grid, dims);

            for chart in tt.expect_visible {
                assert!(
                    view.contains(chart),
                    "{}: chart should be visible: {chart}",
                    tt.name
                );
            }
            for chart in tt.expect_hidden {
                assert!(
                    !view.contains(chart),
                    "{}: chart should be hidden: {chart}",
                    tt.name
                );
            }
        }
    }

    // Go: TestMetricsGridFilter_PreviewAndCancelAndApply
    #[test]
    fn metrics_grid_filter_preview_and_cancel_and_apply() {
        let (w, h) = (240, 80);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);
        let m = history(vec![
            ("loss", metric(&[0.0], &[1.0])),
            ("acc", metric(&[0.0], &[2.0])),
            ("val/acc", metric(&[0.0], &[3.0])),
            ("unrelated/x", metric(&[0.0], &[4.0])),
        ]);
        grid.process_history(&m);
        let dims = grid.calculate_chart_dimensions(w, h);

        // Start typing "lo", then cancel (Esc behavior).
        grid.enter_filter_mode();
        type_string(&mut grid, "lo");
        assert!(grid.filtered_chart_count() >= 1);
        grid.exit_filter_mode(false); // cancel

        let view = view_string(&grid, dims);
        assert!(view.contains("loss"));
        assert!(view.contains("acc"));
        assert!(view.contains("val/acc"));

        // Start another filter "acc", add data while typing, then apply.
        grid.enter_filter_mode();
        type_string(&mut grid, "acc");
        let m = history(vec![("val/loss", metric(&[1.0], &[5.0]))]);
        grid.process_history(&m);
        grid.exit_filter_mode(true);

        let view = view_string(&grid, dims);
        assert!(view.contains("acc"));
        assert!(view.contains("val/acc"));
        assert!(!view.contains("loss")); // filtered out
        assert!(!view.contains("val/loss")); // filtered out
    }

    // Go: TestMetricsGridFilter_ConcurrentApplyAndUpdate_NoDeadlock.
    //
    // PARITY: the Go test races ProcessHistory against filter application to
    // prove mg.mu freedom from deadlock. The port is single-threaded (S9
    // deleted; Rc/RefCell are !Send), so the same operation sequences run
    // sequentially to pin the state-machine behavior instead.
    #[test]
    fn metrics_grid_filter_concurrent_apply_and_update_no_deadlock() {
        let (w, h) = (140, 60);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);
        let m = history(vec![
            ("train/loss", metric(&[1.0], &[0.5])),
            ("accuracy", metric(&[1.0], &[0.8])),
        ]);
        grid.process_history(&m);

        for i in 0..50i64 {
            // PARITY: Go's `"metric_" + fmt.Sprint('a'+(i%3))` formats the
            // INT sum ('a' is an untyped rune constant promoted to int), so
            // the names are metric_97/metric_98/metric_99.
            let m = history(vec![(
                &format!("metric_{}", 97 + (i % 3)) as &str,
                metric(&[(2 + i) as f64], &[i as f64 * 0.1]),
            )]);
            grid.process_history(&m);
        }

        let patterns = ["loss", "acc", "*_1*", ""];
        for i in 0..40usize {
            grid.enter_filter_mode();
            type_string(&mut grid, patterns[i % patterns.len()]);
            grid.exit_filter_mode(true);
            grid.apply_filter();
        }

        let out = view_string(&grid, grid.calculate_chart_dimensions(w, h));
        assert!(!out.is_empty(), "grid should render");
        assert!(out.contains("Metrics"), "section header should render");
    }

    // Go: TestMetricsGrid_RegexFilter
    #[test]
    fn metrics_grid_regex_filter() {
        let (w, h) = (240, 80);
        let (mut grid, _dir) = new_metrics_grid(2, 2, w, h, None);

        let m = history(vec![
            ("train/loss", metric(&[1.0], &[0.5])),
            ("val/loss", metric(&[1.0], &[0.6])),
            ("train/acc", metric(&[1.0], &[0.9])),
        ]);
        grid.process_history(&m);
        let dims = grid.calculate_chart_dimensions(w, h);

        // Default mode is regex. Filter for "ends with loss".
        grid.enter_filter_mode();
        type_string(&mut grid, "loss$");
        grid.exit_filter_mode(true);

        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(out.contains("val/loss"));
        assert!(!out.contains("train/acc"));

        // Toggle to glob mode.
        grid.clear_filter();
        grid.enter_filter_mode();
        grid.toggle_filter_match_mode();
        type_string(&mut grid, "loss$");
        grid.exit_filter_mode(true);
        let out = view_string(&grid, dims);
        assert!(!out.contains("train/loss")); // Glob shouldn't match regex syntax.

        // Test glob syntax.
        grid.clear_filter();
        grid.enter_filter_mode();
        type_string(&mut grid, "train/*");
        grid.exit_filter_mode(true);
        let out = view_string(&grid, dims);
        assert!(out.contains("train/loss"));
        assert!(out.contains("train/acc"));
        assert!(!out.contains("val/loss"));
    }
}
