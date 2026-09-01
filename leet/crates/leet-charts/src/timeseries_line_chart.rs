//! Port of `core/internal/leet/timeserieslinechart.go`: the time-based
//! system metrics chart.
//!
//! Go embeds `*EpochLineChart`; the port composes an `epoch` field plus
//! `Deref`/`DerefMut` so promoted methods (`title`, `series_count`,
//! `start_inspection`, …) keep their call shape, and inherent methods here
//! shadow the embedded ones exactly where Go declares its own (`resize`,
//! `handle_zoom`, `set_y_scale`, `toggle_y_scale`, `park`).
//!
//! Go's constructor installs closures over the chart pointer for the X
//! label and inspection label formatters; the port routes them through
//! [`EpochLineChart`]'s `x_label_formatter_factory` hook and the
//! receiver-passing [`crate::epoch_line_chart::InspectionLabelFormatter`]
//! (see the epoch_line_chart.rs module docs).
//!
//! DIVERGENCE(TZ): axis and inspection timestamps render in UTC, not Go's
//! `.Local()`; see [`time_unix_utc`].

use std::collections::{HashMap, HashSet};
use std::ops::{Deref, DerefMut};
use std::rc::Rc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use leet_data::config::DEFAULT_SYSTEM_TAIL_WINDOW_MINS;
use leet_data::system_metrics::{DEFAULT_SYSTEM_METRIC_SERIES_NAME, MetricDef};
use leet_data::units::Unit;
use leet_data::width::text_width;

use crate::epoch_line_chart::{
    AxisScaleMode, EpochLineChart, MIN_ZOOM_RANGE, Series, SeriesStyle, go_max, go_min, is_finite,
    truncate_title,
};
use crate::styles::{AdaptiveColor, CHART_TITLE_HEIGHT};

/// Go: `minSystemMetricsRightPad = 2 * time.Second`.
const MIN_SYSTEM_METRICS_RIGHT_PAD: Duration = Duration::from_secs(2);
/// Go: `maxSystemMetricsRightPad = 10 * time.Second`.
const MAX_SYSTEM_METRICS_RIGHT_PAD: Duration = Duration::from_secs(10);
/// Go: `preferredSystemTimeLabelWidth = len("15:04")`.
const PREFERRED_SYSTEM_TIME_LABEL_WIDTH: i64 = "15:04".len() as i64;

/// Go: `func() AdaptiveColor` (colorProvider). `FnMut` because Go closures
/// mutate captured state (the workspace color cursor).
pub type ColorProvider = Box<dyn FnMut() -> AdaptiveColor>;

/// TimeSeriesLineChart is a time-based system metrics chart.
///
/// It reuses EpochLineChart's custom multi-series rendering and inspection
/// behavior while adding live-tail windowing semantics for timestamped data.
///
/// A single chart can contain multiple related series (for example GPU 0 / GPU 1).
/// By default the chart auto-trails the most recent data using tailWindow.
/// Users can zoom out to show the entire history; if the latest point remains
/// visible after a zoom operation, the view continues trailing live updates.
pub struct TimeSeriesLineChart {
    /// Go embeds `*EpochLineChart`; `Deref` promotes its methods.
    pub(crate) epoch: EpochLineChart,

    // PARITY: Go holds a shared `*MetricDef`; the chart never mutates it, so
    // an owned copy is equivalent.
    def: MetricDef,

    /// series tracks named (non-default) series for display purposes.
    // Go: map[string]struct{}; only its length reaches the screen.
    series: HashSet<String>,

    /// seriesColors stores the assigned color for each underlying series key.
    series_colors: HashMap<String, AdaptiveColor>,
    base_color: AdaptiveColor,

    /// colorProvider yields the next color for additional series on this chart.
    /// It is anchored to the chart's base color so multi-series colors are stable per chart.
    // PARITY: Go's nil func ports as None (see next_series_color).
    color_provider: Option<ColorProvider>,

    // PARITY: Go time.Duration is signed; std Duration is unsigned. Both
    // windows are non-negative everywhere in leet (config validation), and
    // the `<= 0` guards port as `== ZERO`.
    tail_window: Duration,
    view_window: Duration,

    view_initialized: bool,
    auto_trail: bool,
    show_all: bool,

    last_update: SystemTime,
    min_value: f64,
    max_value: f64,
}

impl Deref for TimeSeriesLineChart {
    type Target = EpochLineChart;

    fn deref(&self) -> &EpochLineChart {
        &self.epoch
    }
}

impl DerefMut for TimeSeriesLineChart {
    fn deref_mut(&mut self) -> &mut EpochLineChart {
        &mut self.epoch
    }
}

/// Go `TimeSeriesLineChartParams`.
pub struct TimeSeriesLineChartParams {
    pub width: i64,
    pub height: i64,
    pub def: MetricDef,
    pub base_color: AdaptiveColor,
    pub color_provider: Option<ColorProvider>,
    pub now: SystemTime,
}

impl TimeSeriesLineChart {
    /// Go `NewTimeSeriesLineChart`.
    pub fn new(params: TimeSeriesLineChartParams) -> TimeSeriesLineChart {
        // Go: time.Duration(DefaultSystemTailWindowMins) * time.Minute.
        let tail_window = Duration::from_secs(DEFAULT_SYSTEM_TAIL_WINDOW_MINS as u64 * 60);

        let mut base_chart = EpochLineChart::new(&params.def.title());
        // Go: baseChart.yTickFormatter = params.Def.Unit.Format (a bound
        // method value; Unit is Copy).
        let unit = params.def.unit;
        base_chart.set_y_tick_formatter(Rc::new(move |v| unit.format(v)));

        let mut chart = TimeSeriesLineChart {
            epoch: base_chart,
            def: params.def,
            series: HashSet::new(),
            series_colors: HashMap::new(),
            base_color: params.base_color,
            color_provider: params.color_provider,
            tail_window,
            view_window: tail_window,
            view_initialized: false,
            auto_trail: true,
            show_all: false,
            last_update: params.now,
            min_value: f64::INFINITY,
            max_value: f64::NEG_INFINITY,
        };

        // Go: chart.XLabelFormatter = func(_ int, v float64) string {
        //     return chart.formatXAxisTick(v, chart.maxXLabelWidth())
        // } — a closure over the chart pointer; ported as the draw-time
        // factory hook (see EpochLineChart::draw and XAxisTickView).
        chart.epoch.x_label_formatter_factory = Some(Box::new(|c: &EpochLineChart| {
            let view = XAxisTickView::capture(c);
            let max_width = c.max_x_label_width();
            Box::new(move |_i, v| view.format_x_axis_tick(v, max_width))
        }));

        // Go: chart.SetInspectionLabelFormatter(chart.formatInspectionLabel)
        // — a bound method; the port receives the chart back explicitly and
        // captures def.Unit by value (immutable after construction).
        let unit = chart.def.unit;
        chart.set_inspection_label_formatter(Some(Box::new(move |c, series_key, x, y| {
            format_inspection_label(c, unit, series_key, x, y)
        })));
        chart.resize(params.width, params.height);

        chart
    }

