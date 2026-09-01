//! Port of `core/internal/leet/frenchfrieschart.go`: the "French Fries"
//! chart — one row band per series, with the visible time window compressed
//! into color-coded buckets, producing a compact heatmap.
//!
//! Render target: Go builds an ANSI string grid (`[][]string` joined with
//! newlines); the port draws into [`crate::canvas::Canvas`] per
//! docs/PORTING.md (Canvas render-target row) — tests diff
//! `Canvas::text_rows` where Go diffs `stripANSI(View())`. Cells Go leaves
//! as unstyled `" "` are either written as unstyled `' '` cells (inside the
//! plot area) or left as the canvas default Null rune (outside it); both
//! render as unstyled spaces.
//!
//! Style resolution: Go pre-renders the palette to ANSI strings at
//! construction via the `darkBackground` global (`renderFrenchFriesCells`);
//! the port keeps the palette as [`AdaptiveColor`]s and resolves at draw
//! time through the chart's `dark_background` flag, exactly like
//! `epoch_line_chart.rs` (DIVERGENCE(S13) recorded there — leet-tui owns
//! the flag and pushes it via [`FrenchFriesChart::set_dark_background`]).
//!
//! DIVERGENCE (time labels render in UTC): Go renders the bottom time axis
//! with `time.Unix(..).Local()`; the port renders UTC — see
//! [`crate::timeseries_line_chart::time_unix_utc`] for the rationale and
//! harness contract (differential runs pin the oracle to TZ=UTC).
//!
//! `systemTimeLayouts` / `fitTimeLayouts` / `compactDuration` are Go
//! package-level functions declared in timeserieslinechart.go:477-568;
//! this module reuses the `timeseries_line_chart` ports (the declaring
//! module hosts them, as in Go).

use std::collections::{HashMap, HashSet};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use leet_data::config::DEFAULT_FRENCH_FRIES_COLOR_SCHEME;
use leet_data::system_metrics::{DEFAULT_SYSTEM_METRIC_SERIES_NAME, MetricDef};
use leet_data::width::text_width;

use crate::canvas::{Canvas, Cell, CellStyle, Point};
use crate::epoch_line_chart::{
    PARKED_CANVAS_SIZE, go_max, go_min, inspection_legend_style, inspection_line_style, is_finite,
    truncate_title,
};
use crate::styles::{
    AdaptiveColor, BOX_LIGHT_VERTICAL, CHART_TITLE_HEIGHT, UNICODE_EM_DASH,
    default_dark_background, french_fries_colors,
};
use crate::timeseries_line_chart::{
    compact_duration, fit_time_layouts, system_time_layouts, time_unix_utc,
};

/// Go: `frenchFriesCell = "█"`.
const FRENCH_FRIES_CELL: char = '█';

/// Go `renderFrenchFriesCells` (frenchfrieschart.go:16-28).
///
/// PARITY: Go eagerly renders each palette entry to a styled ANSI "█"
/// string; the port defers resolution to draw time (module doc), so this
/// reduces to the empty-palette default fallback.
fn render_french_fries_cells(colors: &[AdaptiveColor]) -> Vec<AdaptiveColor> {
    let colors = if colors.is_empty() {
        french_fries_colors(DEFAULT_FRENCH_FRIES_COLOR_SCHEME)
    } else {
        colors
    };
    colors.to_vec()
}

/// One time-aligned column of raw values, keyed by series name.
#[derive(Debug, Clone)]
struct FrenchFriesSample {
    timestamp: i64,
    values: HashMap<String, f64>,
}

/// Crosshair state for per-column inspection.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
struct FrenchFriesInspection {
    active: bool,
    mouse_x: i64,
    data_x: f64,
}

/// One horizontal band of rows rendering a single series.
#[derive(Debug, Clone, Default)]
struct FrenchFriesRowBand {
    series_name: String,
    label: String,
    start_y: i64,
    height: i64,
}

impl FrenchFriesRowBand {
    fn center_y(&self) -> i64 {
        if self.height <= 0 {
            return self.start_y;
        }
        self.start_y + (self.height - 1) / 2
    }
}

/// Computed cell geometry for one draw pass.
#[derive(Debug, Clone, Default)]
struct FrenchFriesLayout {
    label_width: i64,
    plot_start_x: i64,
    plot_start_y: i64,
    plot_width: i64,
    plot_height: i64,
    time_axis_y: i64,
    max_visible_rows: i64,
    bands: Vec<FrenchFriesRowBand>,
}

/// One averaged bucket cell (`ok` mirrors Go's presence flag).
#[derive(Debug, Clone, Copy, PartialEq, Default)]
struct FrenchFriesBucketCell {
    timestamp: i64,
    value: f64,
    ok: bool,
}

/// FrenchFriesChart renders one row per series and compresses the visible
/// time window into color-coded buckets, producing a compact heatmap.
#[derive(Debug)]
pub struct FrenchFriesChart {
    def: MetricDef,

    width: i64,
    height: i64,

    /// samples retain the full observed history so the chart can reuse the
    /// same windowing and zoom semantics as the underlying line chart.
    samples: Vec<FrenchFriesSample>,

    series: HashSet<String>,
    ordered_series: Vec<String>,
    series_dirty: bool,

    /// PARITY: write-only in Go as well — nothing in the package reads it
    /// back (TimeSeriesLineChart has a LastUpdate accessor; FrenchFriesChart
    /// does not).
    #[allow(dead_code)]
    last_update: SystemTime,
    // pub(crate): crate tests read the synced window (Go tests live in the
    // same package); see docs/PORTING.md Testing conventions.
    pub(crate) view_min_x: f64,
    pub(crate) view_max_x: f64,
    pub(crate) view_ready: bool,

    inspection: FrenchFriesInspection,

    dirty: bool,
    /// Go: `rendered string` — the port renders into a canvas (module doc).
    canvas: Canvas,

    /// Go: `coloredCells []string` (pre-rendered ANSI cells); the port keeps
    /// the palette and resolves per draw (see render_french_fries_cells).
    colored_cells: Vec<AdaptiveColor>,

    /// Which AdaptiveColor variant draw() resolves (DIVERGENCE(S13), module
    /// doc).
    dark_background: bool,
}

/// Go `FrenchFriesChartParams`.
pub struct FrenchFriesChartParams<'a> {
    pub width: i64,
    pub height: i64,
    pub def: &'a MetricDef,
    pub colors: &'a [AdaptiveColor],
    pub now: SystemTime,
}

