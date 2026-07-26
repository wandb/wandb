//! Port of `core/internal/leet/frenchfriestogglechart.go`: an adapter that
//! keeps the existing time-series line chart as the source of truth for
//! time-window behavior while optionally rendering the same metric as a
//! heatmap-style French Fries chart.
//!
//! DIVERGENCE(hosting): the [`SystemMetricChart`] trait is Go's
//! `systemMetricChart` interface from systemmetricchart.go — a
//! `SystemMetricsGrid` (leet-tui) file. It is hosted here because
//! `activeChart()` returns it and leet-tui depends on leet-charts, not vice
//! versa (the same dependency-direction hosting as PORTING.md's filter.go
//! divergence). The `system_metrics_grid` port must reuse this trait, not
//! re-declare it.

use crate::canvas::Canvas;
use crate::french_fries_chart::FrenchFriesChart;
use crate::timeseries_line_chart::TimeSeriesLineChart;

/// Go `systemMetricChart` (systemmetricchart.go): the minimal surface that
/// SystemMetricsGrid needs from a rendered system-metric chart.
///
/// Receivers are `&mut self` wherever any implementor's Go pointer-receiver
/// method mutates on that path (draw caches, the sortedSeriesNames memo,
/// the effective view window); pure reporters stay `&self`.
pub trait SystemMetricChart {
    fn title(&self) -> String;
    fn title_detail(&mut self) -> String;
    /// Go `View() string`; the port returns the canvas render target
    /// (docs/PORTING.md Canvas row).
    fn view(&mut self) -> &Canvas;
    fn resize(&mut self, width: i64, height: i64);
    fn draw_if_needed(&mut self);
    fn park(&mut self);
    fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64);
    fn graph_width(&mut self) -> i64;
    fn graph_height(&mut self) -> i64;
    fn graph_start_x(&mut self) -> i64;
    fn graph_start_y(&mut self) -> i64;
    fn handle_zoom(&mut self, direction: &str, mouse_x: i64);
    fn toggle_y_scale(&mut self) -> bool;
    fn is_log_y(&self) -> bool;
    fn supports_heatmap(&self) -> bool;
    fn toggle_heatmap_mode(&mut self) -> bool;
    fn is_heatmap_mode(&self) -> bool;
    fn view_mode_label(&mut self) -> String;
    fn scale_label(&self) -> String;
    fn start_inspection_at(&mut self, mouse_x: i64, mouse_y: i64);
    fn update_inspection_at(&mut self, mouse_x: i64, mouse_y: i64);
    fn end_inspection(&mut self);
    fn is_inspecting(&self) -> bool;
    /// Go `InspectionData() (x, y float64, active bool)`.
    fn inspection_data(&self) -> (f64, f64, bool);
    fn inspect_at_data_x(&mut self, target_x: f64);
}

/// frenchfrieschart.go's method set satisfies systemMetricChart implicitly;
/// the port spells the impl out (pure delegation to the inherent methods).
impl SystemMetricChart for FrenchFriesChart {
    fn title(&self) -> String {
        FrenchFriesChart::title(self)
    }

    fn title_detail(&mut self) -> String {
        FrenchFriesChart::title_detail(self)
    }

    fn view(&mut self) -> &Canvas {
        FrenchFriesChart::view(self)
    }

    fn resize(&mut self, width: i64, height: i64) {
        FrenchFriesChart::resize(self, width, height);
    }

    fn draw_if_needed(&mut self) {
        FrenchFriesChart::draw_if_needed(self);
    }

    fn park(&mut self) {
        FrenchFriesChart::park(self);
    }

    fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        FrenchFriesChart::add_data_point(self, series_name, timestamp, value);
    }

    fn graph_width(&mut self) -> i64 {
        FrenchFriesChart::graph_width(self)
    }

    fn graph_height(&mut self) -> i64 {
        FrenchFriesChart::graph_height(self)
    }

    fn graph_start_x(&mut self) -> i64 {
        FrenchFriesChart::graph_start_x(self)
    }

    fn graph_start_y(&mut self) -> i64 {
        FrenchFriesChart::graph_start_y(self)
    }

    fn handle_zoom(&mut self, direction: &str, mouse_x: i64) {
        FrenchFriesChart::handle_zoom(self, direction, mouse_x);
    }

    fn toggle_y_scale(&mut self) -> bool {
        FrenchFriesChart::toggle_y_scale(self)
    }

    fn is_log_y(&self) -> bool {
        FrenchFriesChart::is_log_y(self)
    }

    fn supports_heatmap(&self) -> bool {
        FrenchFriesChart::supports_heatmap(self)
    }

    fn toggle_heatmap_mode(&mut self) -> bool {
        FrenchFriesChart::toggle_heatmap_mode(self)
    }

    fn is_heatmap_mode(&self) -> bool {
        FrenchFriesChart::is_heatmap_mode(self)
    }

    fn view_mode_label(&mut self) -> String {
        FrenchFriesChart::view_mode_label(self)
    }

    fn scale_label(&self) -> String {
        FrenchFriesChart::scale_label(self)
    }

    fn start_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        FrenchFriesChart::start_inspection_at(self, mouse_x, mouse_y);
    }

    fn update_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        FrenchFriesChart::update_inspection_at(self, mouse_x, mouse_y);
    }

    fn end_inspection(&mut self) {
        FrenchFriesChart::end_inspection(self);
    }

    fn is_inspecting(&self) -> bool {
        FrenchFriesChart::is_inspecting(self)
    }

    fn inspection_data(&self) -> (f64, f64, bool) {
        FrenchFriesChart::inspection_data(self)
    }

    fn inspect_at_data_x(&mut self, target_x: f64) {
        FrenchFriesChart::inspect_at_data_x(self, target_x);
    }
}

/// timeserieslinechart.go's method set (own methods plus the promoted
/// EpochLineChart / linechart.Model ones) satisfies systemMetricChart
/// implicitly; the port spells the impl out. Promoted methods are reached
/// through the `epoch` field, mirroring Go's embedding.
impl SystemMetricChart for TimeSeriesLineChart {
    fn title(&self) -> String {
        // Promoted EpochLineChart.Title.
        self.epoch.title().to_string()
    }

    fn title_detail(&mut self) -> String {
        TimeSeriesLineChart::title_detail(self)
    }

    fn view(&mut self) -> &Canvas {
        // Go: the promoted linechart.Model View() renders the canvas as-is
        // (no implicit draw; the grid calls DrawIfNeeded first).
        &self.epoch.model.canvas
    }

    fn resize(&mut self, width: i64, height: i64) {
        TimeSeriesLineChart::resize(self, width, height);
    }

    fn draw_if_needed(&mut self) {
        // Promoted EpochLineChart.DrawIfNeeded.
        self.epoch.draw_if_needed();
    }

    fn park(&mut self) {
        TimeSeriesLineChart::park(self);
    }

    fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        TimeSeriesLineChart::add_data_point(self, series_name, timestamp, value);
    }

    fn graph_width(&mut self) -> i64 {
        // Promoted linechart.Model.GraphWidth.
        self.epoch.model.graph_width()
    }

    fn graph_height(&mut self) -> i64 {
        self.epoch.model.graph_height()
    }

    fn graph_start_x(&mut self) -> i64 {
        TimeSeriesLineChart::graph_start_x(self)
    }

    fn graph_start_y(&mut self) -> i64 {
        TimeSeriesLineChart::graph_start_y(self)
    }

    fn handle_zoom(&mut self, direction: &str, mouse_x: i64) {
        TimeSeriesLineChart::handle_zoom(self, direction, mouse_x);
    }

    fn toggle_y_scale(&mut self) -> bool {
        TimeSeriesLineChart::toggle_y_scale(self)
    }

    fn is_log_y(&self) -> bool {
        // Promoted EpochLineChart.IsLogY.
        self.epoch.is_log_y()
    }

    fn supports_heatmap(&self) -> bool {
        TimeSeriesLineChart::supports_heatmap(self)
    }

    fn toggle_heatmap_mode(&mut self) -> bool {
        TimeSeriesLineChart::toggle_heatmap_mode(self)
    }

    fn is_heatmap_mode(&self) -> bool {
        TimeSeriesLineChart::is_heatmap_mode(self)
    }

    fn view_mode_label(&mut self) -> String {
        TimeSeriesLineChart::view_mode_label(self)
    }

    fn scale_label(&self) -> String {
        // Promoted EpochLineChart.ScaleLabel.
        self.epoch.scale_label().to_string()
    }

    fn start_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        TimeSeriesLineChart::start_inspection_at(self, mouse_x, mouse_y);
    }

    fn update_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        TimeSeriesLineChart::update_inspection_at(self, mouse_x, mouse_y);
    }

    fn end_inspection(&mut self) {
        // Promoted EpochLineChart.EndInspection.
        self.epoch.end_inspection();
    }

    fn is_inspecting(&self) -> bool {
        self.epoch.is_inspecting()
    }

    fn inspection_data(&self) -> (f64, f64, bool) {
        self.epoch.inspection_data()
    }

    fn inspect_at_data_x(&mut self, target_x: f64) {
        self.epoch.inspect_at_data_x(target_x);
    }
}