    /// SetTailWindow updates the default live tail window.
    pub fn set_tail_window(&mut self, window: Duration) {
        self.tail_window = window;
        if !self.view_initialized || self.auto_trail {
            self.view_window = window;
        }
        self.apply_ranges();
    }

    /// AddDataPoint adds a data point to this chart, creating series as needed.
    pub fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        let (series_key, created) = self.ensure_series(series_name);
        let point_time = go_time_unix(timestamp);
        self.last_update = point_time;

        if value < self.min_value {
            self.min_value = value;
        }
        if value > self.max_value {
            self.max_value = value;
        }

        self.add_point(&series_key, timestamp as f64, value);

        if created {
            // Go: lipgloss.NewStyle().Foreground(c.seriesColors[seriesKey]).
            let style = SeriesStyle {
                fg: self.series_colors[&series_key],
            };
            self.set_series_style(&series_key, style);
        }
        self.apply_ranges();
    }

    /// Park minimizes canvas memory for off-screen charts.
    pub fn park(&mut self) {
        self.epoch.park();
    }

    /// Resize updates the underlying chart size and reapplies the current view policy.
    pub fn resize(&mut self, width: i64, height: i64) {
        self.epoch.resize(width, height);
        self.apply_ranges();
    }

    /// HandleZoom updates the current time window and live-trailing state.
    pub fn handle_zoom(&mut self, direction: &str, mouse_x: i64) {
        self.epoch.handle_zoom(direction, mouse_x);
        self.view_initialized = true;
        self.reconcile_view_state();
    }

    /// SetYScale switches the Y-axis scaling mode while preserving the chart's
    /// time-window policy (live tail, frozen window, or full history).
    pub fn set_y_scale(&mut self, mode: AxisScaleMode) -> bool {
        if mode == AxisScaleMode::Log && !self.can_use_log_y() {
            return false;
        }
        if self.epoch.y_scale == mode {
            return false;
        }

        self.epoch.y_scale = mode;
        // Go's formatYTick closure read yScale live; the port re-captures it
        // (see the y_scale field note in epoch_line_chart.rs).
        self.epoch.install_y_label_formatter();
        self.apply_ranges();
        self.epoch.dirty = true;
        true
    }

    /// ToggleYScale toggles between linear and logarithmic Y scaling.
    pub fn toggle_y_scale(&mut self) -> bool {
        if self.is_log_y() {
            return self.set_y_scale(AxisScaleMode::Linear);
        }
        self.set_y_scale(AxisScaleMode::Log)
    }

    /// ViewModeLabel returns a short description of the current X-axis mode.
    // PARITY: Go additionally guards a nil receiver (returns ""), which is
    // unrepresentable here.
    pub fn view_mode_label(&self) -> String {
        if self.show_all {
            return "all history".to_string();
        }

        let mut window = self.view_window;
        // PARITY: Go checks window <= 0; negative is unrepresentable.
        if window == Duration::ZERO {
            window = self.tail_window;
        }
        let window = go_duration_round_second(window);

        if self.auto_trail {
            return format!("live tail {}", compact_duration(window));
        }
        format!("frozen {}", compact_duration(window))
    }

    /// TitleDetail returns the compact suffix rendered next to the chart title.
    pub fn title_detail(&self) -> String {
        if self.series.len() <= 1 {
            return String::new();
        }
        format!("[{}]", self.series.len())
    }

    /// GraphStartX returns the first graph column inside the rendered chart view.
    pub fn graph_start_x(&self) -> i64 {
        let mut start_x = 1;
        if self.y_step() > 0 {
            start_x += self.origin().x + 1;
        }
        start_x
    }

    /// GraphStartY returns the first graph row inside the rendered chart cell.
    pub fn graph_start_y(&self) -> i64 {
        1 + CHART_TITLE_HEIGHT
    }

    /// StartInspectionAt begins inspection at the given graph-local mouse position.
    pub fn start_inspection_at(&mut self, mouse_x: i64, _mouse_y: i64) {
        self.start_inspection(mouse_x);
    }

    /// UpdateInspectionAt moves the inspection cursor.
    pub fn update_inspection_at(&mut self, mouse_x: i64, _mouse_y: i64) {
        self.update_inspection(mouse_x);
    }

    /// SupportsHeatmap reports whether this chart can toggle into heatmap mode.
    pub fn supports_heatmap(&self) -> bool {
        false
    }

    /// ToggleHeatmapMode is unsupported for plain line charts.
    pub fn toggle_heatmap_mode(&mut self) -> bool {
        false
    }

    /// IsHeatmapMode reports whether the chart is currently rendering as a heatmap.
    pub fn is_heatmap_mode(&self) -> bool {
        false
    }

    /// LastUpdate returns the timestamp of the most recent sample seen.
    pub fn last_update(&self) -> SystemTime {
        self.last_update
    }

    /// ValueBounds returns the observed [min,max] values tracked for auto-ranging.
    pub fn value_bounds(&self) -> (f64, f64) {
        (self.min_value, self.max_value)
    }

    /// Go `ensureSeries` (returns `(seriesKey, created)`).
    fn ensure_series(&mut self, series_name: &str) -> (String, bool) {
        let mut series_key = series_name;
        if series_key.is_empty() {
            series_key = DEFAULT_SYSTEM_METRIC_SERIES_NAME;
        }
        if self.series_colors.contains_key(series_key) {
            return (series_key.to_string(), false);
        }

        let mut color = self.base_color;
        if !self.series_colors.is_empty() {
            color = self.next_series_color();
        }
        if series_key != DEFAULT_SYSTEM_METRIC_SERIES_NAME {
            self.series.insert(series_key.to_string());
        }
        self.series_colors.insert(series_key.to_string(), color);
        (series_key.to_string(), true)
    }

    /// Go `addPoint`.
    fn add_point(&mut self, series_key: &str, x: f64, y: f64) {
        if !self.epoch.data.contains_key(series_key) {
            let s = Series::new(series_key, &self.epoch.palette);
            self.epoch.data.insert(series_key.to_string(), s);
            self.epoch.order.push(series_key.to_string());
        }

        let s = self
            .epoch
            .data
            .get_mut(series_key)
            .expect("series was just ensured");
        s.add_point(x, y);
        // Go builtin min/max (NaN-propagating), extending the embedded
        // chart's bounds directly.
        self.epoch.x_min = go_min(self.epoch.x_min, x);
        self.epoch.x_max = go_max(self.epoch.x_max, x);
        self.epoch.y_min = go_min(self.epoch.y_min, y);
        self.epoch.y_max = go_max(self.epoch.y_max, y);
        self.epoch.dirty = true;
    }

    /// Go `nextSeriesColor`.
    fn next_series_color(&mut self) -> AdaptiveColor {
        // PARITY: Go checks c.colorProvider == nil.
        let Some(provider) = self.color_provider.as_mut() else {
            return self.base_color;
        };
        provider()
    }

    /// Go `applyRanges`.
    fn apply_ranges(&mut self) {
        if self.series_count() == 0 {
            return;
        }

        let data_min = self.epoch.x_min;
        let data_max = self.epoch.x_max;
        if !is_finite(data_min) || !is_finite(data_max) {
            return;
        }

        let (y_min, y_max) = self.compute_y_range();
        self.set_y_range(y_min, y_max);
        self.set_view_y_range(y_min, y_max);

        let mut domain_max = data_max + self.right_pad().as_secs_f64();
        if domain_max - data_min < MIN_ZOOM_RANGE {
            domain_max = data_min + MIN_ZOOM_RANGE;
        }
        self.set_x_range(data_min, domain_max);

        // Go: switch { case ... }.
        if self.show_all {
            self.set_view_x_range(data_min, domain_max);
            self.epoch.user_view_min_x = data_min;
            self.epoch.user_view_max_x = domain_max;
        } else if !self.view_initialized || self.auto_trail {
            let mut window = self.view_window.as_secs_f64();
            if !self.view_initialized || window <= 0.0 {
                window = self.tail_window.as_secs_f64();
            }
            if window < MIN_ZOOM_RANGE {
                window = MIN_ZOOM_RANGE;
            }
            self.snap_view_to_tail(window, data_min, domain_max);
            self.view_initialized = true;
        } else {
            self.clamp_user_view(data_min, domain_max);
        }

        // Go: c.SetXYRange(c.MinX(), c.MaxX(), yMin, yMax).
        let (min_x, max_x) = (self.min_x(), self.max_x());
        self.set_xy_range(min_x, max_x, y_min, y_max);
        if self.epoch.inspection.active {
            self.epoch.refresh_inspection_after_view_change();
        }
        self.epoch.dirty = true;
    }

    /// Go `computeYRange`.
    fn compute_y_range(&self) -> (f64, f64) {
        if self.is_log_y() {
            return self.compute_log_y_range();
        }

        if !self.def.auto_range
            || self.def.percentage
            || !is_finite(self.min_value)
            || !is_finite(self.max_value)
        {
            return (self.def.min_y, self.def.max_y);
        }

        let mut value_range = self.max_value - self.min_value;
        if value_range == 0.0 {
            value_range = self.max_value.abs() * 0.1;
            if value_range == 0.0 {
                value_range = 1.0;
            }
        }
        let padding = value_range * 0.1;

        let mut new_min_y = self.min_value - padding;
        let new_max_y = self.max_value + padding;
        if self.min_value >= 0.0 && new_min_y < 0.0 {
            new_min_y = 0.0;
        }
        (new_min_y, new_max_y)
    }

    /// Go `computeLogYRange`.
    fn compute_log_y_range(&self) -> (f64, f64) {
        if (!self.def.auto_range || self.def.percentage)
            && self.def.min_y > 0.0
            && self.def.max_y > self.def.min_y
        {
            return self.calculate_log_range(self.def.min_y, self.def.max_y);
        }

        let Some((min_positive, max_positive)) = self.positive_y_bounds() else {
            return (self.def.min_y, self.def.max_y);
        };
        self.calculate_log_range(min_positive, max_positive)
    }

    /// Go `rightPad`.
    fn right_pad(&self) -> Duration {
        // Go: min(max(c.tailWindow/60, minSystemMetricsRightPad),
        // maxSystemMetricsRightPad) — builtin min/max over Duration (int64
        // nanoseconds); Duration/60 divides the nanosecond count.
        (self.tail_window / 60)
            .max(MIN_SYSTEM_METRICS_RIGHT_PAD)
            .min(MAX_SYSTEM_METRICS_RIGHT_PAD)
    }

    /// Go `snapViewToTail`.
    fn snap_view_to_tail(&mut self, window: f64, data_min: f64, domain_max: f64) {
        let mut window = window;
        if window <= 0.0 {
            window = go_max(self.tail_window.as_secs_f64(), MIN_ZOOM_RANGE);
        }
        let view_max = domain_max;
        let view_min = go_max(view_max - window, data_min);
        self.set_view_x_range(view_min, view_max);
        self.epoch.user_view_min_x = view_min;
        self.epoch.user_view_max_x = view_max;
    }

    /// Go `clampUserView`.
    fn clamp_user_view(&mut self, data_min: f64, domain_max: f64) {
        let mut view_min = self.epoch.user_view_min_x;
        let mut view_max = self.epoch.user_view_max_x;
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            self.auto_trail = true;
            let mut window = self.view_window.as_secs_f64();
            if window <= 0.0 {
                window = self.tail_window.as_secs_f64();
            }
            self.snap_view_to_tail(window, data_min, domain_max);
            return;
        }

        if view_min < data_min {
            view_max += data_min - view_min;
            view_min = data_min;
        }
        if view_max > domain_max {
            view_min -= view_max - domain_max;
            view_max = domain_max;
            if view_min < data_min {
                view_min = data_min;
            }
        }

        self.set_view_x_range(view_min, view_max);
        self.epoch.user_view_min_x = view_min;
        self.epoch.user_view_max_x = view_max;
    }

    /// Go `reconcileViewState`.
    fn reconcile_view_state(&mut self) {
        if self.series_count() == 0 {
            return;
        }

        let data_min = self.epoch.x_min;
        let data_max = self.epoch.x_max;
        if !is_finite(data_min) || !is_finite(data_max) {
            return;
        }

        let view_min = self.view_min_x();
        let view_max = self.view_max_x();
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            return;
        }

        let eps = go_max(self.pixel_eps_x(view_range) * 2.0, 1.0);
        let full_range = self.max_x() - data_min;

        self.show_all = full_range > 0.0 && view_range >= full_range - eps;
        self.auto_trail = view_max >= data_max - eps;
        if self.show_all {
            self.auto_trail = true;
        }

        // Go: c.viewWindow = time.Duration(math.Round(viewRange)) *
        // time.Second (view_range > 0 here, so the u64 cast is exact; the
        // nanosecond multiply cannot overflow for representable views).
        self.view_window = Duration::from_secs(view_range.round() as u64);
        if self.view_window < Duration::from_secs(MIN_ZOOM_RANGE as u64) {
            self.view_window = Duration::from_secs(MIN_ZOOM_RANGE as u64);
        }

        if self.show_all {
            self.epoch.user_view_min_x = data_min;
            self.epoch.user_view_max_x = self.max_x();
            return;
        }
        if self.auto_trail {
            let max_x = self.max_x();
            self.snap_view_to_tail(view_range, data_min, max_x);
            return;
        }

        self.epoch.user_view_min_x = self.view_min_x();
        self.epoch.user_view_max_x = self.view_max_x();
    }

    /// Go `formatXAxisTick`.
    // Parity surface: rendering goes through the factory installed in new()
    // (as in Go); outside tests nothing calls the method form directly.
    #[allow(dead_code)]
    fn format_x_axis_tick(&self, v: f64, max_width: i64) -> String {
        XAxisTickView::capture(&self.epoch).format_x_axis_tick(v, max_width)
    }
}