impl FrenchFriesChart {
    /// Go `NewFrenchFriesChart`.
    pub fn new(params: &FrenchFriesChartParams) -> FrenchFriesChart {
        let mut chart = FrenchFriesChart {
            // PARITY: Go stores the shared *MetricDef; cloned at the
            // boundary (docs/PORTING.md) — defs are immutable after
            // construction.
            def: params.def.clone(),
            width: 0,
            height: 0,
            samples: Vec::new(),
            series: HashSet::new(),
            ordered_series: Vec::new(),
            series_dirty: true,
            last_update: params.now,
            view_min_x: 0.0,
            view_max_x: 0.0,
            view_ready: false,
            inspection: FrenchFriesInspection::default(),
            dirty: true,
            canvas: Canvas::new(0, 0),
            colored_cells: render_french_fries_cells(params.colors),
            dark_background: default_dark_background(),
        };

        chart.resize(params.width, params.height);
        chart
    }

    /// Title returns the title to display on the metric chart.
    pub fn title(&self) -> String {
        self.def.title()
    }

    /// TitleDetail returns the `[..]` series-count suffix for the header.
    pub fn title_detail(&mut self) -> String {
        let total = self.sorted_series_names().len() as i64;
        if total <= 1 {
            return String::new();
        }

        let layout = self.layout();
        if layout.max_visible_rows <= 0 || total <= layout.max_visible_rows {
            return format!("[{total}]");
        }

        summarize_french_fries_series(&self.visible_series_names(layout.max_visible_rows), total)
    }

    /// Go `View() string`: draws if needed and returns the render target.
    pub fn view(&mut self) -> &Canvas {
        self.draw_if_needed();
        &self.canvas
    }

    /// Park minimizes memory for off-screen charts by shrinking to 1x1.
    pub fn park(&mut self) {
        self.resize(PARKED_CANVAS_SIZE, PARKED_CANVAS_SIZE);
    }

    /// Resize records the new outer dimensions and marks the chart dirty.
    pub fn resize(&mut self, width: i64, height: i64) {
        let width = width.max(0);
        let height = height.max(0);
        if self.width == width && self.height == height {
            return;
        }

        self.width = width;
        self.height = height;
        self.dirty = true;
    }

    /// DrawIfNeeded draws only if the chart is marked dirty.
    pub fn draw_if_needed(&mut self) {
        if self.dirty {
            self.draw();
        }
    }

    /// AddDataPoint appends a value for a series at a timestamp, sharing the
    /// sample column with other series at the same (latest) timestamp.
    pub fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        let series_name = if series_name.is_empty() {
            DEFAULT_SYSTEM_METRIC_SERIES_NAME
        } else {
            series_name
        };
        // Go: `if _, ok := c.series[seriesName]; !ok { add; seriesDirty }`.
        if self.series.insert(series_name.to_string()) {
            self.series_dirty = true;
        }

        if self.samples.is_empty() || self.samples[self.samples.len() - 1].timestamp != timestamp {
            self.samples.push(FrenchFriesSample {
                timestamp,
                values: HashMap::new(),
            });
        }
        let last = self.samples.len() - 1;
        self.samples[last]
            .values
            .insert(series_name.to_string(), value);
        self.last_update = go_time_unix(timestamp);

        if !self.view_ready {
            self.set_default_view_window();
        }