/// frenchFriesToggleChart keeps the existing time-series line chart as the
/// source of truth for time-window behavior while optionally rendering the
/// same metric as a heatmap-style French Fries chart.
// Go holds *TimeSeriesLineChart / *FrenchFriesChart pointers; the toggle is
// the sole owner in the port. Pub (Go-unexported) because leet-tui's grid
// constructs it, as with the other chart types.
pub struct FrenchFriesToggleChart {
    line: TimeSeriesLineChart,
    french_fries: FrenchFriesChart,
    heatmap_mode: bool,
}

impl FrenchFriesToggleChart {
    /// Go `newFrenchFriesToggleChart`.
    pub fn new(
        line: TimeSeriesLineChart,
        french_fries: FrenchFriesChart,
    ) -> FrenchFriesToggleChart {
        let mut chart = FrenchFriesToggleChart {
            line,
            french_fries,
            heatmap_mode: false,
        };
        chart.sync_view_window();
        chart
    }

    // PARITY: Go's activeChart serves both read and write call sites
    // through one method; the port needs an immutable twin (borrowck).
    fn active_chart(&mut self) -> &mut dyn SystemMetricChart {
        if self.heatmap_mode {
            return &mut self.french_fries;
        }
        &mut self.line
    }

    fn active_chart_ref(&self) -> &dyn SystemMetricChart {
        if self.heatmap_mode {
            return &self.french_fries;
        }
        &self.line
    }

    fn sync_view_window(&mut self) {
        // PARITY: Go also nil-checks c, c.line and c.frenchFries —
        // unrepresentable here (owned fields).
        let (min_x, max_x) = (self.line.view_min_x(), self.line.view_max_x());
        self.french_fries.set_view_window(min_x, max_x);
    }

    /// The wrapped FrenchFriesChart. testhelpers.go's
    /// `TestFrenchFriesChartAt` reaches it via a Go type assertion; the
    /// grid port needs the same access cross-crate.
    pub fn french_fries(&self) -> &FrenchFriesChart {
        &self.french_fries
    }
}

impl SystemMetricChart for FrenchFriesToggleChart {
    fn title(&self) -> String {
        self.line.title()
    }

    fn title_detail(&mut self) -> String {
        self.active_chart().title_detail()
    }

    fn view(&mut self) -> &Canvas {
        self.active_chart().view()
    }

    /// Park minimizes memory for both underlying charts.
    fn park(&mut self) {
        SystemMetricChart::park(&mut self.line);
        self.french_fries.park();
    }

    fn resize(&mut self, width: i64, height: i64) {
        SystemMetricChart::resize(&mut self.line, width, height);
        self.french_fries.resize(width, height);
        self.sync_view_window();
    }

    fn draw_if_needed(&mut self) {
        self.sync_view_window();
        self.active_chart().draw_if_needed();
    }

    fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        SystemMetricChart::add_data_point(&mut self.line, series_name, timestamp, value);
        self.french_fries
            .add_data_point(series_name, timestamp, value);
        self.sync_view_window();
    }

    fn graph_width(&mut self) -> i64 {
        self.active_chart().graph_width()
    }

    fn graph_height(&mut self) -> i64 {
        self.active_chart().graph_height()
    }

    fn graph_start_x(&mut self) -> i64 {
        self.active_chart().graph_start_x()
    }

    fn graph_start_y(&mut self) -> i64 {
        self.active_chart().graph_start_y()
    }

    fn handle_zoom(&mut self, direction: &str, mouse_x: i64) {
        SystemMetricChart::handle_zoom(&mut self.line, direction, mouse_x);
        self.sync_view_window();
        self.active_chart().draw_if_needed();
    }

    fn toggle_y_scale(&mut self) -> bool {
        if self.heatmap_mode {
            return false;
        }
        SystemMetricChart::toggle_y_scale(&mut self.line)
    }

    fn is_log_y(&self) -> bool {
        if self.heatmap_mode {
            return false;
        }
        SystemMetricChart::is_log_y(&self.line)
    }

    fn supports_heatmap(&self) -> bool {
        true
    }

    fn toggle_heatmap_mode(&mut self) -> bool {
        self.heatmap_mode = !self.heatmap_mode;
        self.sync_view_window();
        self.active_chart().draw_if_needed();
        true
    }

    fn is_heatmap_mode(&self) -> bool {
        self.heatmap_mode
    }

    fn view_mode_label(&mut self) -> String {
        SystemMetricChart::view_mode_label(&mut self.line)
    }

    fn scale_label(&self) -> String {
        if self.heatmap_mode {
            return "heatmap".to_string();
        }
        SystemMetricChart::scale_label(&self.line)
    }

    fn start_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        self.sync_view_window();
        self.active_chart().start_inspection_at(mouse_x, mouse_y);
    }

    fn update_inspection_at(&mut self, mouse_x: i64, mouse_y: i64) {
        self.sync_view_window();
        self.active_chart().update_inspection_at(mouse_x, mouse_y);
    }

    fn end_inspection(&mut self) {
        SystemMetricChart::end_inspection(&mut self.line);
        self.french_fries.end_inspection();
    }

    fn is_inspecting(&self) -> bool {
        self.active_chart_ref().is_inspecting()
    }

    fn inspection_data(&self) -> (f64, f64, bool) {
        self.active_chart_ref().inspection_data()
    }

    fn inspect_at_data_x(&mut self, target_x: f64) {
        self.sync_view_window();
        self.active_chart().inspect_at_data_x(target_x);
    }
}