/// The chart state Go's `formatXAxisTick` / `shouldUseEndpointLabels` /
/// `isEndpointTick` / `endpointXLabelWidth` (timeserieslinechart.go:455-509)
/// read live through the chart pointer. Captured when the X label formatter
/// is bound — at draw time, when geometry and view are fixed — mirroring
/// epoch's max_x_label_width capture.
#[derive(Debug, Clone, Copy)]
struct XAxisTickView {
    view_min_x: f64,
    view_max_x: f64,
    graph_width: i64,
    x_step: i64,
}

impl XAxisTickView {
    fn capture(c: &EpochLineChart) -> XAxisTickView {
        XAxisTickView {
            view_min_x: c.view_min_x(),
            view_max_x: c.view_max_x(),
            graph_width: c.graph_width(),
            x_step: c.x_step(),
        }
    }

    /// Go `formatXAxisTick`.
    fn format_x_axis_tick(&self, v: f64, max_width: i64) -> String {
        if !is_finite(v) {
            return String::new();
        }

        // Go: time.Unix(int64(math.Round(v)), 0).Local() — v is finite;
        // Rust's saturating float→int cast matches for every realistic
        // timestamp. DIVERGENCE(TZ): see time_unix_utc.
        let ts = time_unix_utc(v.round() as i64);
        // Go: time.Duration(math.Round(...)) * time.Second, as whole seconds.
        let span = (self.view_max_x - self.view_min_x).round() as i64;
        let layouts = system_time_layouts(span);

        let mut max_width = max_width;
        if self.should_use_endpoint_labels(max_width) {
            if !self.is_endpoint_tick(v) {
                return String::new();
            }
            max_width = self.endpoint_x_label_width();
        }
        if max_width <= 0 {
            max_width = PREFERRED_SYSTEM_TIME_LABEL_WIDTH;
        }

        fit_time_layouts(&ts, max_width, layouts)
    }