        self.dirty = true;
    }

    /// GraphWidth returns the plot-area width in columns.
    // &mut self: layout() reaches the sortedSeriesNames memo (Go mutates
    // through the pointer receiver on these read paths too).
    pub fn graph_width(&mut self) -> i64 {
        self.layout().plot_width
    }

    /// GraphHeight returns the plot-area height in rows.
    pub fn graph_height(&mut self) -> i64 {
        self.layout().plot_height
    }

    /// GraphStartX returns the plot-area X offset within the bordered pane.
    pub fn graph_start_x(&mut self) -> i64 {
        1 + self.layout().plot_start_x
    }

    /// GraphStartY returns the plot-area Y offset within the bordered pane.
    pub fn graph_start_y(&mut self) -> i64 {
        1 + CHART_TITLE_HEIGHT + self.layout().plot_start_y
    }

    /// HandleZoom is a no-op: zoom is owned by the paired line chart.
    pub fn handle_zoom(&mut self, _direction: &str, _mouse_x: i64) {}

    /// ToggleYScale reports false: the heatmap has no Y scale.
    pub fn toggle_y_scale(&mut self) -> bool {
        false
    }

    /// IsLogY reports false: the heatmap has no Y scale.
    pub fn is_log_y(&self) -> bool {
        false
    }

    /// SupportsHeatmap reports true.
    pub fn supports_heatmap(&self) -> bool {
        true
    }

    /// ToggleHeatmapMode reports false: the bare chart is always a heatmap.
    pub fn toggle_heatmap_mode(&mut self) -> bool {
        false
    }

    /// IsHeatmapMode reports true.
    pub fn is_heatmap_mode(&self) -> bool {
        true
    }

    /// ViewModeLabel describes the active time window for the header.
    pub fn view_mode_label(&mut self) -> String {
        let (view_min_x, view_max_x) = self.effective_view_window();
        let span = view_max_x - view_min_x;
        if span > 0.0 {
            // Go: "window " +
            // compactDuration(time.Duration(math.Round(span))*time.Second);
            // span > 0 so the u64 cast cannot wrap.
            return format!(
                "window {}",
                compact_duration(Duration::from_secs(span.round() as u64))
            );
        }
        let visible = (self.samples.len() as i64).min(self.graph_width());
        if visible <= 0 {
            return "heatmap".to_string();
        }
        format!("heatmap {visible} samples")
    }

    /// ScaleLabel returns the fixed "heatmap" scale tag.
    pub fn scale_label(&self) -> String {
        "heatmap".to_string()
    }

    /// SetViewWindow updates the time window used to bucket samples into
    /// columns.
    pub fn set_view_window(&mut self, min_x: f64, max_x: f64) {
        if !is_finite(min_x) || !is_finite(max_x) || max_x <= min_x {
            self.set_default_view_window();
            return;
        }
        if self.view_ready && self.view_min_x == min_x && self.view_max_x == max_x {
            return;
        }
        self.view_min_x = min_x;
        self.view_max_x = max_x;
        self.view_ready = true;
        self.dirty = true;
        if self.inspection.active {
            let data_x = self.inspection.data_x;
            self.inspect_at_data_x(data_x);
        }
    }

    /// StartInspectionAt begins column inspection at a graph-local mouse X.
    pub fn start_inspection_at(&mut self, mouse_x: i64, _mouse_y: i64) {
        if self.graph_width() <= 0 || self.graph_height() <= 0 {
            return;
        }
        self.inspection.active = true;
        self.update_inspection_at(mouse_x, 0);
    }

    /// UpdateInspectionAt moves the inspected column.
    pub fn update_inspection_at(&mut self, mouse_x: i64, _mouse_y: i64) {
        if !self.inspection.active {
            return;
        }

        let layout = self.layout();
        if layout.plot_width <= 0 || layout.plot_height <= 0 || layout.bands.is_empty() {
            return;
        }

        // PARITY: Go max(0, min(plotWidth-1, mouseX)) — not clamp():
        // Ord::clamp panics when a zero plotWidth makes hi < lo.
        self.inspection.mouse_x = 0.max((layout.plot_width - 1).min(mouse_x));
        self.inspection.data_x = self.data_x_for_mouse(self.inspection.mouse_x, layout.plot_width);
        self.dirty = true;
    }

    /// EndInspection clears inspection state.
    pub fn end_inspection(&mut self) {
        self.inspection = FrenchFriesInspection::default();
        self.dirty = true;
    }

    /// IsInspecting reports whether column inspection is active.
    pub fn is_inspecting(&self) -> bool {
        self.inspection.active
    }

    /// InspectAtDataX anchors inspection at a data-space X (Unix seconds).
    pub fn inspect_at_data_x(&mut self, target_x: f64) {
        let layout = self.layout();
        if layout.plot_width <= 0 || layout.plot_height <= 0 || layout.bands.is_empty() {
            return;
        }
        self.inspection.active = true;
        self.inspection.mouse_x = self.bucket_for_data_x(target_x, layout.plot_width);
        self.inspection.data_x = target_x;
        self.dirty = true;
    }

    /// InspectionData returns `(dataX, 0, active)`.
    pub fn inspection_data(&self) -> (f64, f64, bool) {
        (self.inspection.data_x, 0.0, self.inspection.active)
    }

    fn draw(&mut self) {
        if self.width <= 0 || self.height <= 0 {
            // Go: c.rendered = "".
            self.canvas = Canvas::new(0, 0);
            self.dirty = false;
            return;
        }

        let layout = self.layout();
        // Go builds a fresh " "-filled [][]string each draw; a fresh canvas
        // of default (Null → space) cells is the grid equivalent.
        self.canvas = Canvas::new(self.width, self.height);

        let bucketed = self.bucketed_series(&layout);
        let mut selected_bucket: i64 = -1;
        if self.inspection.active {
            // PARITY: Go max/min shape (see update_inspection_at).
            selected_bucket = 0.max((layout.plot_width - 1).min(self.inspection.mouse_x));
        }

        for band in &layout.bands {
            for y in band.start_y..band.start_y + band.height {
                for x in 0..layout.plot_width {
                    let bucket = bucketed[band.series_name.as_str()][x as usize];
                    let mut cell = Cell::new_with_style(' ', CellStyle::default());
                    if bucket.ok {
                        cell = self.color_for_value(bucket.value);
                    }
                    self.canvas.set_cell(
                        Point {
                            x: layout.plot_start_x + x,
                            y,
                        },
                        cell,
                    );
                }
            }

            self.render_band_label(&layout, band);
        }

        self.render_inspection_hairline(&layout, selected_bucket);
        self.render_time_labels(&layout);
        self.render_inspection_labels(&layout, &bucketed);
        self.render_inspection_time_label(&layout, &bucketed);

        self.dirty = false;
    }

    fn render_band_label(&mut self, layout: &FrenchFriesLayout, band: &FrenchFriesRowBand) {
        if layout.label_width <= 0 || band.label.is_empty() {
            return;
        }
        let row = band.center_y();
        let mut label = band.label.clone();
        if text_width(&label) as i64 > layout.label_width - 1 {
            label = truncate_title(&label, layout.label_width - 1);
        }
        let start = (layout.label_width - 1 - text_width(&label) as i64).max(0);
        // PARITY: Go `for i, r := range label` yields BYTE offsets of rune
        // starts; char_indices matches (columns skip for multibyte runes).
        for (i, r) in label.char_indices() {
            if start + i as i64 >= layout.label_width - 1 {
                break;
            }
            self.canvas.set_cell(
                Point {
                    x: start + i as i64,
                    y: row,
                },
                Cell::new_with_style(r, CellStyle::default()),
            );
        }
    }

    fn render_inspection_hairline(&mut self, layout: &FrenchFriesLayout, selected_bucket: i64) {
        if !self.inspection.active || selected_bucket < 0 || selected_bucket >= layout.plot_width {
            return;
        }

        let x = layout.plot_start_x + selected_bucket;
        let style = inspection_line_style(self.dark_background);
        for y in 0..layout.plot_height {
            self.canvas.set_cell(
                Point { x, y },
                Cell::new_with_style(BOX_LIGHT_VERTICAL, style),
            );
        }
    }

    fn render_inspection_labels(
        &mut self,
        layout: &FrenchFriesLayout,
        bucketed: &HashMap<String, Vec<FrenchFriesBucketCell>>,
    ) {
        if !self.inspection.active || layout.plot_width <= 0 || layout.plot_height <= 0 {
            return;
        }
        // PARITY: Go max/min shape (see update_inspection_at).
        let bucket = 0.max((layout.plot_width - 1).min(self.inspection.mouse_x));
        let mut labels: HashMap<String, String> = HashMap::with_capacity(layout.bands.len());
        let mut max_label_width: i64 = 0;
        for band in &layout.bands {
            let mut label = UNICODE_EM_DASH.to_string();
            if let Some(cells_for_series) = bucketed.get(&band.series_name) {
                label = self
                    .inspection_value_label(&band.series_name, cells_for_series[bucket as usize]);
            }
            max_label_width = max_label_width.max(text_width(&label) as i64);
            labels.insert(band.series_name.clone(), label);
        }
        if max_label_width <= 0 {
            return;
        }

        let start_x = selected_label_start_x(bucket, layout.plot_width, max_label_width);
        let legend_style = inspection_legend_style(self.dark_background);
        for band in &layout.bands {
            let row = band.center_y();
            let mut label = labels[&band.series_name].clone();
            if text_width(&label) as i64 > max_label_width {
                label = truncate_title(&label, max_label_width);
            }
            // PARITY: byte offsets (see render_band_label).
            for (i, r) in label.char_indices() {
                let x = layout.plot_start_x + start_x + i as i64;
                if x < layout.plot_start_x || x >= layout.plot_start_x + layout.plot_width {
                    continue;
                }
                self.canvas
                    .set_cell(Point { x, y: row }, Cell::new_with_style(r, legend_style));
            }
        }
    }

    fn inspection_value_label(&self, series_name: &str, bucket: FrenchFriesBucketCell) -> String {
        let mut value_label = UNICODE_EM_DASH.to_string();
        if bucket.ok {
            value_label = self.def.unit.format(bucket.value);
        }

        let series_label = compact_system_metric_series_label(series_name);
        if series_label.is_empty() {
            return value_label;
        }
        format!("{series_label}: {value_label}")
    }

    fn render_time_labels(&mut self, layout: &FrenchFriesLayout) {
        if layout.time_axis_y < 0 || layout.plot_width <= 0 || self.height <= 0 {
            return;
        }
        let (view_min_x, view_max_x) = self.effective_view_window();
        if view_max_x <= view_min_x {
            return;
        }

        let y = layout.time_axis_y;
        // Go: time.Duration(math.Round(viewMaxX-viewMinX)) * time.Second.
        let span = (view_max_x - view_min_x).round() as i64;
        let layouts = system_time_layouts(span);

        // Go: time.Unix(int64(math.Round(x)), 0).Local() — the port renders
        // UTC (module doc DIVERGENCE).
        let min_label = fit_time_layouts(
            &time_unix_utc(view_min_x.round() as i64),
            layout.plot_width,
            layouts,
        );
        let max_label = fit_time_layouts(
            &time_unix_utc(view_max_x.round() as i64),
            layout.plot_width,
            layouts,
        );
        let max_pos = (layout.plot_width - text_width(&max_label) as i64).max(0);
        let mut labels: Vec<(String, i64)> = vec![(min_label, 0), (max_label, max_pos)];

        let mid_x = (view_min_x + view_max_x) / 2.0;
        let mid_text = fit_time_layouts(
            &time_unix_utc(mid_x.round() as i64),
            layout.plot_width,
            layouts,
        );
        let mid_pos = (layout.plot_width / 2 - text_width(&mid_text) as i64 / 2).max(0);
        if !mid_text.is_empty() && layout.plot_width >= text_width(&mid_text) as i64 * 3 {
            labels.push((mid_text, mid_pos));
        }

        for (text, pos) in &labels {
            // PARITY: byte offsets (see render_band_label).
            for (i, r) in text.char_indices() {
                let x = layout.plot_start_x + pos + i as i64;
                if x < layout.plot_start_x || x >= self.width {
                    continue;
                }
                self.canvas.set_cell(
                    Point { x, y },
                    Cell::new_with_style(r, CellStyle::default()),
                );
            }
        }
    }

    fn render_inspection_time_label(
        &mut self,
        layout: &FrenchFriesLayout,
        bucketed: &HashMap<String, Vec<FrenchFriesBucketCell>>,
    ) {
        if !self.inspection.active || layout.time_axis_y < 0 || layout.plot_width <= 0 {
            return;
        }

        // PARITY: Go max/min shape (see update_inspection_at).
        let bucket = 0.max((layout.plot_width - 1).min(self.inspection.mouse_x));
        let mut data_x = self.inspection.data_x;
        if let Some(ts) = bucket_timestamp(bucketed, bucket) {
            data_x = ts as f64;
        }

        let (view_min_x, view_max_x) = self.effective_view_window();
        let span = (view_max_x - view_min_x).round() as i64;
        // Go: time.Unix(int64(math.Round(dataX)), 0).Local() — UTC here
        // (module doc DIVERGENCE).
        let label = fit_time_layouts(
            &time_unix_utc(data_x.round() as i64),
            layout.plot_width,
            system_time_layouts(span),
        );

        if label.is_empty() {
            return;
        }
        let start_x = selected_label_start_x(bucket, layout.plot_width, text_width(&label) as i64);
        // Go: lipgloss.NewStyle().Bold(true).
        let bold = CellStyle {
            fg: None,
            bg: None,
            bold: true,
        };
        // PARITY: byte offsets (see render_band_label).
        for (i, r) in label.char_indices() {
            let x = layout.plot_start_x + start_x + i as i64;
            if x < layout.plot_start_x || x >= layout.plot_start_x + layout.plot_width {
                continue;
            }
            self.canvas.set_cell(
                Point {
                    x,
                    y: layout.time_axis_y,
                },
                Cell::new_with_style(r, bold),
            );
        }
    }

    fn layout(&mut self) -> FrenchFriesLayout {
        let mut layout = FrenchFriesLayout {
            plot_start_y: 0,
            time_axis_y: -1,
            ..Default::default()
        };
        if self.width <= 0 || self.height <= 0 {
            return layout;
        }

        let mut time_axis_rows = 0;
        if self.height >= 2 {
            time_axis_rows = 1;
            layout.time_axis_y = self.height - 1;
        }
        layout.plot_height = (self.height - time_axis_rows).max(0);
        layout.max_visible_rows = layout.plot_height;
        let visible_series = self.visible_series_names(layout.max_visible_rows);
        layout.bands = Vec::with_capacity(visible_series.len());

        let mut max_label_width: i64 = 0;
        let mut labels = vec![String::new(); visible_series.len()];
        for (i, name) in visible_series.iter().enumerate() {
            labels[i] = compact_system_metric_series_label(name);
            max_label_width = max_label_width.max(text_width(&labels[i]) as i64);
        }
        if max_label_width > 0 && self.width >= max_label_width + 2 {
            layout.label_width = max_label_width + 1;
        }
        layout.plot_start_x = layout.label_width;
        layout.plot_width = (self.width - layout.plot_start_x).max(0);
        if layout.plot_width == 0 {
            layout.label_width = 0;
            layout.plot_start_x = 0;
            layout.plot_width = self.width;
        }

        if visible_series.is_empty() || layout.plot_height <= 0 {
            return layout;
        }

        let base_band_height = (layout.plot_height / visible_series.len() as i64).max(1);
        let extra_rows =
            (layout.plot_height - visible_series.len() as i64 * base_band_height).max(0);
        let mut y: i64 = 0;
        for (i, name) in visible_series.iter().enumerate() {
            let mut band_height = base_band_height;
            if (i as i64) < extra_rows {
                band_height += 1;
            }
            layout.bands.push(FrenchFriesRowBand {
                series_name: name.clone(),
                label: labels[i].clone(),
                start_y: y,
                height: band_height,
            });
            y += band_height;
        }
        layout
    }

    /// Go `visibleSampleRange` (two sort.Search calls). If samples are not
    /// timestamp-sorted and start > end, the caller's slice expression
    /// panics — as Go's does.
    fn visible_sample_range(&self, view_min_x: f64, view_max_x: f64) -> (usize, usize) {
        // Go sort.Search: smallest index with the predicate true; the
        // predicate is negated verbatim for partition_point.
        #[allow(clippy::neg_cmp_op_on_partial_ord)]
        let start = self
            .samples
            .partition_point(|s| !((s.timestamp as f64) >= view_min_x));
        #[allow(clippy::neg_cmp_op_on_partial_ord)]
        let end = self
            .samples
            .partition_point(|s| !((s.timestamp as f64) > view_max_x));
        (start, end)
    }

    fn bucketed_series(
        &mut self,
        layout: &FrenchFriesLayout,
    ) -> HashMap<String, Vec<FrenchFriesBucketCell>> {
        let mut bucketed: HashMap<String, Vec<FrenchFriesBucketCell>> =
            HashMap::with_capacity(layout.bands.len());
        for band in &layout.bands {
            bucketed.insert(
                band.series_name.clone(),
                vec![FrenchFriesBucketCell::default(); layout.plot_width as usize],
            );
        }
        if layout.plot_width <= 0 {
            return bucketed;
        }

        let (view_min_x, view_max_x) = self.effective_view_window();
        if view_max_x <= view_min_x {
            return bucketed;
        }

        // Accumulate sum and count per bucket so the final value is an
        // average. Averaging makes the display stable when a single sample
        // shifts between neighbouring buckets due to a small view-window
        // change.
        #[derive(Clone, Copy, Default)]
        struct Accum {
            sum: f64,
            count: i64,
            timestamp: i64,
        }
        let mut accums: HashMap<String, Vec<Accum>> = HashMap::with_capacity(layout.bands.len());
        for band in &layout.bands {
            accums.insert(
                band.series_name.clone(),
                vec![Accum::default(); layout.plot_width as usize],
            );
        }

        let (start, end) = self.visible_sample_range(view_min_x, view_max_x);
        for sample in &self.samples[start..end] {
            let ts = sample.timestamp as f64;
            // PARITY: Go calls c.bucketForDataX, re-reading
            // effectiveViewWindow per sample; the window is settled by the
            // fetch above and cannot change mid-loop, so the pure form with
            // identical arithmetic is used (borrow split).
            let bucket = bucket_for_data_x_in_window(ts, layout.plot_width, view_min_x, view_max_x);
            // PARITY: Go iterates sample.values unordered; per-bucket
            // accumulation is order-independent.
            for (series_name, value) in &sample.values {
                let Some(a) = accums.get_mut(series_name) else {
                    continue;
                };
                let b = &mut a[bucket as usize];
                b.sum += value;
                b.count += 1;
                if sample.timestamp > b.timestamp {
                    b.timestamp = sample.timestamp;
                }
            }
        }

        for (series_name, cells) in bucketed.iter_mut() {
            let a = &accums[series_name.as_str()];
            for (i, cell) in cells.iter_mut().enumerate() {
                if a[i].count > 0 {
                    *cell = FrenchFriesBucketCell {
                        timestamp: a[i].timestamp,
                        value: a[i].sum / a[i].count as f64,
                        ok: true,
                    };
                }
            }
        }

        bucketed
    }

    /// Go `colorForValue`: maps a value onto the palette. Returns the styled
    /// "█" cell, or an unstyled space for non-finite values / empty palette.
    fn color_for_value(&self, value: f64) -> Cell {
        if !is_finite(value) || self.colored_cells.is_empty() {
            return Cell::new_with_style(' ', CellStyle::default());
        }

        let mut min_y = self.def.min_y;
        let mut max_y = self.def.max_y;
        if max_y <= min_y {
            min_y = 0.0;
            max_y = 100.0;
        }

        let mut normalized = (value - min_y) / (max_y - min_y);
        // Go builtin max/min (NaN-propagating); go_max/go_min match.
        normalized = go_max(0.0, go_min(1.0, normalized));
        // PARITY: Go int(math.Round(..)); NaN is unreachable here for finite
        // defs — Rust's `as` saturates where Go's cast is
        // platform-dependent.
        let idx = (normalized * (self.colored_cells.len() - 1) as f64).round() as i64;
        let color = self.colored_cells[idx as usize];
        Cell::new_with_style(
            FRENCH_FRIES_CELL,
            CellStyle {
                fg: Some(color.resolve(self.dark_background)),
                bg: None,
                bold: false,
            },
        )
    }

    fn set_default_view_window(&mut self) {
        if self.samples.is_empty() {
            self.view_ready = false;
            return;
        }
        let min_x = self.samples[0].timestamp as f64;
        let mut max_x = self.samples[self.samples.len() - 1].timestamp as f64;
        if max_x <= min_x {
            max_x = min_x + 1.0;
        }
        self.view_min_x = min_x;
        self.view_max_x = max_x;
        self.view_ready = true;
    }

    fn effective_view_window(&mut self) -> (f64, f64) {
        if self.view_ready && self.view_max_x > self.view_min_x {
            return (self.view_min_x, self.view_max_x);
        }
        self.set_default_view_window();
        (self.view_min_x, self.view_max_x)
    }

    fn data_x_for_mouse(&mut self, mouse_x: i64, plot_width: i64) -> f64 {
        let (view_min_x, view_max_x) = self.effective_view_window();
        if plot_width <= 1 || view_max_x <= view_min_x {
            return view_min_x;
        }
        // Map mouse position to the center of the corresponding bucket.
        let bucket_width = (view_max_x - view_min_x) / plot_width as f64;
        // PARITY: Go max/min shape (see update_inspection_at).
        view_min_x + (0.max((plot_width - 1).min(mouse_x)) as f64 + 0.5) * bucket_width
    }

    fn bucket_for_data_x(&mut self, data_x: f64, plot_width: i64) -> i64 {
        let (view_min_x, view_max_x) = self.effective_view_window();
        bucket_for_data_x_in_window(data_x, plot_width, view_min_x, view_max_x)
    }

    fn sorted_series_names(&mut self) -> &[String] {
        if !self.series_dirty {
            return &self.ordered_series;
        }

        let mut names: Vec<String> = self.series.iter().cloned().collect();
        // PARITY: Go sort.Slice(names, systemMetricSeriesLess). That
        // relation is NOT a strict weak ordering: mixing the indexed-prefix
        // rule with the bytewise fallback cycles — less("GPU 10","GPU 5x"),
        // less("GPU 5x","GPU 9") and less("GPU 9","GPU 10") all hold — and
        // the distinct names "GPU 01"/"GPU 1" are mutually !less (same
        // prefix, both parse to index 1). Go sort.Slice silently yields an
        // unspecified order for such input, while Rust's std sorts are
        // documented (since 1.81) to possibly PANIC on comparators that
        // violate total order — and no total order can reproduce Go's
        // pairwise relation (the cycle above has no consistent
        // linearization). Go's sort.Slice delegates to plain insertion sort
        // for slices of length <= 12 (maxInsertion, sort/zsortfunc.go), so
        // the port runs that insertion sort with the same less relation at
        // every length: identical to Go's algorithm for <= 12 series (any
        // realistic count) and panic-free always; for longer pathological
        // inputs the order is unspecified in both implementations.
        insertion_sort_by_less(&mut names, system_metric_series_less);

        self.ordered_series = names;
        self.series_dirty = false;
        &self.ordered_series
    }

    /// PARITY: Go returns nil for no rows — ported as an empty Vec.
    fn visible_series_names(&mut self, max_rows: i64) -> Vec<String> {
        let names = self.sorted_series_names();
        if max_rows <= 0 || names.is_empty() {
            return Vec::new();
        }
        if names.len() as i64 <= max_rows {
            return names.to_vec();
        }
        if max_rows == 1 {
            return names[..1].to_vec();
        }

        let mut visible: Vec<String> = Vec::with_capacity(max_rows as usize);
        visible.extend_from_slice(&names[..(max_rows - 1) as usize]);
        visible.push(names[names.len() - 1].clone());
        visible
    }

    /// Sets which AdaptiveColor variant draw() resolves. See the
    /// `dark_background` field's note and epoch_line_chart.rs
    /// DIVERGENCE(S13).
    pub fn set_dark_background(&mut self, dark: bool) {
        if self.dark_background == dark {
            return;
        }
        self.dark_background = dark;
        self.dirty = true;
    }
}

