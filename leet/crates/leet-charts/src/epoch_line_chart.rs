//! Port of `core/internal/leet/epochlinechart.go`: the multi-series braille
//! line chart for epoch/step-based ML training data.
//!
//! Multiple series render with opaque compositing (painter's algorithm):
//! the last series in draw order appears on top
//! (`draw_braille_patterns_occluded` REPLACES cells, unlike ntcharts'
//! merging `DrawBraillePatterns`).
//!
//! Notable ports of Go structure:
//! - Go embeds `linechart.Model`; the port embeds [`crate::braille::LineChart`]
//!   via a `model` field plus `Deref`/`DerefMut` so promoted methods
//!   (`ViewMinX`, `GraphWidth`, …) keep their call shape. `Series` likewise
//!   embeds `MetricData`.
//! - `Series.style` was an `atomic.Value` in Go so Draw could run
//!   concurrently with style updates (CONCURRENCY.md S12); draw runs on the
//!   update thread in the port, so it dies into a plain field
//!   (CONCURRENCY.md §2.6).
//! - Go's `XLabelFormatter`/`YLabelFormatter` are closures over the chart
//!   pointer, reading `maxXLabelWidth()`/`formatYTick` live. A Rust closure
//!   cannot borrow the chart it is stored in, so the equivalent state is
//!   re-captured at every point it can change (see
//!   [`EpochLineChart::install_y_label_formatter`] and [`EpochLineChart::draw`]).
//!   Derived charts (timeserieslinechart.go) that install their own
//!   chart-pointer closures use two hooks instead: the draw-time
//!   [`XLabelFormatterFactory`] and the receiver-passing
//!   [`InspectionLabelFormatter`].
//! - `colorIndex` (epochlinechart.go:51) is hosted in
//!   [`crate::styles::color_index`] (DIVERGENCE(hosting) recorded there);
//!   this module reuses it.
//! - lipgloss adaptive foregrounds resolve at render time through Go's
//!   `darkBackground` global (S13). The port keeps no global (styles.rs
//!   module doc): the chart carries a `dark_background` flag that leet-tui
//!   updates on `tea.BackgroundColorMsg`.

use std::collections::HashMap;
use std::ops::{Deref, DerefMut};
use std::rc::Rc;

use leet_data::config::DEFAULT_COLOR_SCHEME;
use leet_data::go_fmt;
use leet_data::units::{UNIT_SCALAR, format_x_axis_tick};
use leet_data::width::text_width;

use crate::braille::{
    BRAILLE_BLOCK_OFFSET, BrailleGrid, LabelFormatter, LineChart, NULL, is_braille_pattern,
};
use crate::canvas::{Canvas, Cell, CellStyle, Float64Point, Point};
use crate::styles::{
    AdaptiveColor, BOX_LIGHT_VERTICAL, COLOR_SUBTLE, COLOR_TEXT, INSPECTION_LEGEND_BG,
    INSPECTION_LEGEND_FG, color_index, default_dark_background, graph_colors,
};

/// Go: `messages.go` MetricData (re-exported so chart call sites mirror the
/// flat Go package).
pub use leet_data::history_source::MetricData;

const DEFAULT_ZOOM_FACTOR: f64 = 0.10;
// pub(crate): also read by the timeserieslinechart.go port (Go: same package).
pub(crate) const MIN_ZOOM_RANGE: f64 = 5.0;
const TAIL_ANCHOR_MOUSE_THRESHOLD: f64 = 0.95;
const DEFAULT_MAX_X: f64 = 20.0;
const DEFAULT_MAX_Y: f64 = 1.0;

/// Minimal canvas size for parked charts.
// pub(crate): Go declares parkedCanvasSize in epochlinechart.go:27 and
// frenchfrieschart.go Park() reads it cross-file within the package.
pub(crate) const PARKED_CANVAS_SIZE: i64 = 1;

const INIT_DATA_SLICE_CAP: usize = 256;
const MIN_LOG_SCALE_MARGIN: f64 = 0.1;

/// AxisScaleMode controls how Y values are projected for rendering.
///
/// Go: `AxisScaleLinear` / `AxisScaleLog`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum AxisScaleMode {
    #[default]
    Linear,
    Log,
}

impl std::fmt::Display for AxisScaleMode {
    /// Go `AxisScaleMode.String()` (epochlinechart.go:41-48; the Go default
    /// branch maps everything that is not Log to "linear").
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AxisScaleMode::Log => write!(f, "log"),
            AxisScaleMode::Linear => write!(f, "linear"),
        }
    }
}

// ---------------------------------------------------------------------------
// Go builtin float64 min/max.
// ---------------------------------------------------------------------------

/// Go builtin `min` for float64 (epochlinechart.go uses the builtins, not
/// `math.Min`): NaN if either operand is NaN, and -0.0 orders below +0.0.
/// Distinct from [`crate::braille::math_min`] (math.Min lets -Inf beat NaN),
/// and from `f64::min` (which IGNORES NaN).
pub(crate) fn go_min(x: f64, y: f64) -> f64 {
    if x.is_nan() || y.is_nan() {
        return f64::NAN;
    }
    if x == 0.0 && y == 0.0 {
        return if x.is_sign_negative() { x } else { y };
    }
    if x < y { x } else { y }
}

/// Go builtin `max` for float64. See [`go_min`].
pub(crate) fn go_max(x: f64, y: f64) -> f64 {
    if x.is_nan() || y.is_nan() {
        return f64::NAN;
    }
    if x == 0.0 && y == 0.0 {
        return if x.is_sign_negative() { y } else { x };
    }
    if x > y { x } else { y }
}

// ---------------------------------------------------------------------------
// lipgloss.Style stand-ins (chart-internal styles.go objects).
// ---------------------------------------------------------------------------

/// The `lipgloss.Style` subset leet applies to a chart series: an adaptive
/// foreground color. Every Go call site builds
/// `lipgloss.NewStyle().Foreground(color)` (metricsgrid.go:199,306;
/// timeserieslinechart.go:116; epochlinechart.go:103).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SeriesStyle {
    pub fg: AdaptiveColor,
}

impl SeriesStyle {
    /// Resolve to a concrete canvas cell style (Go: lipgloss resolves the
    /// adaptive foreground at render time via the `darkBackground` global).
    pub fn cell_style(self, dark: bool) -> CellStyle {
        CellStyle {
            fg: Some(self.fg.resolve(dark)),
            bg: None,
            bold: false,
        }
    }
}

/// styles.go:552 `axisStyle`: foreground colorSubtle.
pub(crate) fn axis_style(dark: bool) -> CellStyle {
    CellStyle {
        fg: Some(COLOR_SUBTLE.resolve(dark)),
        bg: None,
        bold: false,
    }
}

/// styles.go:554 `labelStyle`: foreground colorText.
pub(crate) fn label_style(dark: bool) -> CellStyle {
    CellStyle {
        fg: Some(COLOR_TEXT.resolve(dark)),
        bg: None,
        bold: false,
    }
}

/// styles.go:556 `inspectionLineStyle`: foreground colorSubtle.
pub(crate) fn inspection_line_style(dark: bool) -> CellStyle {
    CellStyle {
        fg: Some(COLOR_SUBTLE.resolve(dark)),
        bg: None,
        bold: false,
    }
}

/// styles.go:558-566 `inspectionLegendStyle`: adaptive foreground
/// #111111/#EEEEEE over adaptive background #EEEEEE/#333333.
pub(crate) fn inspection_legend_style(dark: bool) -> CellStyle {
    CellStyle {
        fg: Some(INSPECTION_LEGEND_FG.resolve(dark)),
        bg: Some(INSPECTION_LEGEND_BG.resolve(dark)),
        bold: false,
    }
}

/// Go: `func(seriesKey string, x, y float64) string`
/// (inspectionLabelFormatter). Go installs a bound method that reads chart
/// state live through its receiver (timeserieslinechart.go:85); the stored
/// closure cannot borrow the chart it lives in, so the chart is passed back
/// in explicitly at each call.
pub type InspectionLabelFormatter = Box<dyn Fn(&EpochLineChart, &str, f64, f64) -> String>;

/// Borrowed form of [`InspectionLabelFormatter`].
type InspectionLabelFormatterRef<'a> = &'a dyn Fn(&EpochLineChart, &str, f64, f64) -> String;

/// Go: timeserieslinechart.go:82-84 overwrites the linechart model's
/// `XLabelFormatter` with a closure over the chart pointer, reading
/// view/geometry state live. The port's [`EpochLineChart::draw`] invokes
/// this factory — with the geometry fixed — to produce the per-draw
/// formatter; `None` keeps epoch's numeric formatter.
pub type XLabelFormatterFactory = Box<dyn Fn(&EpochLineChart) -> LabelFormatter>;

/// Go: `func(float64) string` (yTickFormatter). `Rc` because the chart field
/// and the closure installed into the linechart model share it (Go's closure
/// reads the field through the chart pointer).
pub type YTickFormatter = Rc<dyn Fn(f64) -> String>;

// ---------------------------------------------------------------------------
// Series.
// ---------------------------------------------------------------------------

/// Series stores the raw samples in arrival order.
///
/// Series is not safe for concurrent use. Callers must synchronize access
/// externally (e.g., via the owning EpochLineChart or grid-level locks).
#[derive(Debug, Clone)]
pub struct Series {
    /// X and Y hold the raw data points. X is typically `_step` (monotonic,
    /// non-decreasing), enabling efficient binary search during rendering.
    /// (Go embeds MetricData; `Deref` promotes `.x`/`.y`.)
    pub metric_data: MetricData,

    /// style is the foreground style used to render the series line/dots.
    // PARITY: Go stores this in an atomic.Value because Draw may run
    // concurrently with style updates (CONCURRENCY.md S12); draw is
    // main-thread in the port, so the atomic dies into a plain field
    // (CONCURRENCY.md §2.6).
    pub(crate) style: SeriesStyle,

    // Precomputed bounds for O(1) chart-level aggregation.
    // Updated incrementally by update_bounds.
    x_min: f64,
    x_max: f64,
    y_min: f64,
    y_max: f64,
    y_min_positive: f64,
}

impl Deref for Series {
    type Target = MetricData;

    fn deref(&self) -> &MetricData {
        &self.metric_data
    }
}

impl DerefMut for Series {
    fn deref_mut(&mut self) -> &mut MetricData {
        &mut self.metric_data
    }
}

impl Series {
    /// Go `NewSeries`.
    pub fn new(name: &str, palette: &[AdaptiveColor]) -> Series {
        let md = MetricData {
            x: Vec::with_capacity(INIT_DATA_SLICE_CAP),
            y: Vec::with_capacity(INIT_DATA_SLICE_CAP),
        };

        let palette = if palette.is_empty() {
            graph_colors(DEFAULT_COLOR_SCHEME)
        } else {
            palette
        };
        // Stable mapping for consistent colors across sessions.
        let i = color_index(name, palette.len());

        Series {
            metric_data: md,
            style: SeriesStyle { fg: palette[i] },
            x_min: f64::INFINITY,
            x_max: f64::NEG_INFINITY,
            y_min: f64::INFINITY,
            y_max: f64::NEG_INFINITY,
            y_min_positive: f64::INFINITY,
        }
    }

    /// updateBounds extends the series bounds with the given data batch.
    ///
    /// Non-finite samples (NaN/Inf, e.g. a diverged loss) are excluded so
    /// they cannot poison the bounds; they still render as gaps in the
    /// series line.
    fn update_bounds(&mut self, xs: &[f64], ys: &[f64]) {
        for &x in xs {
            if !is_finite(x) {
                continue;
            }
            self.x_min = go_min(self.x_min, x);
            self.x_max = go_max(self.x_max, x);
        }

        for &y in ys {
            if !is_finite(y) {
                continue;
            }
            self.y_min = go_min(self.y_min, y);
            self.y_max = go_max(self.y_max, y);
            if y > 0.0 {
                self.y_min_positive = go_min(self.y_min_positive, y);
            }
        }
    }

    /// Bounds returns the series' precomputed bounds.
    pub fn bounds(&self) -> (f64, f64, f64, f64) {
        (self.x_min, self.x_max, self.y_min, self.y_max)
    }