    /// Go `shouldUseEndpointLabels`.
    fn should_use_endpoint_labels(&self, max_width: i64) -> bool {
        max_width > 0
            && max_width < PREFERRED_SYSTEM_TIME_LABEL_WIDTH
            && self.endpoint_x_label_width() > 0
    }

    /// Go `endpointXLabelWidth`.
    fn endpoint_x_label_width(&self) -> i64 {
        if self.graph_width <= 0 {
            return 0;
        }
        // Go: max(c.GraphWidth()/2, 1).
        (self.graph_width / 2).max(1)
    }

    /// Go `isEndpointTick`.
    fn is_endpoint_tick(&self, v: f64) -> bool {
        let view_min = self.view_min_x;
        let view_max = self.view_max_x;
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            return true;
        }

        let eps = go_max(
            self.pixel_eps_x(view_range) * 2.0,
            view_range / self.x_step.max(1) as f64 * 0.25,
        );
        (v - view_min).abs() <= eps || (v - view_max).abs() <= eps
    }

    /// Go calls the embedded EpochLineChart's `pixelEpsX`; same body over
    /// the captured geometry.
    fn pixel_eps_x(&self, x_range: f64) -> f64 {
        if self.graph_width <= 0 || x_range <= 0.0 {
            return 0.0;
        }
        x_range / self.graph_width as f64
    }
}

/// Go `systemTimeLayouts`. `span` is whole seconds (both call sites build it
/// via `time.Duration(math.Round(...)) * time.Second`); i64 keeps Go's
/// signed-duration comparison semantics.
pub(crate) fn system_time_layouts(span: i64) -> &'static [&'static str] {
    // Go: span >= 48*time.Hour / span >= time.Hour.
    if span >= 48 * 3600 {
        &["Jan 2 15:04", "Jan 2", "01/02", "0102"]
    } else if span >= 3600 {
        &["15:04", "1504"]
    } else {
        &["15:04:05", "15:04", "1504"]
    }
}