/// Go `time.Unix(sec, 0)` (frenchfrieschart.go:183). See
/// leveldb_history_source.rs `go_time_unix` for the nsec-carrying form.
fn go_time_unix(sec: i64) -> SystemTime {
    if sec >= 0 {
        UNIX_EPOCH + Duration::from_secs(sec as u64)
    } else {
        UNIX_EPOCH - Duration::from_secs(sec.unsigned_abs())
    }
}

/// Go `selectedLabelStartX` (frenchfrieschart.go:424-433).
fn selected_label_start_x(mouse_x: i64, plot_width: i64, label_width: i64) -> i64 {
    if label_width <= 0 || plot_width <= 0 {
        return 0;
    }
    let mut start = mouse_x + 1;
    if start + label_width > plot_width {
        start = (mouse_x - label_width).max(0);
    }
    // PARITY: Go max(0, min(start, max(plotWidth-labelWidth, 0))) shape.
    0.max(start.min((plot_width - label_width).max(0)))
}

/// Go `bucketTimestamp` (frenchfrieschart.go:534-556); `(int64, bool)` →
/// `Option<i64>`.
fn bucket_timestamp(
    bucketed: &HashMap<String, Vec<FrenchFriesBucketCell>>,
    bucket: i64,
) -> Option<i64> {
    let mut best: i64 = 0;
    let mut ok = false;
    // PARITY: Go iterates the map unordered; max-timestamp selection is
    // order-independent.
    for cells in bucketed.values() {
        if bucket < 0 || bucket >= cells.len() as i64 {
            continue;
        }
        let cell = cells[bucket as usize];
        if !cell.ok {
            continue;
        }
        if !ok || cell.timestamp > best {
            best = cell.timestamp;
            ok = true;
        }
    }
    if ok { Some(best) } else { None }
}