    /// AddPoint appends a single sample and incrementally updates bounds.
    pub fn add_point(&mut self, x: f64, y: f64) {
        self.metric_data.x.push(x);
        self.metric_data.y.push(y);
        if is_finite(x) {
            self.x_min = go_min(self.x_min, x);
            self.x_max = go_max(self.x_max, x);
        }
        if is_finite(y) {
            self.y_min = go_min(self.y_min, y);
            self.y_max = go_max(self.y_max, y);
            if y > 0.0 {
                self.y_min_positive = go_min(self.y_min_positive, y);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// EpochLineChart.
// ---------------------------------------------------------------------------

/// EpochLineChart is a line chart for epoch/step-based ML training data.
///
/// It supports multiple series rendered with opaque compositing (painter's
/// algorithm), where the last series in draw order appears on top.
///
/// Go's concurrency note (Draw racing SetGraphStyle/SetPalette via
/// atomic.Value styles) does not apply: everything runs on the update thread
/// (CONCURRENCY.md §2.6).
pub struct EpochLineChart {
    /// The embedded ntcharts line chart backend providing canvas, axes,
    /// coordinate transforms, and range management (Go embeds
    /// `linechart.Model`; `Deref` promotes its methods).
    pub(crate) model: LineChart,

    /// data maps series keys to their data.
    pub(crate) data: HashMap<String, Series>,

    /// order defines the draw order: series are rendered in slice order,
    /// so the last element appears visually on top.
    pub(crate) order: Vec<String>,

    /// palette provides colors for new series added to this chart.
    // pub(crate): the timeserieslinechart.go port's addPoint constructs
    // Series with it (Go: same package).
    pub(crate) palette: Vec<AdaptiveColor>,

    /// focused indicates whether this chart has input focus in the grid.
    // PARITY: write-only in Go too (nothing in the package reads it back).
    #[allow(dead_code)]
    focused: bool,

    /// title is the metric name shown in the chart header.
    title: String,

    /// dirty marks the chart as needing a redraw on the next
    /// draw_if_needed call.
    pub(crate) dirty: bool,

    /// is_zoomed is set after user adjusts the X view via handle_zoom.
    /// When true, update_ranges preserves the user's X view instead of
    /// auto-fitting.
    pub(crate) is_zoomed: bool,

    /// user_view_min_x/user_view_max_x preserve the user's zoom selection
    /// across data updates when is_zoomed is true.
    // Read/written by the timeserieslinechart.go port
    // (timeserieslinechart.go:301,374-375,451-452).
    pub(crate) user_view_min_x: f64,
    pub(crate) user_view_max_x: f64,

    /// x_min/x_max are the observed X bounds across all series.
    /// Used for axis domain and zoom clamping.
    // pub(crate): the timeserieslinechart.go port extends the bounds in
    // addPoint and reads them in applyRanges (Go: same package).
    pub(crate) x_min: f64,
    pub(crate) x_max: f64,

    /// y_min/y_max are the observed Y bounds across all series.
    /// Used to compute padded Y axis ranges.
    pub(crate) y_min: f64,
    pub(crate) y_max: f64,

    /// y_scale controls how Y values are projected for rendering.
    // NOTE: assigning directly (as timeserieslinechart.go:150 does) requires
    // calling install_y_label_formatter() afterwards — Go's label closure
    // read the field live; the port captures it. See set_y_scale.
    pub(crate) y_scale: AxisScaleMode,

    /// y_tick_formatter formats raw, unscaled Y values for axis labels.
    pub(crate) y_tick_formatter: Option<YTickFormatter>,

    /// inspection holds crosshair overlay state for data inspection mode.
    pub(crate) inspection: ChartInspection,

    /// inspection_label_formatter customizes legend labels for inspection
    /// mode. When None, a default numeric formatter is used.
    inspection_label_formatter: Option<InspectionLabelFormatter>,

    /// See [`XLabelFormatterFactory`]. Installed by the
    /// timeserieslinechart.go port's constructor (Go assigns the model's
    /// XLabelFormatter directly).
    pub(crate) x_label_formatter_factory: Option<XLabelFormatterFactory>,

    /// Which AdaptiveColor variant draw() resolves.
    // DIVERGENCE(S13): Go reads the package-global darkBackground atomic at
    // render time (styles.go:17-31); the port keeps no global — leet-tui
    // owns the flag (styles.rs module doc) and pushes it here on
    // tea.BackgroundColorMsg via set_dark_background.
    dark_background: bool,
}

impl Deref for EpochLineChart {
    type Target = LineChart;

    fn deref(&self) -> &LineChart {
        &self.model
    }
}

impl DerefMut for EpochLineChart {
    fn deref_mut(&mut self) -> &mut LineChart {
        &mut self.model
    }
}

/// formatYTick's body (epochlinechart.go:247-264), shared by the chart
/// method and the closure installed into the linechart model.
fn format_y_tick_impl(log_y: bool, fmtr: Option<&dyn Fn(f64) -> String>, v: f64) -> String {
    if !is_finite(v) {
        return String::new();
    }

    let mut raw_value = v;
    if log_y {
        // PARITY: Go math.Pow(10, v); powf may differ in the last ulp,
        // absorbed by the 3-sig-fig formatting.
        raw_value = 10f64.powf(v);
        if !is_finite(raw_value) {
            return String::new();
        }
    }

    if let Some(f) = fmtr {
        return f(raw_value);
    }
    UNIT_SCALAR.format(raw_value)
}

impl EpochLineChart {
    /// Go `NewEpochLineChart`.
    pub fn new(title: &str) -> EpochLineChart {
        let dark = default_dark_background();
        let mut model = LineChart::new(
            PARKED_CANVAS_SIZE,
            PARKED_CANVAS_SIZE,
            0.0,
            DEFAULT_MAX_X,
            0.0,
            DEFAULT_MAX_Y,
        )
        .with_xy_steps(4, 5) // The default number of ticks when drawing axis values.
        .with_auto_x_range();
        model.axis_style = axis_style(dark);
        model.label_style = label_style(dark);

        let mut chart = EpochLineChart {
            model,
            data: HashMap::new(),
            order: Vec::new(),
            title: title.to_string(),
            palette: graph_colors(DEFAULT_COLOR_SCHEME).to_vec(),
            focused: false,
            dirty: false,
            is_zoomed: false,
            user_view_min_x: 0.0,
            user_view_max_x: 0.0,
            x_min: f64::INFINITY,
            x_max: f64::NEG_INFINITY,
            y_min: f64::INFINITY,
            y_max: f64::NEG_INFINITY,
            y_scale: AxisScaleMode::Linear,
            y_tick_formatter: Some(Rc::new(|v| UNIT_SCALAR.format(v))),
            inspection: ChartInspection::default(),
            inspection_label_formatter: None,
            x_label_formatter_factory: None,
            dark_background: dark,
        };

        // Go installs XLabelFormatter/YLabelFormatter closures over the
        // chart pointer here. The X formatter is (re)bound in draw() (its
        // only call site); the Y formatter is captured now and re-captured
        // whenever its inputs change.
        chart.install_y_label_formatter();

        chart
    }

    /// (Re)installs the linechart model's Y label formatter, capturing the
    /// state Go's `chart.formatYTick` closure read live: the log flag and
    /// the tick formatter. Must be called after either changes.
    pub(crate) fn install_y_label_formatter(&mut self) {
        let log_y = self.is_log_y();
        let fmtr = self.y_tick_formatter.clone();
        self.model.y_label_formatter =
            Box::new(move |_i, v| format_y_tick_impl(log_y, fmtr.as_deref(), v));
    }

    /// Go `formatYTick`.
    // Parity surface: axis labels go through the closure installed by
    // install_y_label_formatter (as in Go); outside tests nothing calls the
    // method form directly.
    #[allow(dead_code)]
    fn format_y_tick(&self, v: f64) -> String {
        format_y_tick_impl(self.is_log_y(), self.y_tick_formatter.as_deref(), v)
    }

    /// YScale reports the active Y-axis scaling mode.
    pub fn y_scale(&self) -> AxisScaleMode {
        self.y_scale
    }

    /// IsLogY reports whether the chart is using logarithmic Y scaling.
    pub fn is_log_y(&self) -> bool {
        self.y_scale == AxisScaleMode::Log
    }

    /// ScaleLabel returns a compact label for the active Y-axis scale.
    pub fn scale_label(&self) -> &'static str {
        if self.is_log_y() {
            return "log y";
        }
        ""
    }

    /// CanUseLogY reports whether the chart has at least one strictly
    /// positive sample.
    pub fn can_use_log_y(&self) -> bool {
        self.positive_y_bounds().is_some()
    }

    /// SetYScale switches the Y-axis scaling mode.
    ///
    /// Log scaling requires at least one strictly positive value. When the
    /// requested mode is already active, set_y_scale is a no-op and reports
    /// false.
    pub fn set_y_scale(&mut self, mode: AxisScaleMode) -> bool {
        if mode == AxisScaleMode::Log && !self.can_use_log_y() {
            return false;
        }
        if self.y_scale == mode {
            return false;
        }

        self.y_scale = mode;
        self.install_y_label_formatter();
        self.update_ranges();
        self.dirty = true;
        true
    }

    /// ToggleYScale toggles between linear and logarithmic Y scaling.
    pub fn toggle_y_scale(&mut self) -> bool {
        if self.is_log_y() {
            return self.set_y_scale(AxisScaleMode::Linear);
        }
        self.set_y_scale(AxisScaleMode::Log)
    }

    /// topSeries returns the topmost series (last in draw order), or None if
    /// empty. The topmost series is used for inspection snapping and data
    /// point queries.
    fn top_series(&self) -> Option<&Series> {
        if self.order.is_empty() {
            return None;
        }
        // PARITY: Go's map lookup yields nil for a missing key; data and
        // order are kept in sync so it is always present.
        self.data.get(&self.order[self.order.len() - 1])
    }

    /// maxXLabelWidth computes maximum X axis label width based on available
    /// space.
    // pub(crate): the timeserieslinechart.go port's X label closure reads it
    // (timeserieslinechart.go:83).
    pub(crate) fn max_x_label_width(&self) -> i64 {
        let w = self.model.graph_width();
        if w <= 0 {
            return 0;
        }

        // Approx spacing between ticks. With XSteps=N there are typically N
        // intervals.
        let mut per = w / self.model.x_step();
        if per > 1 {
            per -= 1; // leave one column slack so labels collide less often
        }
        if per < 1 {
            return 1;
        }
        per
    }

    /// SetPalette updates the color palette for new series.
    /// Existing series retain their current colors.
    pub fn set_palette(&mut self, colors: &[AdaptiveColor]) {
        let colors = if colors.is_empty() {
            graph_colors(DEFAULT_COLOR_SCHEME)
        } else {
            colors
        };
        self.palette = colors.to_vec();
    }

    /// AddData appends (x, y) points to the named series, creating it if
    /// needed.
    ///
    /// X values should be appended in non-decreasing order for efficient
    /// rendering. Empty data is a no-op.
    pub fn add_data(&mut self, key: &str, data: MetricData) {
        if !self.data.contains_key(key) {
            self.data
                .insert(key.to_string(), Series::new(key, &self.palette));
            self.order.push(key.to_string());
        }

        // Safety checks.
        if data.x.len() != data.y.len() {
            return;
        }
        if data.x.is_empty() || data.y.is_empty() {
            return;
        }

        let s = self.data.get_mut(key).expect("series was just ensured");

        // Amortized linear growth. Do not use slices.Concat as it causes
        // O(n^2) allocations that blow up memory footprint. (Go comment;
        // extend_from_slice is the append equivalent.)
        s.metric_data.x.extend_from_slice(&data.x);
        s.metric_data.y.extend_from_slice(&data.y);

        // Update series-level bounds and extend chart-level bounds.
        s.update_bounds(&data.x, &data.y);
        let (sx_min, sx_max, sy_min, sy_max) = s.bounds();
        self.x_min = go_min(self.x_min, sx_min);
        self.x_max = go_max(self.x_max, sx_max);
        self.y_min = go_min(self.y_min, sy_min);
        self.y_max = go_max(self.y_max, sy_max);

        self.update_ranges();
        self.dirty = true;
    }

    /// updateRanges recomputes axis ranges from current bounds.
    fn update_ranges(&mut self) {
        if self.series_count() == 0 {
            return;
        }

        let Some((new_y_min, new_y_max)) = self.compute_y_range() else {
            return;
        };

        // X domain: round up to a "nice" value for axis display.
        let data_x_min = self.x_min;
        let mut data_x_max = self.x_max;
        if !is_finite(data_x_max) {
            data_x_max = 0.0;
        }
        let mut nice_max = data_x_max;
        if nice_max < DEFAULT_MAX_X {
            // Keep a decent default domain early in a run.
            nice_max = DEFAULT_MAX_X;
        } else {
            // Round to nearest 10.
            nice_max = ((nice_max.ceil() as i64 + 9) / 10 * 10) as f64;
        }

        self.model.set_y_range(new_y_min, new_y_max);
        self.model.set_view_y_range(new_y_min, new_y_max);

        // Always ensure X range covers the nice domain; only alter view if
        // not zoomed.
        self.model.set_x_range(data_x_min, nice_max);
        if !self.is_zoomed {
            let mut view_min = self.x_min;
            if !is_finite(view_min) {
                view_min = 0.0;
            }
            self.model.set_view_x_range(view_min, nice_max);
        }

        self.model
            .set_xy_range(self.model.min_x(), self.model.max_x(), new_y_min, new_y_max);

        // Keep inspection overlay consistent if the view/domain changed.
        if self.inspection.active {
            self.refresh_inspection_after_view_change();
        }
    }

    /// Go `computeYRange` (returns `(minY, maxY, ok)`).
    fn compute_y_range(&self) -> Option<(f64, f64)> {
        if self.is_log_y() {
            let (min_positive, max_positive) = self.positive_y_bounds()?;
            return Some(self.calculate_log_range(min_positive, max_positive));
        }

        // No finite samples yet (e.g. only NaN/Inf values logged so far).
        if !is_finite(self.y_min) || !is_finite(self.y_max) {
            return None;
        }

        Some(self.calculate_linear_range())
    }

    fn calculate_linear_range(&self) -> (f64, f64) {
        let value_range = self.y_max - self.y_min;
        let padding = self.calculate_padding(value_range);

        let mut new_y_min = self.y_min - padding;
        let new_y_max = self.y_max + padding;

        // Don't go negative for non-negative data.
        if self.y_min >= 0.0 && new_y_min < 0.0 {
            new_y_min = 0.0;
        }

        (new_y_min, new_y_max)
    }

    // pub(crate): called by the timeserieslinechart.go port's
    // computeLogYRange (Go: same package).
    pub(crate) fn calculate_log_range(&self, min_positive: f64, max_positive: f64) -> (f64, f64) {
        // PARITY: Go math.Log10; f64::log10 may differ in the last ulp,
        // absorbed by padding and label formatting.
        let min_log = min_positive.log10();
        let max_log = max_positive.log10();
        let mut padding = (max_log - min_log) * 0.1;
        if padding < MIN_LOG_SCALE_MARGIN {
            padding = MIN_LOG_SCALE_MARGIN;
        }
        (min_log - padding, max_log + padding)
    }

    /// Go `positiveYBounds` (returns `(minPositive, maxPositive, ok)`).
    pub(crate) fn positive_y_bounds(&self) -> Option<(f64, f64)> {
        let mut min_positive = f64::INFINITY;
        let mut max_positive = f64::NEG_INFINITY;

        // PARITY: Go iterates the map unordered; min/max aggregation is
        // order-independent. The Go nil-series guard is unrepresentable.
        for series in self.data.values() {
            if series.y.is_empty() || series.y_max <= 0.0 || !is_finite(series.y_min_positive) {
                continue;
            }
            min_positive = go_min(min_positive, series.y_min_positive);
            max_positive = go_max(max_positive, series.y_max);
        }

        if !is_finite(min_positive) || !is_finite(max_positive) || max_positive <= 0.0 {
            return None;
        }
        Some((min_positive, max_positive))
    }

    /// calculatePadding determines appropriate padding for the Y axis.
    fn calculate_padding(&self, value_range: f64) -> f64 {
        if value_range == 0.0 {
            let abs_value = self.y_max.abs();
            return if abs_value < 0.001 {
                0.0001
            } else if abs_value < 0.1 {
                abs_value * 0.1
            } else {
                0.1
            };
        }

        let mut padding = value_range * 0.1;
        if padding < 1e-6 {
            padding = 1e-6;
        }
        padding
    }

    /// HandleZoom processes zoom events with the mouse X position in pixels.
    ///
    /// PARITY: `direction` keeps Go's string protocol ("in" zooms in,
    /// anything else zooms out).
    pub fn handle_zoom(&mut self, direction: &str, mouse_x: i64) {
        let view_min = self.model.view_min_x();
        let view_max = self.model.view_max_x();
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            return;
        }

        let mut mouse_proportion = mouse_x as f64 / self.model.graph_width() as f64;
        mouse_proportion = go_max(0.0, go_min(1.0, mouse_proportion));
        let step_under_mouse = view_min + mouse_proportion * view_range;

        let mut new_range = if direction == "in" {
            view_range * (1.0 - DEFAULT_ZOOM_FACTOR)
        } else {
            view_range * (1.0 + DEFAULT_ZOOM_FACTOR)
        };

        new_range = go_max(
            MIN_ZOOM_RANGE,
            go_min(new_range, self.model.max_x() - self.model.min_x()),
        );

        let mut new_min = step_under_mouse - new_range * mouse_proportion;
        let mut new_max = step_under_mouse + new_range * (1.0 - mouse_proportion);

        // Tail anchor: when zooming in at far right, keep the data tail
        // visible.
        if direction == "in"
            && mouse_proportion >= TAIL_ANCHOR_MOUSE_THRESHOLD
            && is_finite(self.x_max)
        {
            let right_pad = self.pixel_eps_x(new_range) * 2.0;
            if new_max < self.x_max - right_pad {
                let shift = (self.x_max + right_pad) - new_max;
                new_min += shift;
                new_max += shift;
            }
        }

        // Clamp to domain.
        let (dom_min, dom_max) = (self.model.min_x(), self.model.max_x());
        if new_min < dom_min {
            new_min = dom_min;
            new_max = go_min(new_min + new_range, dom_max);
        }
        if new_max > dom_max {
            new_max = dom_max;
            new_min = go_max(new_max - new_range, dom_min);
        }

        self.model.set_view_x_range(new_min, new_max);
        self.user_view_min_x = new_min;
        self.user_view_max_x = new_max;
        self.is_zoomed = true;
        self.dirty = true;
    }

    /// Draw renders all series using Braille patterns.
    pub fn draw(&mut self) {
        self.model.clear();

        // PARITY: Go's XLabelFormatter closure reads maxXLabelWidth() (and,
        // for TimeSeriesLineChart, the view range) through the chart pointer
        // at call time; it is only invoked inside DrawXYAxisAndLabel, during
        // which the graph geometry and view are fixed, so binding here is
        // equivalent.
        let x_label_formatter: LabelFormatter = match &self.x_label_formatter_factory {
            Some(factory) => factory(self),
            None => {
                let max_x_label_width = self.max_x_label_width();
                Box::new(move |_i, v| format_x_axis_tick(v, max_x_label_width as isize))
            }
        };
        self.model.x_label_formatter = x_label_formatter;

        // Draw axes and X labels via ntcharts, but suppress its Y labels and
        // draw our own. ntcharts v2.0.1 forces a label at graphHeight, which
        // stacks on top of the previous tick when graphHeight is just above
        // a multiple of yStep (e.g. "4.86" sitting on row y=6 and "4.05" on
        // y=5).
        let orig_y_fmter = std::mem::replace(
            &mut self.model.y_label_formatter,
            Box::new(|_, _| String::new()),
        );
        self.model.draw_xy_axis_and_label();
        self.model.y_label_formatter = orig_y_fmter;
        self.draw_y_labels();

        if self.model.graph_width() <= 0 || self.model.graph_height() <= 0 {
            self.dirty = false;
            return;
        }

        let mut start_x: i64 = 0;
        if self.model.y_step() > 0 {
            start_x = self.model.origin().x + 1;
        }

        // (order cloned to appease the borrow checker; Go ranges c.order.)
        let order = self.order.clone();
        for key in &order {
            self.draw_series(key, start_x);
        }

        self.draw_inspection_overlay(start_x);
        self.dirty = false;
    }

    /// drawYLabels draws Y-axis tick labels at positions i = 0, yStep,
    /// 2*yStep, ... and optionally at graphHeight when there's enough gap
    /// above the previous tick. Replaces ntcharts' drawYLabel, which in
    /// v2.0.1 unconditionally draws a label at graphHeight and stacks it
    /// onto the previous tick when graphHeight mod yStep is small.
    fn draw_y_labels(&mut self) {
        let y_step = self.model.y_step();
        let graph_h = self.model.graph_height();
        if y_step <= 0 || graph_h <= 0 {
            return;
        }
        let (view_min_y, view_max_y) = (self.model.view_min_y(), self.model.view_max_y());
        let increment = (view_max_y - view_min_y) / graph_h as f64;
        let origin = self.model.origin();

        // Go's inner `draw` closure, hoisted to a method (a closure would
        // double-borrow the model).
        let mut last_val = String::new();
        let mut last_i: i64 = 0;
        let mut i: i64 = 0;
        while i <= graph_h {
            last_val = self.draw_one_y_label(i, last_val, view_min_y, increment, origin);
            last_i = i;
            i += y_step;
        }
        // Add a top tick when the last stepped tick fell short of
        // graphHeight and there's room for a non-adjacent label.
        if last_i < graph_h && graph_h - last_i >= (y_step + 1) / 2 {
            self.draw_one_y_label(graph_h, last_val, view_min_y, increment, origin);
        }
    }

    /// The body of Go's `draw` closure inside drawYLabels.
    fn draw_one_y_label(
        &mut self,
        i: i64,
        last_val: String,
        view_min_y: f64,
        increment: f64,
        origin: Point,
    ) -> String {
        let v = view_min_y + increment * i as f64;
        let s = (self.model.y_label_formatter)(i, v);
        if s.is_empty() || s == last_val {
            return last_val;
        }
        // PARITY: Go len(s) counts BYTES, not display width (matches
        // braille::draw_y_label).
        self.model.canvas.set_string_with_style(
            Point {
                x: origin.x - s.len() as i64,
                y: origin.y - i,
            },
            &s,
            self.model.label_style,
        );
        s
    }

    /// drawSeries renders a single series onto the canvas.
    fn draw_series(&mut self, key: &str, start_x: i64) {
        let graph_width = self.model.graph_width();
        let graph_height = self.model.graph_height();
        let view_min_x = self.model.view_min_x();
        let view_max_x = self.model.view_max_x();
        let view_min_y = self.model.view_min_y();
        let view_max_y = self.model.view_max_y();
        let eps = self.pixel_eps_x(view_max_x - view_min_x);

        let Some(s) = self.data.get(key) else {
            return;
        };
        if s.x.is_empty() {
            return;
        }

        // Binary search for visible window.
        // PARITY: Go sort.Search with `s.X[i] >= ViewMinX` / `s.X[i] >
        // ViewMaxX+eps`; the predicates are negated verbatim (NOT rewritten
        // as `<`/`<=`) so NaN samples fall on the same side as in Go.
        #[allow(clippy::neg_cmp_op_on_partial_ord)]
        let lb = s.x.partition_point(|&x| !(x >= view_min_x));
        #[allow(clippy::neg_cmp_op_on_partial_ord)]
        let ub = s.x.partition_point(|&x| !(x > view_max_x + eps));

        if ub <= lb {
            return;
        }

        let mut b_grid = BrailleGrid::new(
            graph_width,
            graph_height,
            0.0,
            graph_width as f64,
            0.0,
            graph_height as f64,
        );

        let x_scale = graph_width as f64 / (view_max_x - view_min_x);
        let y_scale = graph_height as f64 / (view_max_y - view_min_y);

        // Go's `flush` closure over segments/current.
        fn flush(
            segments: &mut Vec<Vec<Float64Point>>,
            current: &mut Vec<Float64Point>,
            cap: usize,
        ) {
            if current.is_empty() {
                return;
            }
            segments.push(std::mem::replace(current, Vec::with_capacity(cap)));
        }

        let mut segments: Vec<Vec<Float64Point>> = Vec::with_capacity(1);
        let mut current: Vec<Float64Point> = Vec::with_capacity(ub - lb);

        for i in lb..ub {
            let Some(y_value) = self.scale_y_value(s.y[i]) else {
                flush(&mut segments, &mut current, ub - lb);
                continue;
            };

            let x = (s.x[i] - view_min_x) * x_scale;
            let y = (y_value - view_min_y) * y_scale;

            // PARITY: kept as Go's `< || >` (a NaN x — non-finite X samples
            // are not filtered — passes this check and is plotted, clamped
            // by the grid, like Go).
            if x < 0.0 || x > graph_width as f64 || y < 0.0 || y > graph_height as f64 {
                flush(&mut segments, &mut current, ub - lb);
                continue;
            }

            current.push(Float64Point { x, y });
        }
        flush(&mut segments, &mut current, ub - lb);

        for points in &segments {
            if points.len() == 1 {
                b_grid.set(b_grid.grid_point(points[0]));
                continue;
            }
            for i in 0..points.len() - 1 {
                let gp1 = b_grid.grid_point(points[i]);
                let gp2 = b_grid.grid_point(points[i + 1]);
                draw_line(&mut b_grid, gp1, gp2);
            }
        }

        let patterns = b_grid.braille_patterns();
        let style = s.style.cell_style(self.dark_background);

        draw_braille_patterns_occluded(
            &mut self.model.canvas,
            Point { x: start_x, y: 0 },
            &patterns,
            style,
        );
    }

    /// drawInspectionOverlay renders the data inspection legend.
    fn draw_inspection_overlay(&mut self, graph_start_x: i64) {
        if !self.inspection.active
            || self.model.graph_width() <= 0
            || self.model.graph_height() <= 0
        {
            return;
        }
        let graph_width = self.model.graph_width();
        let graph_height = self.model.graph_height();
        let dark = self.dark_background;
        let legend_style = inspection_legend_style(dark);

        // Hairline X in canvas coordinates.
        let canvas_x = graph_start_x + self.inspection.mouse_x;

        // Vertical hairline.
        for y in 0..graph_height {
            self.model.canvas.set_cell(
                Point { x: canvas_x, y },
                Cell::new_with_style(BOX_LIGHT_VERTICAL, inspection_line_style(dark)),
            );
        }

        // We anchor inspection at a single data X and show values for all
        // series at that X.
        let anchor_x = self.inspection.data_x;
        if !is_finite(anchor_x) || self.order.is_empty() {
            return;
        }

        struct LegendEntry {
            label_runes: Vec<char>,
            block_runes: Vec<char>,
            block_style: CellStyle,
        }

        let block_runes: Vec<char> = "▬▬".chars().collect();
        let mut entries: Vec<LegendEntry> = Vec::with_capacity(self.order.len());
        let mut max_label_width: i64 = 0;

        // Build entries in render order: topmost series first (last in
        // c.order).
        for key in self.order.iter().rev() {
            let Some(s) = self.data.get(key) else {
                continue;
            };
            if s.x.is_empty() {
                continue;
            }

            let idx = nearest_index_for_x(&s.x, anchor_x);
            if idx < 0 || idx as usize >= s.y.len() {
                continue;
            }
            let idx = idx as usize;

            let y_val = s.y[idx];
            let label = format_inspection_label_with(
                self,
                self.inspection_label_formatter.as_deref(),
                key,
                s.x[idx],
                y_val,
            );
            // PARITY: Go measures len([]rune(label)) — rune count, not
            // display columns (metric labels are effectively single-width).
            let label_runes: Vec<char> = label.chars().collect();
            let lw = label_runes.len() as i64;
            if lw > max_label_width {
                max_label_width = lw;
            }

            let series_style = s.style;
            // Go: seriesStyle.Inherit(inspectionLegendStyle) — the series
            // foreground wins, the legend background fills in.
            let block_style = CellStyle {
                fg: Some(series_style.fg.resolve(dark)),
                bg: legend_style.bg,
                bold: false,
            };

            entries.push(LegendEntry {
                label_runes,
                block_runes: block_runes.clone(),
                block_style,
            });
        }

        if entries.is_empty() {
            return;
        }

        // Don't draw more legend rows than we have vertical space for.
        if entries.len() as i64 > graph_height {
            entries.truncate(graph_height as usize);
        }

        // blocks + space + label
        let total_legend_width = block_runes.len() as i64 + 1 + max_label_width;
        let right_bound = graph_start_x + graph_width;

        // Prefer placing the legend to the right of the hairline if it fits.
        let mut legend_x = canvas_x + 1;
        if legend_x + total_legend_width >= right_bound {
            legend_x = canvas_x - 1 - total_legend_width;
        }
        if legend_x < graph_start_x {
            legend_x = graph_start_x;
        }

        // Vertically center the block of legend rows within the graph.
        let legend_height = entries.len() as i64;
        let mut legend_y_start = (graph_height / 2 - legend_height / 2).max(0);
        if legend_y_start + legend_height > graph_height {
            legend_y_start = (graph_height - legend_height).max(0);
        }

        // Render each legend row: colored block(s) + space + "X: Y".
        for (i, entry) in entries.iter().enumerate() {
            let y = legend_y_start + i as i64;
            let mut x = legend_x;

            // Colored block (tied to series color).
            for &r in &entry.block_runes {
                self.model
                    .canvas
                    .set_cell(Point { x, y }, Cell::new_with_style(r, entry.block_style));
                x += 1;
            }

            self.model
                .canvas
                .set_cell(Point { x, y }, Cell::new_with_style(' ', legend_style));
            x += 1;

            for &ch in &entry.label_runes {
                self.model
                    .canvas
                    .set_cell(Point { x, y }, Cell::new_with_style(ch, legend_style));
                x += 1;
            }
        }
    }

    /// formatInspectionLabel returns the label shown in the inspection
    /// legend.
    #[allow(dead_code)] // parity surface; draw_inspection_overlay calls the _with form
    fn format_inspection_label(&self, series_key: &str, x: f64, y: f64) -> String {
        format_inspection_label_with(
            self,
            self.inspection_label_formatter.as_deref(),
            series_key,
            x,
            y,
        )
    }

    /// findNearestDataPoint returns the data point nearest to mouseX in the
    /// topmost series (Go returns `(dataX, dataY, idx, ok)`).
    fn find_nearest_data_point(&self, mouse_x: i64) -> Option<(f64, f64, usize)> {
        let s = self.top_series()?;
        if s.x.is_empty() || self.model.graph_width() <= 0 {
            return None;
        }

        let x_range = self.model.view_max_x() - self.model.view_min_x();
        if x_range <= 0.0 {
            return None;
        }

        let target_x =
            self.model.view_min_x() + (mouse_x as f64 / self.model.graph_width() as f64) * x_range;
        let best_idx = nearest_index_for_x(&s.x, target_x);
        if best_idx < 0 {
            return None;
        }
        let best_idx = best_idx as usize;

        Some((s.x[best_idx], s.y[best_idx], best_idx))
    }

    /// pixelEpsX returns approximately 1 horizontal pixel in X data units.
    pub(crate) fn pixel_eps_x(&self, x_range: f64) -> f64 {
        if self.model.graph_width() <= 0 || x_range <= 0.0 {
            return 0.0;
        }
        x_range / self.model.graph_width() as f64
    }

    /// Go `scaleYValue` (returns `(float64, bool)`).
    fn scale_y_value(&self, y: f64) -> Option<f64> {
        if !is_finite(y) {
            return None;
        }
        if !self.is_log_y() {
            return Some(y);
        }
        if y <= 0.0 {
            return None;
        }
        // PARITY: Go math.Log10 (see calculate_log_range).
        Some(y.log10())
    }

    /// DrawIfNeeded draws only if the chart is marked dirty.
    pub fn draw_if_needed(&mut self) {
        if self.dirty {
            self.draw();
        }
    }

    /// Title returns the chart title.
    pub fn title(&self) -> &str {
        &self.title
    }

    /// SetFocused sets the chart's focus state.
    pub fn set_focused(&mut self, focused: bool) {
        self.focused = focused;
    }

    /// Resize updates the chart's canvas dimensions.
    pub fn resize(&mut self, width: i64, height: i64) {
        if self.model.width() == width && self.model.height() == height {
            return;
        }
        self.model.resize(width, height);
        self.update_ranges();
        self.dirty = true;
    }

    /// Park minimizes canvas memory for off-screen charts.
    pub fn park(&mut self) {
        self.resize(PARKED_CANVAS_SIZE, PARKED_CANVAS_SIZE);
    }

    /// SetGraphStyle sets the style for the topmost series.
    // PARITY: unlike set_series_style, Go does NOT mark the chart dirty
    // here. Go takes *lipgloss.Style; the adaptive-foreground subset is
    // passed by value.
    pub fn set_graph_style(&mut self, s: SeriesStyle) {
        if let Some(last) = self.order.last()
            && let Some(top) = self.data.get_mut(last)
        {
            top.style = s;
        }
    }

    /// SetSeriesStyle sets the style for the named series, if present.
    // PARITY: Go additionally no-ops on a nil style pointer, which is
    // unrepresentable here.
    pub fn set_series_style(&mut self, key: &str, style: SeriesStyle) {
        if let Some(series) = self.data.get_mut(key) {
            series.style = style;
            self.dirty = true;
        }
    }

    /// SetInspectionLabelFormatter customizes inspection legend labels
    /// (None restores the default numeric formatter, like Go's nil).
    pub fn set_inspection_label_formatter(&mut self, formatter: Option<InspectionLabelFormatter>) {
        self.inspection_label_formatter = formatter;
        self.dirty = true;
    }

    /// Go: timeserieslinechart.go:65 assigns the `yTickFormatter` field
    /// directly (package-internal); ported as a setter so the model's Y
    /// label formatter closure is re-captured.
    pub fn set_y_tick_formatter(&mut self, formatter: YTickFormatter) {
        self.y_tick_formatter = Some(formatter);
        self.install_y_label_formatter();
    }

    /// SeriesCount returns the number of series in the chart.
    pub fn series_count(&self) -> usize {
        self.data.len()
    }

    /// RemoveSeries removes a series by key and recomputes bounds.
    pub fn remove_series(&mut self, key: &str) {
        if !self.data.contains_key(key) {
            return;
        }
        self.data.remove(key);

        for i in 0..self.order.len() {
            if self.order[i] == key {
                self.order.remove(i);
                break;
            }
        }

        self.recompute_bounds();
        self.update_ranges();
        self.dirty = true;
    }

    /// recomputeBounds aggregates bounds from all series.
    /// O(n) in number of series, not data points.
    fn recompute_bounds(&mut self) {
        self.x_min = f64::INFINITY;
        self.x_max = f64::NEG_INFINITY;
        self.y_min = f64::INFINITY;
        self.y_max = f64::NEG_INFINITY;

        // PARITY: Go iterates the map unordered; min/max aggregation is
        // order-independent.
        let mut x_min = self.x_min;
        let mut x_max = self.x_max;
        let mut y_min = self.y_min;
        let mut y_max = self.y_max;
        for s in self.data.values() {
            if s.x.is_empty() || s.y.is_empty() {
                continue;
            }
            let (sx_min, sx_max, sy_min, sy_max) = s.bounds();
            x_min = go_min(x_min, sx_min);
            x_max = go_max(x_max, sx_max);
            y_min = go_min(y_min, sy_min);
            y_max = go_max(y_max, sy_max);
        }
        self.x_min = x_min;
        self.x_max = x_max;
        self.y_min = y_min;
        self.y_max = y_max;
    }

    /// snapInspectionToDataX snaps the crosshair to the nearest sample.
    fn snap_inspection_to_data_x(&mut self, target_x: f64) {
        let graph_width = self.model.graph_width();
        let x_range = self.model.view_max_x() - self.model.view_min_x();
        let view_min_x = self.model.view_min_x();

        let (data_x, data_y) = {
            let Some(s) = self.top_series() else {
                return;
            };
            if !self.inspection.active || graph_width <= 0 || s.x.is_empty() {
                return;
            }
            if x_range <= 0.0 {
                return;
            }
            let idx = nearest_index_for_x(&s.x, target_x);
            if idx < 0 {
                return;
            }
            let idx = idx as usize;
            (s.x[idx], s.y[idx])
        };

        self.inspection.data_x = data_x;
        self.inspection.data_y = data_y;

        // Pixel snap to the exact dataX under current view.
        let mouse_x_frac = (self.inspection.data_x - view_min_x) / x_range;
        let mouse_x = (mouse_x_frac * graph_width as f64).round() as i64;
        self.inspection.mouse_x = (graph_width - 1).min(mouse_x).max(0);
        self.dirty = true;
    }

    /// InspectAtDataX activates inspection at the sample nearest to targetX.
    pub fn inspect_at_data_x(&mut self, target_x: f64) {
        let no_data = match self.top_series() {
            None => true,
            Some(s) => s.x.is_empty(),
        };
        if no_data || self.model.graph_width() <= 0 {
            return;
        }
        self.inspection.active = true;
        self.snap_inspection_to_data_x(target_x);
    }

    /// refreshInspectionAfterViewChange keeps the crosshair on the same
    /// DataX after view/domain changes.
    pub(crate) fn refresh_inspection_after_view_change(&mut self) {
        if !self.inspection.active {
            return;
        }
        self.snap_inspection_to_data_x(self.inspection.data_x);
    }

    /// StartInspection begins inspection at the given mouse X position.
    pub fn start_inspection(&mut self, mouse_x: i64) {
        let no_data = match self.top_series() {
            None => true,
            Some(s) => s.x.is_empty(),
        };
        if no_data || self.model.graph_width() <= 0 {
            return;
        }
        self.inspection.active = true;
        self.update_inspection(mouse_x);
    }

    /// UpdateInspection moves the crosshair to a new mouse X position.
    pub fn update_inspection(&mut self, mouse_x: i64) {
        if !self.inspection.active || self.model.graph_width() <= 0 {
            return;
        }
        // Clamp to the drawable graph area.
        self.inspection.mouse_x = (self.model.graph_width() - 1).min(mouse_x).max(0);

        if let Some((data_x, _, _)) = self.find_nearest_data_point(mouse_x) {
            self.snap_inspection_to_data_x(data_x);
        }
        self.dirty = true;
    }

    /// EndInspection exits inspection mode.
    pub fn end_inspection(&mut self) {
        self.inspection = ChartInspection::default();
        self.dirty = true;
    }

    /// IsInspecting reports whether inspection is active.
    pub fn is_inspecting(&self) -> bool {
        self.inspection.active
    }

    /// InspectionData returns the inspected point's coordinates
    /// (Go returns `(x, y, active)`).
    pub fn inspection_data(&self) -> (f64, f64, bool) {
        (
            self.inspection.data_x,
            self.inspection.data_y,
            self.inspection.active,
        )
    }

    /// PromoteSeriesToTop moves a series to the end of draw order (visually
    /// on top).
    pub fn promote_series_to_top(&mut self, key: &str) {
        if key.is_empty() || self.order.is_empty() {
            return;
        }

        let Some(idx) = self.order.iter().position(|k| k == key) else {
            return;
        };
        if idx == self.order.len() - 1 {
            return;
        }

        let k = self.order.remove(idx);
        self.order.push(k);
        self.dirty = true;
    }

    /// DrawOrder returns the series keys in their current draw order.
    /// Series are rendered in this order; the last appears on top.
    pub fn draw_order(&self) -> Vec<String> {
        self.order.clone()
    }

    /// Sets which AdaptiveColor variant draw() resolves. See the
    /// `dark_background` field's DIVERGENCE(S13) note.
    pub fn set_dark_background(&mut self, dark: bool) {
        if self.dark_background == dark {
            return;
        }
        self.dark_background = dark;
        self.model.axis_style = axis_style(dark);
        self.model.label_style = label_style(dark);
        self.dirty = true;
    }
}

/// formatInspectionLabel's body (a free fn so draw_inspection_overlay can
/// call it while `self.data`/`self.order` are borrowed).
fn format_inspection_label_with(
    chart: &EpochLineChart,
    formatter: Option<InspectionLabelFormatterRef<'_>>,
    series_key: &str,
    x: f64,
    y: f64,
) -> String {
    if let Some(f) = formatter {
        return f(chart, series_key, x, y);
    }
    // Go: fmt.Sprintf("%v: %v", x, formatSigFigs(y, 4)).
    format!("{}: {}", go_sprint_float(x), go_fmt::format_float_g(y, 4))
}

/// `fmt.Sprintf("%v", x)` for a float64 —
/// `strconv.FormatFloat(x, 'g', -1, 64)` (shortest round-trip, scientific
/// when the decimal exponent is < -4 or >= 6).
///
/// DIVERGENCE(hosting): the canonical port lives in
/// `leet-data::run_overview::go_sprint_float` but is private there and this
/// crate cannot edit leet-data, so the layout logic is duplicated. The
/// digits here come from Rust `{:e}` (shortest round-trip); on exact
/// round-trip ties Rust rounds away from zero where Go rounds half-to-even —
/// unreachable for the step values this formats. TODO(parity): dedupe once
/// leet-data exports it.
fn go_sprint_float(v: f64) -> String {
    if v.is_nan() {
        return "NaN".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 {
            "+Inf".to_string()
        } else {
            "-Inf".to_string()
        };
    }
    if v == 0.0 {
        // PARITY: strconv renders ±0 as "0"/"-0" (never in exponent form).
        return if v.is_sign_negative() {
            "-0".to_string()
        } else {
            "0".to_string()
        };
    }

    let neg = v < 0.0;
    // Shortest round-trip digits, e.g. "1.234567e6", "5e0".
    let sci = format!("{:e}", v.abs());
    let (mantissa, e) = sci.split_once('e').expect("`{:e}` always has an exponent");
    let exp: i32 = e.parse().expect("valid exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let digits = digits.as_str();

    let mut out = String::new();
    if neg {
        out.push('-');
    }

    if !(-4..6).contains(&exp) {
        // Scientific: d[.ddd]e±dd (exponent sign always, min two digits).
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        if exp < 0 {
            out.push('-');
        } else {
            out.push('+');
        }
        let e = exp.unsigned_abs();
        if e < 10 {
            out.push('0');
        }
        out.push_str(&e.to_string());
    } else if exp >= 0 {
        // Fixed with the decimal point inside/after the digit string.
        let int_len = (exp + 1) as usize;
        if digits.len() <= int_len {
            out.push_str(digits);
            for _ in digits.len()..int_len {
                out.push('0');
            }
        } else {
            out.push_str(&digits[..int_len]);
            out.push('.');
            out.push_str(&digits[int_len..]);
        }
    } else {
        // 0.0…digits
        out.push_str("0.");
        for _ in 0..(-exp - 1) {
            out.push('0');
        }
        out.push_str(digits);
    }
    out
}

// ---------------------------------------------------------------------------
// Package-level drawing helpers.
// ---------------------------------------------------------------------------

/// drawBraillePatternsOccluded draws braille runes with opaque compositing.
///
/// Unlike ntcharts' graph.DrawBraillePatterns which merges patterns, this
/// replaces existing cells entirely. This prevents color "spilling" when
/// multiple series overlap.
fn draw_braille_patterns_occluded(m: &mut Canvas, p: Point, b: &[Vec<char>], s: CellStyle) {
    for (y, row) in b.iter().enumerate() {
        for (x, &r) in row.iter().enumerate() {
            if r != BRAILLE_BLOCK_OFFSET {
                draw_braille_rune(
                    m,
                    p + Point {
                        x: x as i64,
                        y: y as i64,
                    },
                    r,
                    s,
                );
            }
        }
    }
}

/// drawBrailleRune draws a single braille rune, replacing any existing
/// content.
fn draw_braille_rune(m: &mut Canvas, p: Point, r: char, s: CellStyle) {
    if r == NULL || !is_braille_pattern(r) {
        return;
    }
    m.set_cell(p, Cell::new_with_style(r, s));
}

/// drawLine draws a line using Bresenham's algorithm.
///
/// See <https://en.wikipedia.org/wiki/Bresenham%27s_line_algorithm>.
fn draw_line(b_grid: &mut BrailleGrid, p1: Point, p2: Point) {
    // Go: int(math.Abs(float64(p2.X - p1.X))) — i64 abs is exact here.
    let dx = (p2.x - p1.x).abs();
    let dy = (p2.y - p1.y).abs();

    let sx: i64 = if p1.x > p2.x { -1 } else { 1 };
    let sy: i64 = if p1.y > p2.y { -1 } else { 1 };

    let mut err = dx - dy;
    let (mut x, mut y) = (p1.x, p1.y);

    loop {
        b_grid.set(Point { x, y });
        if x == p2.x && y == p2.y {
            break;
        }
        let e2 = 2 * err;
        if e2 > -dy {
            err -= dy;
            x += sx;
        }
        if e2 < dx {
            err += dx;
            y += sy;
        }
    }
}

/// Go `isFinite`: !IsNaN && !IsInf.
pub(crate) fn is_finite(f: f64) -> bool {
    !f.is_nan() && !f.is_infinite()
}

/// TruncateTitle truncates a title to fit maxWidth, adding ellipsis if
/// needed.
pub fn truncate_title(title: &str, max_width: i64) -> String {
    if text_width(title) as i64 <= max_width {
        return title.to_string();
    }
    if max_width <= 3 {
        return "...".to_string();
    }

    let available_width = max_width - 3;

    // Try to break at a separator for cleaner truncation
    let separators = ["/", "_", ".", "-", ":"];

    let mut best_truncate_at: i64 = 0;
    // PARITY: Go `for i := range title` yields byte offsets of rune starts.
    for (i, _) in title.char_indices() {
        if text_width(&title[..i]) as i64 > available_width {
            break;
        }
        best_truncate_at = i as i64;
    }

    if best_truncate_at > available_width / 2 {
        // Look for a separator near the truncation point for cleaner break
        for sep in separators {
            if let Some(idx) = title[..best_truncate_at as usize].rfind(sep)
                && idx as i64 > best_truncate_at * 2 / 3
            {
                // Found a good separator position.
                best_truncate_at = (idx + sep.len()) as i64;
                break;
            }
        }
    }

    if best_truncate_at <= 0 {
        best_truncate_at = 1;
    }
    if best_truncate_at > title.len() as i64 {
        best_truncate_at = title.len() as i64;
    }

    // PARITY/DIVERGENCE: when the `= 1` fallback lands inside a multibyte
    // rune, Go emits an invalid UTF-8 prefix; Rust strings cannot represent
    // that, so snap DOWN to the previous char boundary ("..." for a leading
    // wide rune). Unreachable for ASCII metric names.
    let mut cut = best_truncate_at as usize;
    while cut > 0 && !title.is_char_boundary(cut) {
        cut -= 1;
    }
    format!("{}...", &title[..cut])
}

// ---------------------------------------------------------------------------
// Inspection.
// ---------------------------------------------------------------------------

/// ChartInspection holds crosshair overlay state.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct ChartInspection {
    /// Active indicates whether inspection mode is on.
    pub active: bool,
    /// MouseX is the vertical crosshair position in graph-local pixels.
    pub mouse_x: i64,
    /// DataX, DataY are coordinates of the nearest data sample.
    pub data_x: f64,
    pub data_y: f64,
}

/// nearestIndexForX returns the index closest to targetX in a sorted slice.
/// Returns -1 if xs is empty.
pub(crate) fn nearest_index_for_x(xs: &[f64], target_x: f64) -> i64 {
    if xs.is_empty() {
        return -1;
    }
    // Go sort.SearchFloat64s: smallest index with xs[i] >= targetX. The
    // predicate is negated verbatim so NaN samples fall on the same side.
    #[allow(clippy::neg_cmp_op_on_partial_ord)]
    let j = xs.partition_point(|&v| !(v >= target_x)) as i64;

    let mut best_idx: i64 = -1;
    let mut best_dist = f64::INFINITY;
    for i in [j - 1, j, j + 1] {
        if i < 0 || i as usize >= xs.len() {
            continue;
        }
        let d = (xs[i as usize] - target_x).abs();
        if d < best_dist {
            best_dist = d;
            best_idx = i;
        }
    }
    best_idx
}

// ---------------------------------------------------------------------------
// testhelpers.go accessors (EpochLineChart subset), pub(crate) per
// PORTING.md's testing conventions.
// ---------------------------------------------------------------------------

#[cfg(test)]
impl EpochLineChart {
    /// testhelpers.go `TestInspectionMouseX`: exposes the current overlay
    /// pixel X for tests.
    pub(crate) fn test_inspection_mouse_x(&self) -> (i64, bool) {
        (self.inspection.mouse_x, self.inspection.active)
    }

    /// testhelpers.go `TestBounds`: exposes the chart's current bounds.
    pub(crate) fn test_bounds(&self) -> (f64, f64, f64, f64) {
        (self.x_min, self.x_max, self.y_min, self.y_max)
    }

    /// testhelpers.go `TestIsLogY`.
    pub(crate) fn test_is_log_y(&self) -> bool {
        self.is_log_y()
    }

    /// testhelpers.go `TestFormatYTick`.
    pub(crate) fn test_format_y_tick(&self, v: f64) -> String {
        self.format_y_tick(v)
    }
}

/// Transliteration of `epochlinechart_test.go`.
///
/// TestTimeSeriesLineChart_LogY_FormatsTicksWithMetricUnits
/// (epochlinechart_test.go:381) exercises `TimeSeriesLineChart` and
/// transliterates with the `timeseries_line_chart` module port.
#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    /// TestEpochLineChart_Range.
    #[test]
    fn epoch_line_chart_range() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(100, 10);

        // Add a couple of points; Y padding should expand range.
        c.add_data(
            m,
            MetricData {
                x: vec![0.0, 1.0],
                y: vec![0.5, 1.0],
            },
        );

        assert!(c.view_min_y() < 0.5);
        assert!(c.view_max_y() > 1.0);

        // Force X-range to expand in rounded tens (0..30) once we exceed 20
        // steps.
        for i in 0..21 {
            c.add_data(
                m,
                MetricData {
                    x: vec![(i + 2) as f64],
                    y: vec![i as f64],
                },
            );
        }
        // Expecting MaxX≈30 after 21 steps.
        assert!((c.max_x() - 30.0).abs() <= 1e-9);
        // Expecting view range to be [0, 30].
        // PARITY: Go asserts require.NotEqual(t, c.ViewMinX(), 0) — a
        // float64-vs-untyped-int comparison that is vacuously true under
        // reflect.DeepEqual (ViewMinX is in fact 0.0 here), so it is not
        // ported.
        assert!((c.view_max_x() - 30.0).abs() <= 1e-9);
    }