/// Go `formatInspectionLabel` — a TimeSeriesLineChart method over the chart
/// pointer; the port receives the embedded chart explicitly (via the
/// receiver-passing InspectionLabelFormatter) and `unit` is the captured
/// `def.Unit`.
fn format_inspection_label(
    c: &EpochLineChart,
    unit: Unit,
    series_key: &str,
    x: f64,
    y: f64,
) -> String {
    // Go: time.Unix(int64(math.Round(x)), 0).Local(). DIVERGENCE(TZ): see
    // time_unix_utc.
    let ts = time_unix_utc(x.round() as i64);
    // Go: time.Duration(math.Round(...)) * time.Second, as whole seconds.
    let span = (c.view_max_x() - c.view_min_x()).round() as i64;
    let mut layout = "15:04:05";
    if span >= 48 * 3600 {
        layout = "Jan 2 15:04:05";
    }

    let label = format!("{} {}", go_time_format(&ts, layout), unit.format(y));
    if series_key.is_empty() || series_key == DEFAULT_SYSTEM_METRIC_SERIES_NAME {
        return label;
    }
    format!("{}: {}", series_key, label)
}

/// Go `fitTimeLayouts`.
pub(crate) fn fit_time_layouts(ts: &GoTime, max_width: i64, layouts: &[&str]) -> String {
    for layout in layouts {
        let formatted = go_time_format(ts, layout);
        if text_width(&formatted) as i64 <= max_width {
            return formatted;
        }
    }

    let formatted = go_time_format(ts, layouts[layouts.len() - 1]);
    if text_width(&formatted) as i64 <= max_width {
        return formatted;
    }
    truncate_title(&formatted, max_width)
}

/// Go `compactDuration`.
pub(crate) fn compact_duration(d: Duration) -> String {
    let d = go_duration_round_second(d);
    // PARITY: Go returns "0s" for d <= 0; negative is unrepresentable here.
    if d == Duration::ZERO {
        return "0s".to_string();
    }
    // d is second-granular after rounding; Go's Duration/Duration divisions
    // and remainders below port to whole-second arithmetic.
    let secs = d.as_secs();

    // Go: d % time.Hour == 0.
    if secs.is_multiple_of(3600) {
        return format!("{}h", secs / 3600);
    }
    // Go: d >= time.Hour.
    if secs >= 3600 {
        let hours = secs / 3600;
        let minutes = (secs % 3600) / 60;
        // PARITY: sub-minute remainders are dropped ("2h" for 2h30s).
        if minutes == 0 {
            return format!("{}h", hours);
        }
        return format!("{}h{}m", hours, minutes);
    }
    // Go: d % time.Minute == 0.
    if secs.is_multiple_of(60) {
        return format!("{}m", secs / 60);
    }
    // Go: d >= time.Minute.
    if secs >= 60 {
        let minutes = secs / 60;
        let seconds = secs % 60;
        if seconds == 0 {
            return format!("{}m", minutes);
        }
        return format!("{}m{}s", minutes, seconds);
    }
    format!("{}s", secs)
}

// ---------------------------------------------------------------------------
// Go time.Time / time.Duration support (the subset these layouts need).
// ---------------------------------------------------------------------------

/// Go `time.Unix(sec, 0)` — SystemTime relative to the epoch (pre-epoch
/// timestamps map below UNIX_EPOCH).
fn go_time_unix(sec: i64) -> SystemTime {
    if sec >= 0 {
        UNIX_EPOCH + Duration::from_secs(sec as u64)
    } else {
        UNIX_EPOCH - Duration::from_secs(sec.unsigned_abs())
    }
}

/// Go `Duration.Round(time.Second)`: nearest multiple of a second, halves
/// away from zero. (Go's overflow saturation is unreachable for leet's
/// windows; negative durations are unrepresentable in std Duration.)
fn go_duration_round_second(d: Duration) -> Duration {
    let nanos = d.subsec_nanos();
    if nanos * 2 < 1_000_000_000 {
        Duration::from_secs(d.as_secs())
    } else {
        Duration::from_secs(d.as_secs() + 1)
    }
}

/// Go `time.Month` abbreviations (the "Jan" layout token).
const SHORT_MONTH_NAMES: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/// Broken-down UTC time for the fixed layouts this module renders (no
/// layout uses a year token).
#[derive(Debug, Clone, Copy)]
pub(crate) struct GoTime {
    month: u32, // 1-12
    day: u32,   // 1-31
    hour: u32,
    minute: u32,
    second: u32,
}

/// Go `time.Unix(sec, 0).Local()` broken down for [`go_time_format`].
///
/// DIVERGENCE(TZ): rendered in UTC, not local time — the same divergence,
/// rationale, and harness contract as leet-tui's console timestamps
/// (run_console_logs.rs): std has no local-time API, the workspace denies
/// unsafe_code (no libc localtime_r FFI), and a tz-database crate is a
/// workspace-level Cargo decision outside this unit. Go under TZ="" behaves
/// identically, so the harness pins the oracle to TZ=UTC
/// (harness/leet-harness/src/pty.rs). Recorded in docs/PARITY.md (the row
/// amending CH-14, signed off 2026-07-25); revisit if a tz crate is adopted.
pub(crate) fn time_unix_utc(sec: i64) -> GoTime {
    let days = sec.div_euclid(86_400);
    let sod = sec.rem_euclid(86_400);

    // Days-since-epoch → civil date (Howard Hinnant's civil_from_days;
    // agrees with Go time.Time.Date's absDate over the full range used).
    let z = days + 719_468;
    let era = (if z >= 0 { z } else { z - 146_096 }) / 146_097;
    let doe = z - era * 146_097; // [0, 146096]
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let month = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32; // [1, 12]

    GoTime {
        month,
        day,
        hour: (sod / 3_600) as u32,
        minute: ((sod % 3_600) / 60) as u32,
        second: (sod % 60) as u32,
    }
}

/// Go `time.Time.Format` for the fixed layouts used by the system-metric
/// charts. Reference-time tokens: "15"→padded 24h hour, "04"→padded minute,
/// "05"→padded second, "Jan"→month name, "2"→unpadded day, "01"→padded
/// month, "02"→padded day.
pub(crate) fn go_time_format(t: &GoTime, layout: &str) -> String {
    let mon = SHORT_MONTH_NAMES[(t.month - 1) as usize];
    match layout {
        "15:04" => format!("{:02}:{:02}", t.hour, t.minute),
        "1504" => format!("{:02}{:02}", t.hour, t.minute),
        "15:04:05" => format!("{:02}:{:02}:{:02}", t.hour, t.minute, t.second),
        "Jan 2" => format!("{} {}", mon, t.day),
        "Jan 2 15:04" => format!("{} {} {:02}:{:02}", mon, t.day, t.hour, t.minute),
        "Jan 2 15:04:05" => format!(
            "{} {} {:02}:{:02}:{:02}",
            mon, t.day, t.hour, t.minute, t.second
        ),
        "01/02" => format!("{:02}/{:02}", t.month, t.day),
        "0102" => format!("{:02}{:02}", t.month, t.day),
        // Every layout this module renders is enumerated above.
        _ => unreachable!("unsupported Go time layout {layout:?}"),
    }
}