// ---------------------------------------------------------------------------
// Port-added smoke test: frenchfriestogglechart.go has no Go unit tests
// (its behavior is exercised by SystemMetricsGrid cases that port to
// leet-tui). This pins the delegation wiring the grid relies on.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    use leet_data::system_metrics::{MetricChartKind, MetricDef};
    use leet_data::units::UNIT_PERCENT;
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::french_fries_chart::FrenchFriesChartParams;
    use crate::styles::{AdaptiveColor, Rgb};
    use crate::timeseries_line_chart::TimeSeriesLineChartParams;

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

    fn test_now() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(1_700_000_000)
    }

    fn new_toggle() -> FrenchFriesToggleChart {
        let base = Rgb(0x11, 0x22, 0x33);
        let line = TimeSeriesLineChart::new(TimeSeriesLineChartParams {
            width: 40,
            height: 10,
            def: percent_def(),
            base_color: AdaptiveColor {
                light: base,
                dark: base,
            },
            color_provider: None,
            now: test_now(),
        });
        let fries = FrenchFriesChart::new(&FrenchFriesChartParams {
            width: 40,
            height: 10,
            def: &percent_def(),
            colors: &[],
            now: test_now(),
        });
        FrenchFriesToggleChart::new(line, fries)
    }

    #[test]
    fn toggle_chart_syncs_window_and_switches_active_chart() {
        let mut toggle = new_toggle();

        // Line mode by default; ScaleLabel comes from the line chart
        // (empty for linear).
        assert!(!toggle.is_heatmap_mode());
        assert!(toggle.supports_heatmap());
        assert_eq!(toggle.scale_label(), "");

        // AddDataPoint feeds both charts and syncs the line chart's view
        // window into the fries chart (frenchfriestogglechart.go:67-71).
        toggle.add_data_point("GPU 0", 1_700_000_000, 10.0);
        toggle.add_data_point("GPU 0", 1_700_000_060, 90.0);
        assert!(toggle.french_fries.view_ready);
        assert_eq!(toggle.french_fries.view_min_x, toggle.line.view_min_x());
        assert_eq!(toggle.french_fries.view_max_x, toggle.line.view_max_x());

        // Log toggling is delegated to the line chart in line mode...
        assert!(toggle.toggle_y_scale());
        assert!(toggle.is_log_y());

        // ...and suppressed entirely in heatmap mode
        // (frenchfriestogglechart.go:95-107); the line chart keeps its
        // state underneath.
        assert!(toggle.toggle_heatmap_mode());
        assert!(toggle.is_heatmap_mode());
        assert_eq!(toggle.scale_label(), "heatmap");
        assert!(!toggle.toggle_y_scale());
        assert!(!toggle.is_log_y());
        assert!(toggle.line.epoch.is_log_y());

        // Inspection routes to the active (fries) chart, and EndInspection
        // clears both.
        toggle.start_inspection_at(1, 0);
        assert!(toggle.is_inspecting());
        assert!(toggle.french_fries.is_inspecting());
        toggle.end_inspection();
        assert!(!toggle.is_inspecting());

        // Toggling back re-activates the line chart with log-Y intact.
        assert!(toggle.toggle_heatmap_mode());
        assert!(!toggle.is_heatmap_mode());
        assert!(toggle.is_log_y());
    }
}