/// The body of Go `bucketForDataX` (frenchfrieschart.go:737-753) after the
/// effectiveViewWindow fetch (see bucketed_series for why it is split out).
fn bucket_for_data_x_in_window(
    data_x: f64,
    plot_width: i64,
    view_min_x: f64,
    view_max_x: f64,
) -> i64 {
    if plot_width <= 1 || view_max_x <= view_min_x {
        return 0;
    }
    if data_x <= view_min_x {
        return 0;
    }
    if data_x >= view_max_x {
        return plot_width - 1;
    }
    // Stable interval-based bucketing: each bucket covers a fixed time
    // width so that small view-window changes don't redistribute samples.
    let bucket_width = (view_max_x - view_min_x) / plot_width as f64;
    let bucket = ((data_x - view_min_x) / bucket_width).floor() as i64;
    // PARITY: Go max/min shape (clamp() panics when hi < lo).
    0.max((plot_width - 1).min(bucket))
}

/// Go `summarizeFrenchFriesSeries` (frenchfrieschart.go:791-811).
fn summarize_french_fries_series(names: &[String], total: i64) -> String {
    if total <= names.len() as i64 {
        return format!("[{total}]");
    }

    let mut labels: Vec<String> = Vec::with_capacity(4);
    if names.len() <= 3 {
        for name in names {
            labels.push(compact_system_metric_series_label(name));
        }
    } else {
        labels.push(compact_system_metric_series_label(&names[0]));
        labels.push(compact_system_metric_series_label(&names[1]));
        labels.push("...".to_string());
        labels.push(compact_system_metric_series_label(&names[names.len() - 1]));
    }

    format!("[{}/{}]", labels.join(","), total)
}

