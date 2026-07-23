//! Time-based system metrics chart.
//!
//! Reuses [`EpochLineChart`]'s multi-series rendering and inspection behavior
//! while adding live-tail windowing semantics for timestamped data.

use std::collections::{HashMap, HashSet};

use ratatui::style::Style;

use crate::systemmetrics::{DEFAULT_SYSTEM_METRIC_SERIES_NAME, MetricDef};
use crate::theme::Adaptive;

use super::epoch::{
    AxisScaleMode, EpochLineChart, InspectionLabelStyle, MIN_ZOOM_RANGE, Series, XAxisStyle,
    ZoomDirection, calculate_log_range,
};
use super::timefmt::compact_duration;

const MIN_SYSTEM_METRICS_RIGHT_PAD_SECS: f64 = 2.0;
const MAX_SYSTEM_METRICS_RIGHT_PAD_SECS: f64 = 10.0;

/// Default live tail window in minutes (config.go: DefaultSystemTailWindowMins).
pub const DEFAULT_SYSTEM_TAIL_WINDOW_MINS: u64 = 10;

/// Provides the next color for additional series on a chart.
pub type ColorProvider = Box<dyn FnMut() -> Adaptive>;

/// Chart of timestamped system metrics with live-tail behavior.
///
/// A single chart can contain multiple related series (e.g. GPU 0 / GPU 1).
/// By default the chart auto-trails the most recent data using `tail_window`.
/// Users can zoom out to show the entire history; if the latest point remains
/// visible after a zoom, the view continues trailing live updates.
pub struct TimeSeriesLineChart {
    pub chart: EpochLineChart,

    def: &'static MetricDef,

    /// Named (non-default) series, for display purposes.
    series: HashSet<String>,
    /// Assigned color for each underlying series key.
    series_colors: HashMap<String, Adaptive>,
    base_color: Adaptive,
    /// Yields the next color for additional series; anchored to the chart's
    /// base color so multi-series colors are stable per chart.
    color_provider: Option<ColorProvider>,

    /// Windows in seconds.
    tail_window: f64,
    view_window: f64,

    view_initialized: bool,
    auto_trail: bool,
    show_all: bool,

    /// Unix seconds of the most recent sample.
    last_update: i64,
    min_value: f64,
    max_value: f64,
}

pub struct TimeSeriesLineChartParams {
    pub width: usize,
    pub height: usize,
    pub def: &'static MetricDef,
    pub base_color: Adaptive,
    pub color_provider: Option<ColorProvider>,
    /// Current time in unix seconds.
    pub now: i64,
}

impl TimeSeriesLineChart {
    pub fn new(params: TimeSeriesLineChartParams) -> Self {
        let tail_window = DEFAULT_SYSTEM_TAIL_WINDOW_MINS as f64 * 60.0;

        let mut base_chart = EpochLineChart::new(&params.def.title());
        base_chart.set_y_tick_unit(params.def.unit);
        base_chart.x_axis_style = XAxisStyle::Time;
        base_chart.inspection_label_style = InspectionLabelStyle::Time(params.def.unit);

        let mut chart = Self {
            chart: base_chart,
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
        chart.resize(params.width, params.height);
        chart
    }

    pub fn def(&self) -> &'static MetricDef {
        self.def
    }

    /// Updates the default live tail window (seconds).
    pub fn set_tail_window(&mut self, window_secs: f64) {
        self.tail_window = window_secs;
        if !self.view_initialized || self.auto_trail {
            self.view_window = window_secs;
        }
        self.apply_ranges();
    }

    /// Adds a data point to this chart, creating series as needed.
    pub fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        let (series_key, created) = self.ensure_series(series_name);
        self.last_update = timestamp;

        self.min_value = self.min_value.min(value);
        self.max_value = self.max_value.max(value);

        self.add_point(&series_key, timestamp as f64, value);