    /// TestEpochLineChart_NonFiniteValuesDoNotPoisonRange.
    #[test]
    fn epoch_line_chart_non_finite_values_do_not_poison_range() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(100, 10);

        // A diverged loss logs NaN/Inf mid-run; the Y range must stay finite
        // and continue tracking the finite samples.
        c.add_data(
            m,
            MetricData {
                x: vec![0.0, 1.0, 2.0, 3.0],
                y: vec![0.5, f64::NAN, f64::INFINITY, 2.0],
            },
        );

        assert!(c.view_min_y() < 0.5 && !c.view_min_y().is_nan());
        assert!(c.view_max_y() > 2.0 && c.view_max_y() != f64::INFINITY);

        // Later finite samples keep extending the range as usual.
        c.add_data(
            m,
            MetricData {
                x: vec![4.0],
                y: vec![3.0],
            },
        );
        assert!(c.view_max_y() > 3.0);
        assert!(!c.view_min_y().is_nan());
    }

    /// TestEpochLineChart_ZoomClampsAndAnchors.
    #[test]
    fn epoch_line_chart_zoom_clamps_and_anchors() {
        let m = "acc";
        let mut c = EpochLineChart::new(m);
        c.resize(120, 12);
        for i in 0..40 {
            c.add_data(
                m,
                MetricData {
                    x: vec![i as f64],
                    y: vec![0.1 + 0.02 * i as f64],
                },
            );
        }
        let (old_min, old_max) = (c.view_min_x(), c.view_max_x());
        let old_range = old_max - old_min;

        // Zoom in around the middle of the graph - should NOT snap to tail.
        let mouse_x = c.graph_width() / 2;
        c.handle_zoom("in", mouse_x);

        let (new_min, new_max) = (c.view_min_x(), c.view_max_x());
        let new_range = new_max - new_min;

        // Verify zoom reduced range.
        assert!(new_range < old_range);

        // Verify we're still centered around the middle (not snapped to
        // tail).
        let mid_point = (new_min + new_max) / 2.0;
        let expected_mid = (old_min + old_max) / 2.0;
        let tolerance = old_range * 0.2; // Allow some movement but not a full snap
        assert!((mid_point - expected_mid).abs() <= tolerance);

        // Test zoom at right edge - should maintain tail visibility.
        c.set_view_x_range(30.0, 40.0); // Position at tail
        let gw = c.graph_width();
        c.handle_zoom("in", gw - 1); // Mouse at far right

        // Should still see the last data point (39).
        assert!(c.view_max_x() >= 39.0);
    }

    /// TestEpochLineChart_ZoomDoesNotSnapToTailAwayFromRight.
    ///
    /// When zooming away from the right edge (and not already at the tail),
    /// the view should NOT jump to the tail.
    #[test]
    fn epoch_line_chart_zoom_does_not_snap_to_tail_away_from_right() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(120, 12);
        for i in 0..40 {
            c.add_data(
                m,
                MetricData {
                    x: vec![i as f64],
                    y: vec![i as f64],
                },
            );
        }
        // Sanity: initial view is [0, 40] with data tail at x≈39.

        let mouse_x = c.graph_width() / 4; // left-ish
        c.handle_zoom("in", mouse_x);

        // If the view wrongly snapped to the tail, ViewMaxX would be ~39.
        assert!((c.view_max_x() - 39.0).abs() > 0.75);
    }

    /// TestEpochLineChart_ZoomNearRightAnchorsToTail.
    ///
    /// When zooming near the right edge, we still anchor to the tail.
    #[test]
    fn epoch_line_chart_zoom_near_right_anchors_to_tail() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(120, 12);
        for i in 0..40 {
            c.add_data(
                m,
                MetricData {
                    x: vec![i as f64],
                    y: vec![0.5],
                },
            );
        }

        let mouse_x = (c.graph_width() as f64 * 0.95) as i64; // near right edge
        c.handle_zoom("in", mouse_x);

        // Expect the right edge to be close to the last data point (~39).
        assert!((c.view_max_x() - 39.0).abs() < 1.0);
    }

    /// Shared scaffolding for the Y-label tests: returns the plot rows
    /// carrying a non-blank Y label (text left of axis), mirroring the Go
    /// tests' line scanning. Go scans stripANSI(c.View()); text_rows() is
    /// already style-free, and byte offsets equal char offsets left of the
    /// axis (labels are ASCII).
    fn labeled_rows(lines: &[String]) -> (i64, Vec<usize>) {
        // Locate the Y-axis column ('│' for axis, '└' for the bottom-left
        // corner).
        let mut axis_col: i64 = -1;
        for line in lines {
            if let Some(i) = line.chars().position(|ch| ch == '│' || ch == '└') {
                axis_col = i as i64;
                break;
            }
        }
        let mut rows: Vec<usize> = Vec::new();
        if axis_col < 0 {
            return (axis_col, rows);
        }
        for (r, line) in lines.iter().enumerate() {
            // Skip the X-axis label row, which lives below the axis line and
            // has no Y label of its own.
            if !line.contains(['│', '└']) {
                continue;
            }
            if axis_col > line.chars().count() as i64 {
                continue;
            }
            let prefix: String = line.chars().take(axis_col as usize).collect();
            if !prefix.trim().is_empty() {
                rows.push(r);
            }
        }
        (axis_col, rows)
    }

    /// TestEpochLineChart_YLabelsDoNotStack guards against the ntcharts
    /// v2.0.1 regression where drawYLabel forces a label at graphHeight,
    /// stacking it directly above the previous tick when graphHeight mod
    /// yStep is small.
    ///
    /// At height 8 the chart has graphHeight=6 and yStep=5, so the buggy
    /// behavior places labels on rows i=5 and i=6 (adjacent). After the fix
    /// only rows i=0 and i=5 carry labels.
    #[test]
    fn epoch_line_chart_y_labels_do_not_stack() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(80, 8);
        c.add_data(
            m,
            MetricData {
                x: vec![0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                y: vec![4.86, 4.0, 3.0, 2.0, 1.0, 0.5],
            },
        );
        c.draw();

        let lines = c.canvas.text_rows();
        assert!(
            lines.len() >= 7,
            "expected chart to be at least 7 rows tall"
        );

        let (axis_col, labeled) = labeled_rows(&lines);
        assert!(axis_col >= 0, "expected to find Y-axis column");
        assert!(!labeled.is_empty(), "expected at least one Y label");

        for i in 1..labeled.len() {
            assert!(
                labeled[i] - labeled[i - 1] > 1,
                "Y labels stacked on adjacent rows {} and {}:\n{}",
                labeled[i - 1],
                labeled[i],
                lines.join("\n")
            );
        }
    }

    /// TestEpochLineChart_YLabelsKeepTopTickWhenSpaced verifies that we
    /// still draw a label at graphHeight when the gap above the previous
    /// stepped tick is large enough to avoid stacking. Height 13 →
    /// graphHeight=11; ticks at i=0,5,10 leave a 1-row gap to graphHeight=11
    /// (no top tick), so we test a height where the gap >= yStep/2 instead.
    #[test]
    fn epoch_line_chart_y_labels_keep_top_tick_when_spaced() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        // Height 10 → graphHeight=8; stepped ticks at i=0,5; gap to top =
        // 3 >= 3, so a top tick at i=8 is added.
        c.resize(80, 10);
        c.add_data(
            m,
            MetricData {
                x: vec![0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                y: vec![10.0, 8.0, 6.0, 4.0, 2.0, 0.0],
            },
        );
        c.draw();

        let lines = c.canvas.text_rows();
        let (axis_col, labeled) = labeled_rows(&lines);
        assert!(axis_col >= 0);

        assert!(
            labeled.len() >= 3,
            "expected at least 3 Y labels (top + middle + bottom):\n{}",
            lines.join("\n")
        );
        // And still no stacking.
        for i in 1..labeled.len() {
            assert!(
                labeled[i] - labeled[i - 1] > 1,
                "Y labels stacked on rows {} and {}",
                labeled[i - 1],
                labeled[i]
            );
        }
    }

    /// TestTruncateTitle.
    #[test]
    fn truncate_title_cases() {
        let tests: &[(&str, &str, i64, &str)] = &[
            ("fits within max width", "short", 10, "short"),
            (
                "needs basic truncation",
                "this is a very long title",
                10,
                "this is...",
            ),
            (
                "truncates at separator",
                "path/to/file/document.txt",
                15,
                "path/to/file...",
            ),
            ("tiny max width", "title", 3, "..."),
            ("empty string", "", 10, ""),
        ];

        for &(name, title, max_width, want) in tests {
            assert_eq!(truncate_title(title, max_width), want, "{name}");
        }
    }

    /// TestFormatXAxisTick (units.go's FormatXAxisTick, called as the chart's
    /// X label formatter).
    #[test]
    fn format_x_axis_tick_cases() {
        let tests: &[(&str, f64, isize, &str)] = &[
            // Special values
            ("zero", 0.0, 0, "0"),
            ("NaN", f64::NAN, 0, ""),
            ("positive infinity", f64::INFINITY, 0, ""),
            ("negative infinity", f64::NEG_INFINITY, 0, ""),
            // Small integers (no suffix)
            ("one", 1.0, 0, "1"),
            ("small", 42.0, 0, "42"),
            ("hundred", 100.0, 0, "100"),
            ("max before k", 999.0, 0, "999"),
            // Thousands (k)
            ("exactly 1k", 1000.0, 0, "1k"),
            ("1.5k", 1500.0, 0, "1.5k"),
            ("fractional k", 1234.0, 0, "1.23k"),
            ("large k", 50000.0, 0, "50k"),
            ("max k", 999000.0, 0, "999k"),
            ("high precision k", 999600.0, 0, "999.6k"),
            // Millions (M)
            ("exactly 1M", 1e6, 0, "1M"),
            ("1.2M", 1.2e6, 0, "1.2M"),
            ("fractional M", 1234567.0, 0, "1.23M"),
            ("high precision M", 999.95e6, 0, "999.95M"),
            // Billions (G)
            ("exactly 1G", 1e9, 0, "1G"),
            ("2.5G", 2.5e9, 0, "2.5G"),
            // Trillions (T)
            ("exactly 1T", 1e12, 0, "1T"),
            // Negative values
            ("negative small", -42.0, 0, "-42"),
            ("negative k", -1500.0, 0, "-1.5k"),
            ("negative M", -1.2e6, 0, "-1.2M"),
            // Boundary bump: rounding at 2 decimals produces "1000"
            ("999.9996k bumps to M", 999999.6, 0, "1M"),
            ("999.9996M bumps to G", 999999.6e3, 0, "1G"),
            // Width constraints
            ("width forces fewer decimals", 1234.0, 4, "1.2k"),
            ("width forces integer", 1234.0, 3, "1k"),
            ("width allows full precision", 1234.0, 10, "1.23k"),
            ("negative with width", -1234.0, 5, "-1.2k"),
            // Width-constrained bump: reduction to 0 decimals triggers bump
            ("width causes bump", 999600.0, 4, "1M"),
        ];

        for &(name, value, max_width, want) in tests {
            assert_eq!(format_x_axis_tick(value, max_width), want, "{name}");
        }
    }

    /// TestEpochLineChart_ToggleYScale_RejectsNonPositiveOnlyData.
    #[test]
    fn epoch_line_chart_toggle_y_scale_rejects_non_positive_only_data() {
        let mut c = EpochLineChart::new("loss");
        c.resize(80, 12);
        c.add_data(
            "run",
            MetricData {
                x: vec![0.0, 1.0, 2.0],
                y: vec![-3.0, 0.0, -1.0],
            },
        );

        assert!(!c.test_is_log_y());
        assert!(!c.toggle_y_scale());
        assert!(!c.test_is_log_y());
    }

    /// TestEpochLineChart_LogY_FormatsTicksInRawUnits.
    #[test]
    fn epoch_line_chart_log_y_formats_ticks_in_raw_units() {
        let mut c = EpochLineChart::new("loss");
        c.resize(80, 12);
        c.add_data(
            "run",
            MetricData {
                x: vec![0.0, 1.0, 2.0],
                y: vec![0.1, 1.0, 10.0],
            },
        );

        assert!(c.toggle_y_scale());
        assert!(c.test_is_log_y());
        assert_eq!(c.test_format_y_tick(-1.0), "0.1");
        assert_eq!(c.test_format_y_tick(0.0), "1");
        assert_eq!(c.test_format_y_tick(1.0), "10");
    }

    // ----- Port-only anchors (not in the Go test files) ---------------------

    /// Anchors the local `%v` float port against a Go probe of
    /// `fmt.Sprintf("%v", x)` (go1.26.5, 2026-07-25).
    #[test]
    fn go_sprint_float_matches_go_probe() {
        for (v, want) in [
            (5.0, "5"),
            (6.0, "6"),
            (0.0, "0"),
            (42.0, "42"),
            (0.5, "0.5"),
            (1234567.0, "1.234567e+06"),
            (999999.0, "999999"),
            (1e6, "1e+06"),
            (123456.75, "123456.75"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (-1.5, "-1.5"),
            (3.5e21, "3.5e+21"),
            (2.5e-7, "2.5e-07"),
            (1e21, "1e+21"),
        ] {
            assert_eq!(go_sprint_float(v), want, "v={v}");
        }
        assert_eq!(go_sprint_float(f64::NAN), "NaN");
        assert_eq!(go_sprint_float(f64::INFINITY), "+Inf");
        assert_eq!(go_sprint_float(f64::NEG_INFINITY), "-Inf");
        assert_eq!(go_sprint_float(-0.0), "-0");
    }

    /// Go builtin min/max float64 semantics (NaN dominates; contrast
    /// braille::math_min/math_max where infinities beat NaN).
    #[test]
    fn go_min_max_builtin_semantics() {
        assert!(go_min(f64::NAN, f64::NEG_INFINITY).is_nan());
        assert!(go_max(f64::NAN, f64::INFINITY).is_nan());
        assert_eq!(go_min(-1.0, 2.0), -1.0);
        assert_eq!(go_max(-1.0, 2.0), 2.0);
        assert!(go_min(-0.0, 0.0).is_sign_negative());
        assert!(go_max(-0.0, 0.0).is_sign_positive());
    }
}