/// Go `compactSystemMetricSeriesLabel` (frenchfrieschart.go:813-826).
///
/// PARITY: strings.Fields (unicode.IsSpace) ↔ split_whitespace
/// (White_Space property) — identical for the ASCII space/tab separators
/// series names contain.
pub(crate) fn compact_system_metric_series_label(name: &str) -> String {
    if name.is_empty() || name == DEFAULT_SYSTEM_METRIC_SERIES_NAME {
        return String::new();
    }
    let fields: Vec<&str> = name.split_whitespace().collect();
    if fields.is_empty() {
        return name.to_string();
    }
    let last = fields[fields.len() - 1];
    // Go strconv.Atoi ↔ i64 parse (optional sign, overflow rejected).
    if last.parse::<i64>().is_ok() {
        return last.to_string();
    }
    name.to_string()
}

/// Go `insertionSort_func` (sort/zsortfunc.go) — the algorithm
/// `sort.Slice` runs for slices of length <= 12. Ported standalone because
/// `system_metric_series_less` is not a total order (see the PARITY note in
/// `sorted_series_names`) and std's sorts may panic on such comparators.
/// Terminates for any relation: `j` strictly decreases per swap.
fn insertion_sort_by_less(names: &mut [String], less: fn(&str, &str) -> bool) {
    // Go: for i := a + 1; i < b; i++ {
    //         for j := i; j > a && data.Less(j, j-1); j-- { data.Swap(j, j-1) }
    //     }
    for i in 1..names.len() {
        let mut j = i;
        while j > 0 && less(&names[j], &names[j - 1]) {
            names.swap(j, j - 1);
            j -= 1;
        }
    }
}