        if created {
            let style = Style::new().fg(self.series_colors[&series_key].color());
            self.chart.set_series_style(&series_key, style);
        }
        self.apply_ranges();
    }

    /// Minimizes canvas memory for off-screen charts.
    pub fn park(&mut self) {
        self.chart.park();
    }

    /// Updates the underlying chart size and reapplies the view policy.
    pub fn resize(&mut self, width: usize, height: usize) {
        self.chart.resize(width, height);
        self.apply_ranges();
    }

    /// Updates the current time window and live-trailing state.
    pub fn handle_zoom(&mut self, direction: ZoomDirection, mouse_x: i32) {
        self.chart.handle_zoom(direction, mouse_x);
        self.view_initialized = true;
        self.reconcile_view_state();
    }

    /// Switches the Y-axis scaling mode while preserving the chart's
    /// time-window policy (live tail, frozen window, or full history).
    pub fn set_y_scale(&mut self, mode: AxisScaleMode) -> bool {
        if mode == AxisScaleMode::Log && !self.chart.can_use_log_y() {
            return false;
        }
        if self.chart.y_scale == mode {
            return false;
        }
        self.chart.y_scale = mode;
        self.apply_ranges();
        self.chart.dirty = true;
        true
    }

    pub fn toggle_y_scale(&mut self) -> bool {
        if self.chart.is_log_y() {
            self.set_y_scale(AxisScaleMode::Linear)
        } else {
            self.set_y_scale(AxisScaleMode::Log)
        }
    }

    /// A short description of the current X-axis mode.
    pub fn view_mode_label(&self) -> String {
        if self.show_all {
            return "all history".to_string();
        }

        let mut window = self.view_window;
        if window <= 0.0 {
            window = self.tail_window;
        }
        let window = window.round() as i64;

        if self.auto_trail {
            format!("live tail {}", compact_duration(window))
        } else {
            format!("frozen {}", compact_duration(window))
        }
    }

    /// The compact suffix rendered next to the chart title.
    pub fn title_detail(&self) -> String {
        if self.series.len() <= 1 {
            return String::new();
        }
        format!("[{}]", self.series.len())
    }

    /// The first graph column inside the rendered chart view.
    pub fn graph_start_x(&self) -> i32 {
        let mut start_x = 1;
        if self.chart.model.y_step() > 0 {
            start_x += self.chart.model.origin().0 + 1;
        }
        start_x
    }

    /// Unix seconds of the most recent sample seen.
    pub fn last_update(&self) -> i64 {
        self.last_update
    }

    /// The observed [min,max] values tracked for auto-ranging.
    pub fn value_bounds(&self) -> (f64, f64) {
        (self.min_value, self.max_value)
    }

    fn ensure_series(&mut self, series_name: &str) -> (String, bool) {
        let series_key = if series_name.is_empty() {
            DEFAULT_SYSTEM_METRIC_SERIES_NAME.to_string()
        } else {
            series_name.to_string()
        };
        if self.series_colors.contains_key(&series_key) {
            return (series_key, false);
        }

        let color = if self.series_colors.is_empty() {
            self.base_color
        } else {
            self.next_series_color()
        };
        if series_key != DEFAULT_SYSTEM_METRIC_SERIES_NAME {
            self.series.insert(series_key.clone());
        }
        self.series_colors.insert(series_key.clone(), color);
        (series_key, true)
    }

    fn add_point(&mut self, series_key: &str, x: f64, y: f64) {
        let c = &mut self.chart;
        if !c.data.contains_key(series_key) {
            c.data
                .insert(series_key.to_string(), Series::new(series_key, &c.palette));
            c.order.push(series_key.to_string());
        }
        let s = c.data.get_mut(series_key).expect("series just inserted");
        s.add_point(x, y);
        c.x_min = c.x_min.min(x);
        c.x_max = c.x_max.max(x);
        c.y_min = c.y_min.min(y);
        c.y_max = c.y_max.max(y);
        c.dirty = true;
    }

    fn next_series_color(&mut self) -> Adaptive {
        match &mut self.color_provider {
            Some(provider) => provider(),
            None => self.base_color,
        }
    }

    fn apply_ranges(&mut self) {
        if self.chart.series_count() == 0 {
            return;
        }

        let data_min = self.chart.x_min;
        let data_max = self.chart.x_max;
        if !data_min.is_finite() || !data_max.is_finite() {
            return;
        }

        let (y_min, y_max) = self.compute_y_range();
        self.chart.model.set_y_range(y_min, y_max);
        self.chart.model.set_view_y_range(y_min, y_max);

        let mut domain_max = data_max + self.right_pad_secs();
        if domain_max - data_min < MIN_ZOOM_RANGE {
            domain_max = data_min + MIN_ZOOM_RANGE;
        }
        self.chart.model.set_x_range(data_min, domain_max);

        if self.show_all {
            self.chart.model.set_view_x_range(data_min, domain_max);
            self.chart.user_view_min_x = data_min;
            self.chart.user_view_max_x = domain_max;
        } else if !self.view_initialized || self.auto_trail {
            let mut window = self.view_window;
            if !self.view_initialized || window <= 0.0 {
                window = self.tail_window;
            }
            if window < MIN_ZOOM_RANGE {
                window = MIN_ZOOM_RANGE;
            }
            self.snap_view_to_tail(window, data_min, domain_max);
            self.view_initialized = true;
        } else {
            self.clamp_user_view(data_min, domain_max);
        }

        self.chart.sync_layout();

        if self.chart.inspection.active {
            self.chart.refresh_inspection_after_view_change();
        }
        self.chart.dirty = true;
    }

    fn compute_y_range(&self) -> (f64, f64) {
        if self.chart.is_log_y() {
            return self.compute_log_y_range();
        }

        if !self.def.auto_range
            || self.def.percentage
            || !self.min_value.is_finite()
            || !self.max_value.is_finite()
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

    fn compute_log_y_range(&self) -> (f64, f64) {
        if (!self.def.auto_range || self.def.percentage)
            && self.def.min_y > 0.0
            && self.def.max_y > self.def.min_y
        {
            return calculate_log_range(self.def.min_y, self.def.max_y);
        }

        match self.chart.positive_y_bounds() {
            Some((min_positive, max_positive)) => calculate_log_range(min_positive, max_positive),
            None => (self.def.min_y, self.def.max_y),
        }
    }

    fn right_pad_secs(&self) -> f64 {
        (self.tail_window / 60.0).clamp(
            MIN_SYSTEM_METRICS_RIGHT_PAD_SECS,
            MAX_SYSTEM_METRICS_RIGHT_PAD_SECS,
        )
    }

    fn snap_view_to_tail(&mut self, window: f64, data_min: f64, domain_max: f64) {
        let mut window = window;
        if window <= 0.0 {
            window = self.tail_window.max(MIN_ZOOM_RANGE);
        }
        let view_max = domain_max;
        let view_min = (view_max - window).max(data_min);
        self.chart.model.set_view_x_range(view_min, view_max);
        self.chart.user_view_min_x = view_min;
        self.chart.user_view_max_x = view_max;
    }

    fn clamp_user_view(&mut self, data_min: f64, domain_max: f64) {
        let mut view_min = self.chart.user_view_min_x;
        let mut view_max = self.chart.user_view_max_x;
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            self.auto_trail = true;
            let mut window = self.view_window;
            if window <= 0.0 {
                window = self.tail_window;
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

        self.chart.model.set_view_x_range(view_min, view_max);
        self.chart.user_view_min_x = view_min;
        self.chart.user_view_max_x = view_max;
    }

    fn reconcile_view_state(&mut self) {
        if self.chart.series_count() == 0 {
            return;
        }

        let data_min = self.chart.x_min;
        let data_max = self.chart.x_max;
        if !data_min.is_finite() || !data_max.is_finite() {
            return;
        }

        let view_min = self.chart.model.view_min_x();
        let view_max = self.chart.model.view_max_x();
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            return;
        }

        let eps = (self.chart.pixel_eps_x(view_range) * 2.0).max(1.0);
        let full_range = self.chart.model.max_x() - data_min;

        self.show_all = full_range > 0.0 && view_range >= full_range - eps;
        self.auto_trail = view_max >= data_max - eps;
        if self.show_all {
            self.auto_trail = true;
        }

        self.view_window = view_range.round().max(MIN_ZOOM_RANGE);

        if self.show_all {
            self.chart.user_view_min_x = data_min;
            self.chart.user_view_max_x = self.chart.model.max_x();
            return;
        }
        if self.auto_trail {
            self.snap_view_to_tail(view_range, data_min, self.chart.model.max_x());
            return;
        }

        self.chart.user_view_min_x = self.chart.model.view_min_x();
        self.chart.user_view_max_x = self.chart.model.view_max_x();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::systemmetrics::match_metric_def;
    use crate::theme::adaptive;

    fn new_chart() -> TimeSeriesLineChart {
        TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 60,
            height: 12,
            def: match_metric_def("cpu").unwrap(),
            base_color: adaptive(0xff0000, 0xff0000),
            color_provider: None,
            now: 1_700_000_000,
        })
    }

    #[test]
    fn live_tail_by_default() {
        let mut c = new_chart();
        for i in 0..100 {
            c.add_data_point("", 1_700_000_000 + i * 10, 50.0 + (i % 10) as f64);
        }
        assert!(c.view_mode_label().starts_with("live tail"));
        // Percentage metric: fixed 0-100 Y range.
        assert_eq!(c.chart.model.view_min_y(), 0.0);
        assert_eq!(c.chart.model.view_max_y(), 100.0);
        // View trails the latest data.
        assert!(c.chart.model.view_max_x() >= 1_700_000_990.0);
        c.chart.draw();
    }

    #[test]
    fn multi_series_title_detail() {
        let mut c = new_chart();
        c.add_data_point("GPU 0", 1_700_000_000, 10.0);
        c.add_data_point("GPU 1", 1_700_000_000, 20.0);
        assert_eq!(c.title_detail(), "[2]");
    }
}