/// Transliteration of `epochlinechart_multiseries_test.go`.
#[cfg(test)]
mod multiseries_tests {
    use super::*;
    use pretty_assertions::assert_eq;

    /// TestEpochLineChart_AddData_CreatesNewSeries.
    #[test]
    fn add_data_creates_new_series() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        assert_eq!(c.series_count(), 0);

        c.add_data(
            "series_a",
            MetricData {
                x: vec![0.0, 1.0],
                y: vec![1.0, 2.0],
            },
        );
        assert_eq!(c.series_count(), 1);

        c.add_data(
            "series_b",
            MetricData {
                x: vec![0.0, 1.0],
                y: vec![3.0, 4.0],
            },
        );
        assert_eq!(c.series_count(), 2);
    }

    /// TestEpochLineChart_AddData_AppendsToExistingSeries.
    #[test]
    fn add_data_appends_to_existing_series() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "series_a",
            MetricData {
                x: vec![0.0, 1.0],
                y: vec![1.0, 2.0],
            },
        );
        assert_eq!(c.series_count(), 1);

        c.add_data(
            "series_a",
            MetricData {
                x: vec![2.0, 3.0],
                y: vec![3.0, 4.0],
            },
        );
        assert_eq!(c.series_count(), 1);

        let (x_min, x_max, y_min, y_max) = c.test_bounds();
        assert!((x_min - 0.0).abs() <= 1e-9);
        assert!((x_max - 3.0).abs() <= 1e-9);
        assert!((y_min - 1.0).abs() <= 1e-9);
        assert!((y_max - 4.0).abs() <= 1e-9);
    }

    /// TestEpochLineChart_AddData_EmptyDataNoOp.
    #[test]
    fn add_data_empty_data_no_op() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "series_a",
            MetricData {
                x: vec![1.0],
                y: vec![10.0],
            },
        );
        assert_eq!(c.series_count(), 1);

        // Adding empty data should not change anything.
        c.add_data(
            "series_a",
            MetricData {
                x: vec![],
                y: vec![],
            },
        );
        assert_eq!(c.series_count(), 1);

        let (x_min, x_max, y_min, y_max) = c.test_bounds();
        assert!((x_min - 1.0).abs() <= 1e-9);
        assert!((x_max - 1.0).abs() <= 1e-9);
        assert!((y_min - 10.0).abs() <= 1e-9);
        assert!((y_max - 10.0).abs() <= 1e-9);
    }

    /// TestEpochLineChart_AddData_DrawOrder.
    #[test]
    fn add_data_draw_order() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "alpha",
            MetricData {
                x: vec![0.0],
                y: vec![1.0],
            },
        );
        c.add_data(
            "beta",
            MetricData {
                x: vec![0.0],
                y: vec![2.0],
            },
        );
        c.add_data(
            "gamma",
            MetricData {
                x: vec![0.0],
                y: vec![3.0],
            },
        );

        let order = c.draw_order();
        assert_eq!(order, vec!["alpha", "beta", "gamma"]);
    }

    /// TestEpochLineChart_Bounds_AggregatesAcrossSeries.
    #[test]
    fn bounds_aggregates_across_series() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        // Series A: X [0,10], Y [5,15]
        c.add_data(
            "A",
            MetricData {
                x: vec![0.0, 10.0],
                y: vec![5.0, 15.0],
            },
        );

        // Series B: X [5,20], Y [-10,20]
        c.add_data(
            "B",
            MetricData {
                x: vec![5.0, 20.0],
                y: vec![-10.0, 20.0],
            },
        );

        let (x_min, x_max, y_min, y_max) = c.test_bounds();
        assert!(
            (x_min - 0.0).abs() <= 1e-9,
            "xMin should be min of all series"
        );
        assert!(
            (x_max - 20.0).abs() <= 1e-9,
            "xMax should be max of all series"
        );
        assert!(
            (y_min - -10.0).abs() <= 1e-9,
            "yMin should be min of all series"
        );
        assert!(
            (y_max - 20.0).abs() <= 1e-9,
            "yMax should be max of all series"
        );
    }

    /// TestEpochLineChart_RemoveSeries_UpdatesBounds.
    #[test]
    fn remove_series_updates_bounds() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        // Series A: X [0,10], Y [0,10]
        c.add_data(
            "A",
            MetricData {
                x: vec![0.0, 10.0],
                y: vec![0.0, 10.0],
            },
        );

        // Series B: X [100,200], Y [100,200]
        c.add_data(
            "B",
            MetricData {
                x: vec![100.0, 200.0],
                y: vec![100.0, 200.0],
            },
        );

        assert_eq!(c.series_count(), 2);
        let (x_min, x_max, _, _) = c.test_bounds();
        assert!((x_min - 0.0).abs() <= 1e-9);
        assert!((x_max - 200.0).abs() <= 1e-9);

        // Remove series B; bounds should shrink back to A.
        c.remove_series("B");
        assert_eq!(c.series_count(), 1);

        let (x_min, x_max, y_min, y_max) = c.test_bounds();
        assert!((x_min - 0.0).abs() <= 1e-9);
        assert!((x_max - 10.0).abs() <= 1e-9);
        assert!((y_min - 0.0).abs() <= 1e-9);
        assert!((y_max - 10.0).abs() <= 1e-9);
    }

    /// TestEpochLineChart_RemoveSeries_UpdatesDrawOrder.
    #[test]
    fn remove_series_updates_draw_order() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "alpha",
            MetricData {
                x: vec![0.0],
                y: vec![1.0],
            },
        );
        c.add_data(
            "beta",
            MetricData {
                x: vec![0.0],
                y: vec![2.0],
            },
        );
        c.add_data(
            "gamma",
            MetricData {
                x: vec![0.0],
                y: vec![3.0],
            },
        );

        assert_eq!(c.draw_order(), vec!["alpha", "beta", "gamma"]);

        c.remove_series("beta");
        assert_eq!(c.draw_order(), vec!["alpha", "gamma"]);
    }

    /// TestEpochLineChart_RemoveSeries_NonExistent.
    #[test]
    fn remove_series_non_existent() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "A",
            MetricData {
                x: vec![1.0],
                y: vec![1.0],
            },
        );
        assert_eq!(c.series_count(), 1);

        // Removing a non-existent series should be a no-op.
        c.remove_series("nonexistent");
        assert_eq!(c.series_count(), 1);
        assert_eq!(c.draw_order(), vec!["A"]);
    }

    /// TestEpochLineChart_RemoveSeries_AllSeries.
    #[test]
    fn remove_series_all_series() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "A",
            MetricData {
                x: vec![1.0],
                y: vec![10.0],
            },
        );
        c.add_data(
            "B",
            MetricData {
                x: vec![2.0],
                y: vec![20.0],
            },
        );

        c.remove_series("A");
        c.remove_series("B");

        assert_eq!(c.series_count(), 0);
        assert!(c.draw_order().is_empty());

        let (x_min, x_max, y_min, y_max) = c.test_bounds();
        assert!(x_min == f64::INFINITY);
        assert!(x_max == f64::NEG_INFINITY);
        assert!(y_min == f64::INFINITY);
        assert!(y_max == f64::NEG_INFINITY);
    }

    /// TestEpochLineChart_RemoveSeries_ThenAddNewData.
    #[test]
    fn remove_series_then_add_new_data() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "A",
            MetricData {
                x: vec![0.0, 100.0],
                y: vec![0.0, 100.0],
            },
        );
        c.remove_series("A");

        // Add a new series with smaller bounds.
        c.add_data(
            "B",
            MetricData {
                x: vec![5.0, 10.0],
                y: vec![5.0, 10.0],
            },
        );

        let (x_min, x_max, y_min, y_max) = c.test_bounds();
        assert!((x_min - 5.0).abs() <= 1e-9);
        assert!((x_max - 10.0).abs() <= 1e-9);
        assert!((y_min - 5.0).abs() <= 1e-9);
        assert!((y_max - 10.0).abs() <= 1e-9);
    }

    /// TestEpochLineChart_PromoteSeriesToTop_MovesToEnd.
    #[test]
    fn promote_series_to_top_moves_to_end() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "A",
            MetricData {
                x: vec![0.0],
                y: vec![1.0],
            },
        );
        c.add_data(
            "B",
            MetricData {
                x: vec![0.0],
                y: vec![2.0],
            },
        );
        c.add_data(
            "C",
            MetricData {
                x: vec![0.0],
                y: vec![3.0],
            },
        );

        assert_eq!(c.draw_order(), vec!["A", "B", "C"]);

        // Promote A to top (end of draw order).
        c.promote_series_to_top("A");
        assert_eq!(c.draw_order(), vec!["B", "C", "A"]);
    }

    /// TestEpochLineChart_PromoteSeriesToTop_NonExistent.
    #[test]
    fn promote_series_to_top_non_existent() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        c.add_data(
            "A",
            MetricData {
                x: vec![0.0],
                y: vec![1.0],
            },
        );

        // Promoting a non-existent series should be a no-op.
        c.promote_series_to_top("nonexistent");
        assert_eq!(c.draw_order(), vec!["A"]);
    }

    /// TestEpochLineChart_PromoteSeriesToTop_EmptyChart.
    #[test]
    fn promote_series_to_top_empty_chart() {
        let mut c = EpochLineChart::new("multi");
        c.resize(100, 10);

        // Should not panic on empty chart.
        c.promote_series_to_top("A");
        assert_eq!(c.series_count(), 0);
    }

    /// TestEpochLineChart_MultiSeries_ViewRangeCoversAll.
    #[test]
    fn multi_series_view_range_covers_all() {
        let mut c = EpochLineChart::new("multi");
        c.resize(120, 12);

        // Series with different X ranges.
        c.add_data(
            "early",
            MetricData {
                x: vec![0.0, 5.0],
                y: vec![1.0, 1.0],
            },
        );
        c.add_data(
            "late",
            MetricData {
                x: vec![50.0, 100.0],
                y: vec![1.0, 1.0],
            },
        );

        // View should encompass all data, rounded to nice boundaries.
        assert!(c.view_min_x() <= 0.0);
        assert!(c.view_max_x() >= 100.0);
    }

    /// TestEpochLineChart_MultiSeries_DrawAfterRemove.
    #[test]
    fn multi_series_draw_after_remove() {
        let mut c = EpochLineChart::new("multi");
        c.resize(80, 12);

        c.add_data(
            "A",
            MetricData {
                x: vec![0.0, 10.0],
                y: vec![1.0, 5.0],
            },
        );
        c.add_data(
            "B",
            MetricData {
                x: vec![5.0, 15.0],
                y: vec![2.0, 4.0],
            },
        );
        c.draw();

        c.remove_series("A");

        // Go: require.NotPanics — a panic here fails the test.
        c.draw();
    }
}