/// Go `systemMetricSeriesLess` (frenchfrieschart.go:828-835).
pub(crate) fn system_metric_series_less(a: &str, b: &str) -> bool {
    let a_split = split_system_metric_series_index(a);
    let b_split = split_system_metric_series_index(b);
    if let (Some((a_prefix, a_index)), Some((b_prefix, b_index))) = (&a_split, &b_split)
        && a_prefix == b_prefix
    {
        return a_index < b_index;
    }
    // Go string < is bytewise; str Ord matches.
    a < b
}

/// Go `splitSystemMetricSeriesIndex` (frenchfrieschart.go:837-848);
/// `(prefix, index, ok)` → `Option<(prefix, index)>`.
fn split_system_metric_series_index(name: &str) -> Option<(String, i64)> {
    let fields: Vec<&str> = name.split_whitespace().collect();
    if fields.len() < 2 {
        return None;
    }

    let index: i64 = fields[fields.len() - 1].parse().ok()?;
    Some((fields[..fields.len() - 1].join(" "), index))
}

// ---------------------------------------------------------------------------
// Tests: transliteration of the seven TestFrenchFriesChart_* cases of
// frenchfrieschart_test.go.
//
// PARITY: DEFERRED TESTS — the three TestSystemMetricsGrid_* cases in that
// file (frenchfrieschart_test.go:149-245) construct a SystemMetricsGrid with
// ConfigManager/NewFocus/NewFilter (leet-tui types), so they cannot compile
// in leet-charts; they port with systemmetricsgrid.go. The leet-tui
// system_metrics_grid unit MUST transliterate all three in addition to
// systemmetricsgrid_test.go's own cases; this debt is tracked in
// docs/PARITY.md §5.2 (do not flip the frenchfrieschart_test.go row to
// `done` until they land):
//   - TestSystemMetricsGrid_CycleFocusedChartMode (y-key mode-cycle order
//     linear→log→heatmap→linear on a heatmap-capable chart)
//   - TestSystemMetricsGrid_GPUUtilizationUsesFrenchFriesChart (gpu.N.gpu
//     metrics auto-create a french-fries-capable chart)
//   - TestSystemMetricsGrid_FrenchFriesUsesConfiguredPalette (ConfigManager
//     FrenchFriesColorScheme plumbing reaches colorForValue)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use leet_data::system_metrics::MetricChartKind;
    use leet_data::units::UNIT_PERCENT;
    use pretty_assertions::assert_eq;

    use crate::styles::Rgb;
    use crate::timeseries_line_chart::go_time_format;

    /// The `&leet.MetricDef{...}` literal shared by the Go cases; omitted
    /// fields keep their Go zero values.
    fn percent_def() -> MetricDef {
        MetricDef {
            name: "GPU Utilization".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            percentage: true,
            auto_range: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        }
    }

    /// Go `time.Unix(1_700_000_000, 0)`.
    fn test_now() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(1_700_000_000)
    }

    /// testhelpers.go `TestVisibleSeries` (not ported as a shipped module;
    /// see docs/PORTING.md Testing conventions).
    fn test_visible_series(chart: &mut FrenchFriesChart) -> Vec<String> {
        let layout = chart.layout();
        layout
            .bands
            .iter()
            .map(|band| band.series_name.clone())
            .collect()
    }

    /// testhelpers.go `TestBucketValues` (missing buckets → NaN).
    fn test_bucket_values(chart: &mut FrenchFriesChart, series_name: &str) -> Vec<f64> {
        let layout = chart.layout();
        let bucketed = chart.bucketed_series(&layout);
        bucketed[series_name]
            .iter()
            .map(|cell| if cell.ok { cell.value } else { f64::NAN })
            .collect()
    }

    /// require.InDelta.
    fn assert_in_delta(want: f64, got: f64, delta: f64, msg: &str) {
        assert!((want - got).abs() <= delta, "{msg}: want {want}, got {got}");
    }

    /// TestFrenchFriesChart_UsesProvidedPalette.
    #[test]
    fn french_fries_chart_uses_provided_palette() {
        let uniform = |c: Rgb| AdaptiveColor { light: c, dark: c };
        let palette = vec![
            uniform(Rgb(0x11, 0x22, 0x33)),
            uniform(Rgb(0x44, 0x55, 0x66)),
            uniform(Rgb(0x77, 0x88, 0x99)),
        ];

        let chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 8,
            height: 2,
            def: &percent_def(),
            colors: &palette,
            now: test_now(),
        });

        // Go: lipgloss.NewStyle().Foreground(palette[i]).Render("█") vs
        // TestColorForValue — the port compares styled cells.
        let dark = default_dark_background();
        let styled = |color: AdaptiveColor| {
            Cell::new_with_style(
                FRENCH_FRIES_CELL,
                CellStyle {
                    fg: Some(color.resolve(dark)),
                    bg: None,
                    bold: false,
                },
            )
        };
        let low = styled(palette[0]);
        let high = styled(palette[palette.len() - 1]);
        assert_eq!(chart.color_for_value(0.0), low);
        assert_eq!(chart.color_for_value(100.0), high);
    }

    /// TestFrenchFriesChart_AlignsMetricsByTimestamp.
    #[test]
    fn french_fries_chart_aligns_metrics_by_timestamp() {
        let def = percent_def();

        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 8,
            height: 2,
            def: &def,
            colors: &[],
            now: test_now(),
        });

        chart.add_data_point("GPU 0", 100, 10.0);
        chart.add_data_point("GPU 1", 100, 90.0);
        chart.add_data_point("GPU 0", 101, 20.0);
        chart.add_data_point("GPU 1", 101, 80.0);

        // "same-timestamp samples should share a column"
        assert_eq!(chart.samples.len(), 2);
    }

    /// TestFrenchFriesChart_RetainsHistoryBeyondVisibleWidth.
    #[test]
    fn french_fries_chart_retains_history_beyond_visible_width() {
        let def = percent_def();

        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 4,
            height: 3,
            def: &def,
            colors: &[],
            now: test_now(),
        });

        for i in 0..10 {
            chart.add_data_point("GPU 0", 100 + i, (i * 10) as f64);
        }

        assert_eq!(chart.samples.len(), 10);
    }

    /// TestFrenchFriesChart_TruncatedRowsExposeVisibleSeriesInTitle.
    #[test]
    fn french_fries_chart_truncated_rows_expose_visible_series_in_title() {
        let def = percent_def();

        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 12,
            height: 3,
            def: &def,
            colors: &[],
            now: test_now(),
        });

        for gpu in 0..8 {
            chart.add_data_point(&format!("GPU {gpu}"), 100, (gpu * 10) as f64);
        }

        assert_eq!(
            test_visible_series(&mut chart),
            vec!["GPU 0".to_string(), "GPU 7".to_string()]
        );
        assert_eq!(chart.title_detail(), "[0,7/8]");
    }

    /// TestFrenchFriesChart_InspectionShowsValuesForWholeColumn.
    #[test]
    fn french_fries_chart_inspection_shows_values_for_whole_column() {
        let def = percent_def();

        let start: i64 = 1_700_000_000;
        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 32,
            height: 4,
            def: &def,
            colors: &[],
            now: test_now(),
        });

        let ts = start;
        chart.add_data_point("GPU 0", ts, 10.0);
        chart.add_data_point("GPU 1", ts, 50.0);
        chart.add_data_point("GPU 7", ts, 90.0);
        chart.set_view_window((ts - 1) as f64, (ts + 1) as f64);
        chart.inspect_at_data_x(ts as f64);

        // Go: stripANSI(chart.View()) — text_rows is the style-stripped
        // equivalent.
        let lines = chart.view().text_rows();
        assert_eq!(lines.len(), 4);
        assert!(lines.join("\n").contains('│'));
        assert!(lines[0].contains("0: 10%"), "line 0: {:?}", lines[0]);
        assert!(lines[1].contains("1: 50%"), "line 1: {:?}", lines[1]);
        assert!(lines[2].contains("7: 90%"), "line 2: {:?}", lines[2]);
        // Go: start.Local().Format("15:04") — the port renders UTC (module
        // doc DIVERGENCE), so the expectation goes through the same
        // formatter.
        assert!(
            lines[3].contains(&go_time_format(&time_unix_utc(start), "15:04")),
            "line 3: {:?}",
            lines[3]
        );
    }

    /// TestFrenchFriesChart_StableBuckets_AddingDataDoesNotShiftExisting.
    #[test]
    fn french_fries_chart_stable_buckets_adding_data_does_not_shift_existing() {
        // no label → plotWidth == width
        let series = DEFAULT_SYSTEM_METRIC_SERIES_NAME;

        let def = percent_def();

        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 10,
            height: 2,
            def: &def,
            colors: &[],
            now: test_now(),
        });

        // Fix the view window so it doesn't auto-adjust when we add data.
        // 10 buckets over [0, 100): each bucket covers 10 seconds.
        chart.set_view_window(0.0, 100.0);

        // Seed 10 samples, one per bucket.
        for i in 0..10 {
            chart.add_data_point(series, i * 10, (i * 10) as f64);
        }
        let before = test_bucket_values(&mut chart, series);

        // Add a new sample inside bucket 5 ([50, 60)).
        chart.add_data_point(series, 55, 42.0);
        let after = test_bucket_values(&mut chart, series);

        assert_eq!(before.len(), after.len());
        for i in 0..before.len() {
            if i == 5 {
                // Bucket 5 now averages the original sample (50) with the
                // new one (42), so its value is expected to change.
                continue;
            }
            assert_in_delta(
                before[i],
                after[i],
                0.001,
                &format!("bucket {i} should not change when data is added to bucket 5"),
            );
        }
    }

    /// TestFrenchFriesChart_StableBuckets_AveragesWithinBucket.
    #[test]
    fn french_fries_chart_stable_buckets_averages_within_bucket() {
        let series = DEFAULT_SYSTEM_METRIC_SERIES_NAME;

        let def = percent_def();

        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 4,
            height: 2,
            def: &def,
            colors: &[],
            now: test_now(),
        });

        // 4-column chart with view window [0, 40): each bucket covers 10
        // seconds.
        chart.set_view_window(0.0, 40.0);

        // Put three samples in bucket 0 ([0, 10)).
        chart.add_data_point(series, 1, 20.0);
        chart.add_data_point(series, 3, 40.0);
        chart.add_data_point(series, 7, 60.0);

        let vals = test_bucket_values(&mut chart, series);
        assert_in_delta(
            40.0,
            vals[0],
            0.001,
            "bucket 0 should be average of 20,40,60",
        );
    }

    /// Port-only regression (no Go counterpart): systemMetricSeriesLess is
    /// not a strict weak ordering, so a std sort could panic on it — the
    /// port must sort like Go's sort.Slice instead (unspecified order, no
    /// panic; see the PARITY note in sorted_series_names).
    #[test]
    fn french_fries_chart_sorted_series_names_tolerates_comparator_cycle() {
        // The relation cycles across the indexed/bytewise boundary...
        assert!(system_metric_series_less("GPU 10", "GPU 5x"));
        assert!(system_metric_series_less("GPU 5x", "GPU 9"));
        assert!(system_metric_series_less("GPU 9", "GPU 10"));
        // ...and distinct names can be mutually !less.
        assert!(!system_metric_series_less("GPU 01", "GPU 1"));
        assert!(!system_metric_series_less("GPU 1", "GPU 01"));

        let mut chart = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 12,
            height: 3,
            def: &percent_def(),
            colors: &[],
            now: test_now(),
        });

        // Well-behaved input (one shared indexed prefix) sorts numerically,
        // including past Go's maxInsertion=12 threshold where bytewise order
        // ("GPU 10" < "GPU 2") would differ.
        for gpu in [3, 14, 0, 7, 11, 2, 9, 1, 13, 5, 15, 4, 10, 8, 12, 6] {
            chart.add_data_point(&format!("GPU {gpu}"), 100, 1.0);
        }
        let want: Vec<String> = (0..16).map(|i| format!("GPU {i}")).collect();
        assert_eq!(chart.sorted_series_names().to_vec(), want);

        // Adversarial input containing the cycle must not panic and must
        // keep every series; the resulting order is unspecified (as Go's).
        chart.add_data_point("GPU 5x", 100, 1.0);
        let mut got = chart.sorted_series_names().to_vec();
        assert_eq!(got.len(), 17);
        got.sort();
        let mut want_all = want;
        want_all.push("GPU 5x".to_string());
        want_all.sort();
        assert_eq!(got, want_all);
    }
}