// ---------------------------------------------------------------------------
// testhelpers.go accessors (TimeSeriesLineChart subset), pub(crate) per
// PORTING.md's testing conventions.
// ---------------------------------------------------------------------------

#[cfg(test)]
impl TimeSeriesLineChart {
    /// testhelpers.go `TestSeriesCount`: the number of named (non-default)
    /// series in the chart.
    pub(crate) fn test_series_count(&self) -> usize {
        self.series.len()
    }

    /// testhelpers.go `TestSeriesColor`: the configured color for a series
    /// key.
    // PARITY: Go's map read yields the zero AdaptiveColor (empty color
    // strings) for a missing key; the port's zero is black. Unreachable in
    // the ported tests (they only query existing keys).
    pub(crate) fn test_series_color(&self, key: &str) -> AdaptiveColor {
        self.series_colors
            .get(key)
            .copied()
            .unwrap_or(AdaptiveColor {
                light: crate::styles::Rgb(0, 0, 0),
                dark: crate::styles::Rgb(0, 0, 0),
            })
    }

    /// testhelpers.go `TestViewRange`: the current X view range.
    pub(crate) fn test_view_range(&self) -> (f64, f64) {
        (self.view_min_x(), self.view_max_x())
    }

    /// testhelpers.go `TestAutoTrail`: whether the chart is currently
    /// auto-trailing live updates.
    pub(crate) fn test_auto_trail(&self) -> bool {
        self.auto_trail
    }

    /// testhelpers.go `TestShowAll`: whether the chart is currently showing
    /// the full history.
    pub(crate) fn test_show_all(&self) -> bool {
        self.show_all
    }

    /// testhelpers.go `TestFormatXAxisTick`: exposes system-metric X tick
    /// formatting for focused tests.
    pub(crate) fn test_format_x_axis_tick(&self, v: f64, max_width: i64) -> String {
        self.format_x_axis_tick(v, max_width)
    }
}