/// Transliteration of `epochlinechart_overlay_test.go`.
///
/// Go's `ansiRE`/`stripANSI` helpers are unnecessary here:
/// `Canvas::text_rows` is already style-free.
#[cfg(test)]
mod overlay_tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn seed_xy(n: usize) -> MetricData {
        let mut xs = vec![0.0; n];
        let mut ys = vec![0.0; n];
        for i in 0..n {
            xs[i] = i as f64;
            ys[i] = (i + 1) as f64;
        }
        MetricData { x: xs, y: ys }
    }

    /// TestEpochLineChart_DrawInspectionOverlay_RendersHairlineAndLegend_RightSide.
    #[test]
    fn draw_inspection_overlay_renders_hairline_and_legend_right_side() {
        let m = "acc";
        let mut c = EpochLineChart::new(m);
        c.resize(80, 12);
        c.add_data(m, seed_xy(30));
        c.draw();

        // Inspect near X=5 -> expect legend to the right of the vertical
        // hairline.
        let want_x = 5.0;
        let px = ((want_x - c.view_min_x()) / (c.view_max_x() - c.view_min_x())
            * c.graph_width() as f64)
            .round() as i64;
        c.start_inspection(px);
        c.draw();

        let lines = c.canvas.text_rows();

        let label = "5: 6"; // y = x+1
        let mut found = false;
        for line in &lines {
            if line.contains(&format!("│▬▬ {label}")) {
                found = true;
                break;
            }
        }
        assert!(
            found,
            "expected hairline followed by legend on the right in the same row"
        );
    }

    /// TestInspectAtDataX_SnapsToNearestAndPixel.
    #[test]
    fn inspect_at_data_x_snaps_to_nearest_and_pixel() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(80, 12);

        // Non-uniform X to exercise nearest selection.
        let data = MetricData {
            x: vec![0.0, 2.0, 5.0, 9.0],
            y: vec![10.0, 20.0, 50.0, 90.0],
        };
        c.add_data(m, data);

        // Domain becomes [0,20] (niceMax), view = [0,20] initially.
        c.draw();

        // Target X=4 should snap to X=5 (nearest), then hairline snaps to
        // exact pixel for X=5.
        c.inspect_at_data_x(4.0);

        let (x, y, active) = c.inspection_data();
        assert!(active);
        assert!((x - 5.0).abs() <= 1e-9);
        assert!((y - 50.0).abs() <= 1e-9);

        let (px, ok) = c.test_inspection_mouse_x();
        assert!(ok);

        // Expected pixel for X=5
        let expect_px = ((5.0 - c.view_min_x()) / (c.view_max_x() - c.view_min_x())
            * c.graph_width() as f64)
            .round() as i64;
        assert_eq!(
            px, expect_px,
            "hairline should pixel-snap to the exact sample X"
        );
    }

    /// TestInspectAtDataX_NoData_NoActivate.
    #[test]
    fn inspect_at_data_x_no_data_no_activate() {
        let mut c = EpochLineChart::new("acc");
        c.resize(80, 12);
        // No data; should no-op
        c.inspect_at_data_x(1.0);
        let (_, _, active) = c.inspection_data();
        assert!(!active);
    }

    /// TestInspection_RepositionsOnXDomainExpansion.
    ///
    /// When new data expands the X domain (e.g., [0,20] -> [0,30]), the
    /// overlay should keep pointing at the same data X and move to the
    /// correct pixel.
    #[test]
    fn inspection_repositions_on_x_domain_expansion() {
        let m = "loss";
        let mut c = EpochLineChart::new(m);
        c.resize(120, 12);

        // Seed 0..19 so nice X domain is [0,20].
        let mut xs = vec![0.0; 20];
        let ys = vec![0.0; 20];
        for (i, x) in xs.iter_mut().enumerate() {
            *x = i as f64;
        }
        c.add_data(m, MetricData { x: xs, y: ys });
        assert!((c.view_max_x() - 20.0).abs() <= 1e-9);

        // Start inspecting at X=10 (middle of initial view).
        let want_x = 10.0;
        let start_px = ((want_x - c.view_min_x()) / (c.view_max_x() - c.view_min_x())
            * c.graph_width() as f64)
            .round() as i64;
        c.start_inspection(start_px);

        // Sanity: active and anchored to ~X=10.
        let (x0, _, active0) = c.inspection_data();
        assert!(active0);
        assert!((x0 - want_x).abs() <= 1e-9);
        let (old_px, _) = c.test_inspection_mouse_x();

        // Append 20..29 -> nice view should expand to [0,30].
        c.add_data(
            m,
            MetricData {
                x: vec![20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0],
                y: vec![0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            },
        );
        assert!((c.view_max_x() - 30.0).abs() <= 1e-9);

        // The overlay remains at the same DataX but moves to the new pixel.
        let (new_px, active1) = c.test_inspection_mouse_x();
        assert!(active1);
        let (x1, _, active1b) = c.inspection_data();
        assert!(active1b);
        assert!((x1 - want_x).abs() <= 1e-9);

        let expect_px = ((want_x - c.view_min_x()) / (c.view_max_x() - c.view_min_x())
            * c.graph_width() as f64)
            .round() as i64;
        assert_eq!(new_px, expect_px);
        assert!(
            new_px < old_px,
            "overlay should move left as view widens from 20 to 30"
        );
    }

    /// TestInspection_RepositionsOnResize.
    ///
    /// Resizing the chart should also keep the overlay anchored to the same
    /// DataX.
    #[test]
    fn inspection_repositions_on_resize() {
        let m = "acc";
        let mut c = EpochLineChart::new(m);
        c.resize(80, 12);

        // Seed 0..29 so nice X domain is [0,30].
        let mut xs = vec![0.0; 30];
        let ys = vec![0.0; 30];
        for (i, x) in xs.iter_mut().enumerate() {
            *x = i as f64;
        }
        c.add_data(m, MetricData { x: xs, y: ys });
        assert!((c.view_max_x() - 30.0).abs() <= 1e-9);

        let want_x = 15.0;
        let start_px = ((want_x - c.view_min_x()) / (c.view_max_x() - c.view_min_x())
            * c.graph_width() as f64)
            .round() as i64;
        c.start_inspection(start_px);
        let (old_px, _) = c.test_inspection_mouse_x();

        // Wider chart -> overlay should move proportionally to new width.
        c.resize(160, 12);

        let (new_px, active) = c.test_inspection_mouse_x();
        assert!(active);
        let (x, _, a) = c.inspection_data();
        assert!(a);
        assert!((x - want_x).abs() <= 1e-9);

        let expect_px = ((want_x - c.view_min_x()) / (c.view_max_x() - c.view_min_x())
            * c.graph_width() as f64)
            .round() as i64;
        assert_eq!(new_px, expect_px);
        assert!(
            new_px > old_px,
            "overlay should move right when width doubles"
        );
    }

    /// TestEpochLineChart_MultiSeries_InspectionUsesTopmostSeries.
    #[test]
    fn multi_series_inspection_uses_topmost_series() {
        let mut c = EpochLineChart::new("multi");
        c.resize(80, 12);

        // Series A: Y values are 100 at each X.
        c.add_data(
            "A",
            MetricData {
                x: vec![0.0, 5.0, 10.0],
                y: vec![100.0, 100.0, 100.0],
            },
        );
        // Series B: Y values are 200 at each X (added second = topmost).
        c.add_data(
            "B",
            MetricData {
                x: vec![0.0, 5.0, 10.0],
                y: vec![200.0, 200.0, 200.0],
            },
        );

        c.draw();
        c.inspect_at_data_x(5.0);

        let (_, y, active) = c.inspection_data();
        assert!(active);
        // Should inspect series B (topmost).
        assert!((y - 200.0).abs() <= 1e-9);
    }

    /// TestEpochLineChart_MultiSeries_InspectionAfterPromotion.
    #[test]
    fn multi_series_inspection_after_promotion() {
        let mut c = EpochLineChart::new("multi");
        c.resize(80, 12);

        c.add_data(
            "A",
            MetricData {
                x: vec![0.0, 5.0, 10.0],
                y: vec![100.0, 100.0, 100.0],
            },
        );
        c.add_data(
            "B",
            MetricData {
                x: vec![0.0, 5.0, 10.0],
                y: vec![200.0, 200.0, 200.0],
            },
        );

        // Promote A to top.
        c.promote_series_to_top("A");

        c.draw();
        c.inspect_at_data_x(5.0);

        let (_, y, active) = c.inspection_data();
        assert!(active);
        // Now A is topmost, so Y should be 100.
        assert!((y - 100.0).abs() <= 1e-9);
    }
}