/// Transliteration of `timeserieslinechart_test.go`.
#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    use leet_data::system_metrics::MetricChartKind;
    use leet_data::units::{UNIT_GIB, UNIT_MHZ, UNIT_PERCENT};

    use crate::styles::{MIN_METRIC_CHART_WIDTH, Rgb, parse_hex_color};

    /// Go `leet.AdaptiveColor{Light: lipgloss.Color(c), Dark: lipgloss.Color(c)}`.
    fn adaptive(c: &str) -> AdaptiveColor {
        let rgb = parse_hex_color(c).expect("test hex color");
        AdaptiveColor {
            light: rgb,
            dark: rgb,
        }
    }

    /// stubColorProvider returns deterministic colors for series creation order.
    pub(super) fn stub_color_provider(colors: &[&str]) -> ColorProvider {
        let colors: Vec<AdaptiveColor> = colors.iter().map(|c| adaptive(c)).collect();
        let mut i = 0usize;
        Box::new(move || {
            if colors.is_empty() {
                // Go: leet.AdaptiveColor{} (zero value).
                return AdaptiveColor {
                    light: Rgb(0, 0, 0),
                    dark: Rgb(0, 0, 0),
                };
            }
            let c = colors[i % colors.len()];
            i += 1;
            c
        })
    }

    /// Go: require.Regexp(t, `^\d{2}:?\d{2}$`, s) — hand-rolled (this crate
    /// carries no regex dev-dependency).
    fn matches_hh_mm(s: &str) -> bool {
        let b: Vec<char> = s.chars().collect();
        match b.len() {
            4 => b.iter().all(char::is_ascii_digit),
            5 => {
                b[0].is_ascii_digit()
                    && b[1].is_ascii_digit()
                    && b[2] == ':'
                    && b[3].is_ascii_digit()
                    && b[4].is_ascii_digit()
            }
            _ => false,
        }
    }

    /// TestNewTimeSeriesLineChart_ConstructsAndInitializes.
    #[test]
    fn new_time_series_line_chart_constructs_and_initializes() {
        let def = MetricDef {
            name: "CPU".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            auto_range: true,
            percentage: false,
            // Go literal zero values.
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let now = UNIX_EPOCH + Duration::from_secs(1_700_000_000);

        let ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 20,
            def,
            // base color
            base_color: adaptive("#FF00FF"),
            // provider for subsequent series
            color_provider: Some(stub_color_provider(&["#00FF00"])),
            now,
        });

        assert_eq!(ch.title(), "CPU (%)");
        assert_eq!(ch.last_update(), now, "constructor sets last update to now");

        let (minimum, maximum) = ch.value_bounds();
        assert!(minimum == f64::INFINITY);
        assert!(maximum == f64::NEG_INFINITY);
    }

    /// TestAddDataPoint_DefaultSeries_BookKeeping.
    #[test]
    fn add_data_point_default_series_book_keeping() {
        let def = MetricDef {
            name: "Mem".to_string(),
            unit: UNIT_GIB,
            min_y: 0.0,
            max_y: 64.0,
            auto_range: true,
            percentage: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let now_secs: i64 = 1_700_000_000;
        let now = UNIX_EPOCH + Duration::from_secs(now_secs as u64);
        let mut ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 20,
            def,
            base_color: adaptive("#ABCDEF"),
            color_provider: Some(stub_color_provider(&[])),
            now,
        });

        // First point
        let ts1 = now_secs - 5 * 60; // now.Add(-5 * time.Minute).Unix()
        let val1 = 12.5;
        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, ts1, val1);

        assert_eq!(
            ch.last_update(),
            UNIX_EPOCH + Duration::from_secs(ts1 as u64)
        );

        let (minimum, maximum) = ch.value_bounds();
        assert_eq!(minimum, val1);
        assert_eq!(maximum, val1);
        assert_eq!(
            ch.test_series_count(),
            0,
            "Default dataset should not create a named series"
        );

        // Lower value adjusts min only
        let ts2 = ts1 + 5;
        let val2 = 10.0;
        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, ts2, val2);
        let (minimum, maximum) = ch.value_bounds();
        assert_eq!(minimum, val2);
        assert_eq!(maximum, val1);

        // Higher value adjusts max only
        let ts3 = ts2 + 5;
        let val3 = 20.0;
        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, ts3, val3);
        let (minimum, maximum) = ch.value_bounds();
        assert_eq!(minimum, val2);
        assert_eq!(maximum, val3);
        assert_eq!(
            ch.last_update(),
            UNIX_EPOCH + Duration::from_secs(ts3 as u64)
        );
    }

    /// TestAddDataPoint_NamedSeries_CreatesSeriesOnDemand.
    #[test]
    fn add_data_point_named_series_creates_series_on_demand() {
        let def = MetricDef {
            name: "CPU".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            auto_range: true,
            percentage: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let now_secs: i64 = 1_700_000_000;
        let now = UNIX_EPOCH + Duration::from_secs(now_secs as u64);
        let mut ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 20,
            def,
            base_color: adaptive("#FF00FF"),
            color_provider: Some(stub_color_provider(&["#00FF00", "#0000FF"])),
            now,
        });

        let ts = now_secs;
        ch.add_data_point("cpu0", ts, 30.0);
        assert_eq!(
            ch.test_series_count(),
            1,
            "first named series should be created"
        );

        ch.add_data_point("cpu1", ts + 1, 70.0);
        assert_eq!(
            ch.test_series_count(),
            2,
            "second named series should be created"
        );

        // Adding to an existing series should not create more
        ch.add_data_point("cpu0", ts + 2, 15.0);
        assert_eq!(
            ch.test_series_count(),
            2,
            "reusing series must not change count"
        );

        // Bounds track across all series
        let (minimum, maximum) = ch.value_bounds();
        assert_eq!(minimum, 15.0);
        assert_eq!(maximum, 70.0);
    }

    /// TestDefaultAndNamedSeries_GetDistinctColors.
    #[test]
    fn default_and_named_series_get_distinct_colors() {
        let def = MetricDef {
            name: "CPU".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            auto_range: true,
            percentage: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let now_secs: i64 = 1_700_000_000;
        let now = UNIX_EPOCH + Duration::from_secs(now_secs as u64);
        let base_color = adaptive("#FF00FF");
        let next_color = adaptive("#00FF00");
        let mut ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 20,
            def,
            base_color,
            color_provider: Some(stub_color_provider(&["#00FF00"])),
            now,
        });

        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, now_secs, 30.0);
        ch.add_data_point("cpu0", now_secs + 1, 70.0);

        assert_eq!(ch.series_count(), 2);
        assert_eq!(
            ch.test_series_count(),
            1,
            "only named series should count here"
        );
        assert_eq!(
            ch.test_series_color(DEFAULT_SYSTEM_METRIC_SERIES_NAME),
            base_color
        );
        assert_eq!(ch.test_series_color("cpu0"), next_color);
    }

    /// TestFormatXAxisTick_NarrowSystemChartsKeepEndpointLabels.
    #[test]
    fn format_x_axis_tick_narrow_system_charts_keep_endpoint_labels() {
        let def = MetricDef {
            name: "Apple E-cores Freq".to_string(),
            unit: UNIT_MHZ,
            min_y: 0.0,
            max_y: 3000.0,
            auto_range: true,
            percentage: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let now_secs: i64 = 1_700_000_000;
        let now = UNIX_EPOCH + Duration::from_secs(now_secs as u64);
        let mut ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: MIN_METRIC_CHART_WIDTH,
            height: 8,
            def,
            base_color: adaptive("#FF00FF"),
            color_provider: Some(stub_color_provider(&["#00FF00"])),
            now,
        });

        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, now_secs - 10 * 60, 990.0);
        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, now_secs, 1100.0);

        let (view_min, view_max) = ch.test_view_range();
        let mid = (view_min + view_max) / 2.0;

        assert!(
            ch.test_format_x_axis_tick(mid, 3).is_empty(),
            "narrow charts should suppress interior labels"
        );

        let left = ch.test_format_x_axis_tick(view_min, 3);
        let right = ch.test_format_x_axis_tick(view_max, 3);
        assert!(!left.is_empty());
        assert!(!right.is_empty());
        assert_ne!(left, "...");
        assert_ne!(right, "...");
        assert!(matches_hh_mm(&left), "left = {left:?}");
        assert!(matches_hh_mm(&right), "right = {right:?}");
    }

    /// TestFormatXAxisTick_WideSystemChartsKeepInteriorLabels.
    #[test]
    fn format_x_axis_tick_wide_system_charts_keep_interior_labels() {
        let def = MetricDef {
            name: "CPU".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            auto_range: true,
            percentage: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let now_secs: i64 = 1_700_000_000;
        let now = UNIX_EPOCH + Duration::from_secs(now_secs as u64);
        let mut ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 12,
            def,
            base_color: adaptive("#FF00FF"),
            color_provider: Some(stub_color_provider(&["#00FF00"])),
            now,
        });

        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, now_secs - 10 * 60, 10.0);
        ch.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, now_secs, 20.0);

        let (view_min, view_max) = ch.test_view_range();
        let mid = (view_min + view_max) / 2.0;

        let label = ch.test_format_x_axis_tick(mid, 6);
        assert!(!label.is_empty());
        assert_ne!(label, "...");
        assert!(matches_hh_mm(&label), "label = {label:?}");
    }

    /// TestTimeSeriesLineChart_LogY_FormatsTicksWithMetricUnits
    /// (epochlinechart_test.go:381; transliterated here because it exercises
    /// TimeSeriesLineChart — see the epoch_line_chart.rs tests doc).
    #[test]
    fn time_series_line_chart_log_y_formats_ticks_with_metric_units() {
        let def = MetricDef {
            name: "CPU".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            auto_range: true,
            percentage: true,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };

        let mut ch = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 20,
            def,
            base_color: adaptive("#FF00FF"),
            color_provider: Some(stub_color_provider(&["#00FF00"])),
            now: UNIX_EPOCH + Duration::from_secs(1_700_000_000),
        });

        ch.add_data_point("", 1, 0.1);
        ch.add_data_point("", 2, 10.0);

        assert!(ch.toggle_y_scale());
        assert!(ch.test_is_log_y());
        assert_eq!(ch.test_format_y_tick(1.0), "10%");
    }

    // ----- Port-only anchors (not in the Go test files) ---------------------

    /// Anchors the Go time-layout port against Go-formatted probes
    /// (`time.Unix(sec, 0).UTC().Format(layout)`).
    #[test]
    fn go_time_format_matches_go_probe() {
        // 2023-11-14 22:13:20 UTC.
        let t = time_unix_utc(1_700_000_000);
        assert_eq!(go_time_format(&t, "15:04"), "22:13");
        assert_eq!(go_time_format(&t, "1504"), "2213");
        assert_eq!(go_time_format(&t, "15:04:05"), "22:13:20");
        assert_eq!(go_time_format(&t, "Jan 2"), "Nov 14");
        assert_eq!(go_time_format(&t, "Jan 2 15:04"), "Nov 14 22:13");
        assert_eq!(go_time_format(&t, "Jan 2 15:04:05"), "Nov 14 22:13:20");
        assert_eq!(go_time_format(&t, "01/02"), "11/14");
        assert_eq!(go_time_format(&t, "0102"), "1114");

        // The epoch: 1970-01-01 00:00:00 UTC (unpadded day token).
        let t = time_unix_utc(0);
        assert_eq!(go_time_format(&t, "Jan 2 15:04:05"), "Jan 1 00:00:00");
        assert_eq!(go_time_format(&t, "01/02"), "01/01");

        // Leap day: 2000-02-29 23:42:02 UTC.
        let t = time_unix_utc(951_867_722);
        assert_eq!(go_time_format(&t, "Jan 2 15:04:05"), "Feb 29 23:42:02");

        // Pre-epoch: 1969-12-31 23:59:59 UTC.
        let t = time_unix_utc(-1);
        assert_eq!(go_time_format(&t, "Jan 2 15:04:05"), "Dec 31 23:59:59");
    }

    /// Anchors compactDuration against Go behavior (including the "2h for
    /// 2h30s" remainder-dropping quirk).
    #[test]
    fn compact_duration_matches_go() {
        let cases: &[(u64, &str)] = &[
            (0, "0s"),
            (30, "30s"),
            (59, "59s"),
            (60, "1m"),
            (90, "1m30s"),
            (600, "10m"),
            (3600, "1h"),
            (3630, "1h"), // minutes == 0 quirk: sub-minute remainder dropped
            (3660, "1h1m"),
            (7200, "2h"),
            (7290, "2h1m"),
            (86400, "24h"),
        ];
        for &(secs, want) in cases {
            assert_eq!(
                compact_duration(Duration::from_secs(secs)),
                want,
                "secs={secs}"
            );
        }
        // Round-to-second: halves away from zero.
        assert_eq!(compact_duration(Duration::from_millis(59_500)), "1m");
        assert_eq!(compact_duration(Duration::from_millis(59_499)), "59s");
    }
}

/// Transliteration of `timeserieslinechart_zoom_test.go`.
///
/// TestSystemMetricsGrid_MultiSeriesInspectionUsesTopmostSeries and
/// TestSystemMetricsGrid_Inspection_Synchronized (plus their
/// computeSystemAdjustedX helper) exercise `SystemMetricsGrid` and
/// transliterate with leet-tui's `system_metrics_grid` module port.
#[cfg(test)]
mod zoom_tests {
    use super::tests::stub_color_provider;
    use super::*;

    use leet_data::system_metrics::MetricChartKind;
    use leet_data::units::UNIT_PERCENT;

    use crate::styles::Rgb;

    /// TestTimeSeriesLineChart_AutoTrailFreezeAndShowAll.
    #[test]
    fn time_series_line_chart_auto_trail_freeze_and_show_all() {
        let def = MetricDef {
            name: "CPU".to_string(),
            unit: UNIT_PERCENT,
            min_y: 0.0,
            max_y: 100.0,
            auto_range: true,
            percentage: false,
            chart_kind: MetricChartKind::Line,
            regex: None,
        };
        let start_secs: i64 = 1_700_000_000;
        let start = UNIX_EPOCH + Duration::from_secs(start_secs as u64);

        let mut chart = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 80,
            height: 20,
            def,
            base_color: AdaptiveColor {
                light: Rgb(0xFF, 0x00, 0xFF),
                dark: Rgb(0xFF, 0x00, 0xFF),
            },
            color_provider: Some(stub_color_provider(&["#00FF00"])),
            now: start,
        });
        chart.set_tail_window(Duration::from_secs(2 * 60));

        for i in 0..10i64 {
            let ts = start_secs + (i - 9) * 60; // start.Add(time.Duration(i-9) * time.Minute)
            chart.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, ts, i as f64);
        }

        let (view_min, view_max) = chart.test_view_range();
        assert!(chart.test_auto_trail());
        assert!(
            ((view_max - view_min) - 120.0).abs() <= 1.0,
            "tail window should default to 2 minutes"
        );
        assert!(view_max >= start_secs as f64);

        chart.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, start_secs + 60, 10.0);
        let (trail_min, trail_max) = chart.test_view_range();
        assert!(chart.test_auto_trail());
        assert!(trail_min > view_min);
        assert!(trail_max > view_max);

        for _ in 0..12 {
            if !chart.test_auto_trail() {
                break;
            }
            chart.handle_zoom("in", 0);
        }
        assert!(
            !chart.test_auto_trail(),
            "zooming away from the tail should freeze the view"
        );
        let (frozen_min, frozen_max) = chart.test_view_range();

        chart.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, start_secs + 2 * 60, 11.0);
        let (still_min, still_max) = chart.test_view_range();
        assert!((frozen_min - still_min).abs() <= 1e-9);
        assert!((frozen_max - still_max).abs() <= 1e-9);

        for _ in 0..32 {
            if chart.test_show_all() {
                break;
            }
            chart.handle_zoom("out", chart.graph_width() / 2);
        }
        assert!(
            chart.test_show_all(),
            "zooming out should eventually show the full history"
        );
        let (show_all_min, show_all_max) = chart.test_view_range();

        chart.add_data_point(DEFAULT_SYSTEM_METRIC_SERIES_NAME, start_secs + 3 * 60, 12.0);
        let (expanded_min, expanded_max) = chart.test_view_range();
        assert!(
            (show_all_min - expanded_min).abs() <= 10.0,
            "full-history mode should preserve the start"
        );
        assert!(
            expanded_max > show_all_max,
            "full-history mode should continue trailing live data"
        );
        assert!(chart.test_auto_trail());
    }
}
