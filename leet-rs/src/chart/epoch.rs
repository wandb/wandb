//! Line chart for epoch/step-based ML training data.
//!
//! Supports multiple series rendered with opaque compositing (painter's
//! algorithm), where the last series in draw order appears on top.

use ratatui::style::Style;
use unicode_width::UnicodeWidthStr;

use crate::msg::MetricData;
use crate::theme::{self, Adaptive, BOX_LIGHT_VERTICAL, DEFAULT_COLOR_SCHEME};
use crate::units::{Unit, format_sig_figs, format_x_axis_tick};

use super::braille::{BRAILLE_BLOCK_OFFSET, BrailleGrid, draw_line, go_round};
use super::canvas::Cell;
use super::linechart::LineChartModel;
use super::timefmt;

const DEFAULT_ZOOM_FACTOR: f64 = 0.10;
pub(crate) const MIN_ZOOM_RANGE: f64 = 5.0;
const TAIL_ANCHOR_MOUSE_THRESHOLD: f64 = 0.95;
const DEFAULT_MAX_X: f64 = 20.0;
const DEFAULT_MAX_Y: f64 = 1.0;

/// Minimal canvas size for parked (off-screen) charts.
pub const PARKED_CANVAS_SIZE: usize = 1;

const MIN_LOG_SCALE_MARGIN: f64 = 0.1;

/// Controls how Y values are projected for rendering.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum AxisScaleMode {
    #[default]
    Linear,
    Log,
}

impl std::fmt::Display for AxisScaleMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AxisScaleMode::Log => write!(f, "log"),
            AxisScaleMode::Linear => write!(f, "linear"),
        }
    }
}

/// Zoom direction for [`EpochLineChart::handle_zoom`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ZoomDirection {
    In,
    Out,
}

/// Raw samples in arrival order plus precomputed bounds.
pub struct Series {
    pub x: Vec<f64>,
    pub y: Vec<f64>,
    pub style: Style,

    x_min: f64,
    x_max: f64,
    y_min: f64,
    y_max: f64,
    y_min_positive: f64,
}

impl Series {
    pub fn new(name: &str, palette: &[Adaptive]) -> Self {
        let default_palette;
        let palette = if palette.is_empty() {
            default_palette = theme::graph_colors(DEFAULT_COLOR_SCHEME);
            default_palette
        } else {
            palette
        };
        // Stable mapping for consistent colors across sessions.
        let i = theme::color_index(name, palette.len());
        Self {
            x: Vec::with_capacity(256),
            y: Vec::with_capacity(256),
            style: Style::new().fg(palette[i].color()),
            x_min: f64::INFINITY,
            x_max: f64::NEG_INFINITY,
            y_min: f64::INFINITY,
            y_max: f64::NEG_INFINITY,
            y_min_positive: f64::INFINITY,
        }
    }

    /// Extends the series bounds with the given data batch.
    ///
    /// Non-finite samples (NaN/Inf, e.g. a diverged loss) are excluded so
    /// they cannot poison the bounds; they still render as gaps in the line.
    fn update_bounds(&mut self, xs: &[f64], ys: &[f64]) {
        for &x in xs {
            if !x.is_finite() {
                continue;
            }
            self.x_min = self.x_min.min(x);
            self.x_max = self.x_max.max(x);
        }
        for &y in ys {
            if !y.is_finite() {
                continue;
            }
            self.y_min = self.y_min.min(y);
            self.y_max = self.y_max.max(y);
            if y > 0.0 {
                self.y_min_positive = self.y_min_positive.min(y);
            }
        }
    }

    pub fn bounds(&self) -> (f64, f64, f64, f64) {
        (self.x_min, self.x_max, self.y_min, self.y_max)
    }

    /// Appends a single sample and incrementally updates bounds.
    pub fn add_point(&mut self, x: f64, y: f64) {
        self.x.push(x);
        self.y.push(y);
        if x.is_finite() {
            self.x_min = self.x_min.min(x);
            self.x_max = self.x_max.max(x);
        }
        if y.is_finite() {
            self.y_min = self.y_min.min(y);
            self.y_max = self.y_max.max(y);
            if y > 0.0 {
                self.y_min_positive = self.y_min_positive.min(y);
            }
        }
    }
}

/// Crosshair overlay state for data inspection mode.
#[derive(Debug, Clone, Copy, Default)]
pub struct ChartInspection {
    pub active: bool,
    /// Vertical crosshair position in graph-local pixels.
    pub mouse_x: i32,
    /// Coordinates of the nearest data sample.
    pub data_x: f64,
    pub data_y: f64,
}

/// How X axis tick values are rendered.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub(crate) enum XAxisStyle {
    /// Step counts with SI prefixes.
    #[default]
    Step,
    /// Unix-second timestamps rendered as wall-clock times.
    Time,
}

/// How inspection legend labels are rendered.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub(crate) enum InspectionLabelStyle {
    /// "X: Y" with 4 significant figures.
    #[default]
    Step,
    /// "HH:MM:SS <value>" with the given unit.
    Time(Unit),
}

/// A line chart for epoch/step-based training metrics.
pub struct EpochLineChart {
    pub model: LineChartModel,

    pub(crate) data: std::collections::HashMap<String, Series>,
    /// Draw order: last element appears visually on top.
    pub(crate) order: Vec<String>,
    pub(crate) palette: Vec<Adaptive>,

    focused: bool,
    title: String,
    pub(crate) dirty: bool,

    /// Set after the user adjusts the X view via zoom; preserves the view
    /// across data updates.
    pub(crate) is_zoomed: bool,
    pub(crate) user_view_min_x: f64,
    pub(crate) user_view_max_x: f64,

    pub(crate) x_min: f64,
    pub(crate) x_max: f64,
    pub(crate) y_min: f64,
    pub(crate) y_max: f64,

    pub(crate) y_scale: AxisScaleMode,
    /// Formats raw, unscaled Y values for axis labels.
    y_tick_unit: Unit,

    pub(crate) inspection: ChartInspection,
    pub(crate) x_axis_style: XAxisStyle,
    pub(crate) inspection_label_style: InspectionLabelStyle,
}

impl EpochLineChart {
    pub fn new(title: &str) -> Self {
        let mut model = LineChartModel::new(
            PARKED_CANVAS_SIZE,
            PARKED_CANVAS_SIZE,
            0.0,
            DEFAULT_MAX_X,
            0.0,
            DEFAULT_MAX_Y,
            4, // X axis tick steps
            5, // Y axis tick steps
        );
        model.axis_style = theme::axis_style();
        model.label_style = theme::label_style();

        let mut chart = Self {
            model,
            data: Default::default(),
            order: Vec::new(),
            palette: theme::graph_colors(DEFAULT_COLOR_SCHEME).to_vec(),
            focused: false,
            title: title.to_string(),
            dirty: false,
            is_zoomed: false,
            user_view_min_x: 0.0,
            user_view_max_x: 0.0,
            x_min: f64::INFINITY,
            x_max: f64::NEG_INFINITY,
            y_min: f64::INFINITY,
            y_max: f64::NEG_INFINITY,
            y_scale: AxisScaleMode::Linear,
            y_tick_unit: Unit::Scalar,
            inspection: ChartInspection::default(),
            x_axis_style: XAxisStyle::default(),
            inspection_label_style: InspectionLabelStyle::default(),
        };
        chart.sync_layout();
        chart
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn is_focused(&self) -> bool {
        self.focused
    }

    pub fn set_focused(&mut self, focused: bool) {
        self.focused = focused;
    }

    pub fn set_y_tick_unit(&mut self, unit: Unit) {
        self.y_tick_unit = unit;
        self.sync_layout();
    }

    pub fn y_tick_unit(&self) -> Unit {
        self.y_tick_unit
    }

    /// Recomputes graph geometry from the current view Y range.
    pub(crate) fn sync_layout(&mut self) {
        let scale = self.y_scale;
        let unit = self.y_tick_unit;
        self.model
            .update_graph_sizes(&move |_, v| format_y_tick(scale, unit, v));
    }

    pub fn y_scale(&self) -> AxisScaleMode {
        self.y_scale
    }

    pub fn is_log_y(&self) -> bool {
        self.y_scale == AxisScaleMode::Log
    }

    /// A compact label for the active Y-axis scale.
    pub fn scale_label(&self) -> &'static str {
        if self.is_log_y() { "log y" } else { "" }
    }

    /// Whether the chart has at least one strictly positive sample.
    pub fn can_use_log_y(&self) -> bool {
        self.positive_y_bounds().is_some()
    }

    /// Switches the Y-axis scaling mode. Log scaling requires at least one
    /// strictly positive value. Returns false if nothing changed.
    pub fn set_y_scale(&mut self, mode: AxisScaleMode) -> bool {
        if mode == AxisScaleMode::Log && !self.can_use_log_y() {
            return false;
        }
        if self.y_scale == mode {
            return false;
        }
        self.y_scale = mode;
        self.update_ranges();
        self.dirty = true;
        true
    }

    pub fn toggle_y_scale(&mut self) -> bool {
        if self.is_log_y() {
            self.set_y_scale(AxisScaleMode::Linear)
        } else {
            self.set_y_scale(AxisScaleMode::Log)
        }
    }

    /// The topmost series (last in draw order), used for inspection snapping.
    pub(crate) fn top_series(&self) -> Option<&Series> {
        self.order.last().and_then(|k| self.data.get(k))
    }

    /// Maximum X axis label width based on available space.
    pub(crate) fn max_x_label_width(&self) -> usize {
        let w = self.model.graph_width();
        if w <= 0 {
            return 0;
        }
        // Approx spacing between ticks; leave one column slack so labels
        // collide less often.
        let mut per = w / self.model.x_step();
        if per > 1 {
            per -= 1;
        }
        per.max(1) as usize
    }

    /// Updates the color palette for new series. Existing series keep their
    /// current colors.
    pub fn set_palette(&mut self, colors: &[Adaptive]) {
        self.palette = if colors.is_empty() {
            theme::graph_colors(DEFAULT_COLOR_SCHEME).to_vec()
        } else {
            colors.to_vec()
        };
    }

    /// Appends (x, y) points to the named series, creating it if needed.
    /// X values should be non-decreasing for efficient rendering.
    pub fn add_data(&mut self, key: &str, data: &MetricData) {
        if !self.data.contains_key(key) {
            self.data
                .insert(key.to_string(), Series::new(key, &self.palette));
            self.order.push(key.to_string());
        }
        let s = self.data.get_mut(key).expect("series just inserted");

        if data.x.len() != data.y.len() || data.x.is_empty() {
            return;
        }

        s.x.extend_from_slice(&data.x);
        s.y.extend_from_slice(&data.y);

        s.update_bounds(&data.x, &data.y);
        let (sx_min, sx_max, sy_min, sy_max) = s.bounds();
        self.x_min = self.x_min.min(sx_min);
        self.x_max = self.x_max.max(sx_max);
        self.y_min = self.y_min.min(sy_min);
        self.y_max = self.y_max.max(sy_max);

        self.update_ranges();
        self.dirty = true;
    }

    /// Recomputes axis ranges from current bounds.
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
        if !data_x_max.is_finite() {
            data_x_max = 0.0;
        }
        let nice_max = if data_x_max < DEFAULT_MAX_X {
            // Keep a decent default domain early in a run.
            DEFAULT_MAX_X
        } else {
            // Round to nearest 10.
            (((data_x_max.ceil() as i64 + 9) / 10) * 10) as f64
        };

        self.model.set_y_range(new_y_min, new_y_max);
        self.model.set_view_y_range(new_y_min, new_y_max);

        // Always ensure X range covers the nice domain; only alter view if
        // not zoomed.
        self.model.set_x_range(data_x_min, nice_max);
        if !self.is_zoomed {
            let view_min = if self.x_min.is_finite() {
                self.x_min
            } else {
                0.0
            };
            self.model.set_view_x_range(view_min, nice_max);
        }

        self.model
            .set_x_range(self.model.min_x(), self.model.max_x());
        self.model.set_y_range(new_y_min, new_y_max);
        self.sync_layout();

        // Keep inspection overlay consistent if the view/domain changed.
        if self.inspection.active {
            self.refresh_inspection_after_view_change();
        }
    }

    fn compute_y_range(&self) -> Option<(f64, f64)> {
        if self.is_log_y() {
            let (min_positive, max_positive) = self.positive_y_bounds()?;
            return Some(calculate_log_range(min_positive, max_positive));
        }

        // No finite samples yet (e.g. only NaN/Inf values logged so far).
        if !self.y_min.is_finite() || !self.y_max.is_finite() {
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

    pub(crate) fn positive_y_bounds(&self) -> Option<(f64, f64)> {
        let mut min_positive = f64::INFINITY;
        let mut max_positive = f64::NEG_INFINITY;

        for series in self.data.values() {
            if series.y.is_empty() || series.y_max <= 0.0 || !series.y_min_positive.is_finite() {
                continue;
            }
            min_positive = min_positive.min(series.y_min_positive);
            max_positive = max_positive.max(series.y_max);
        }

        if !min_positive.is_finite() || !max_positive.is_finite() || max_positive <= 0.0 {
            return None;
        }
        Some((min_positive, max_positive))
    }

    /// Determines appropriate padding for the Y axis.
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
        (value_range * 0.1).max(1e-6)
    }

    /// Processes zoom events with the mouse X position in graph pixels.
    pub fn handle_zoom(&mut self, direction: ZoomDirection, mouse_x: i32) {
        let view_min = self.model.view_min_x();
        let view_max = self.model.view_max_x();
        let view_range = view_max - view_min;
        if view_range <= 0.0 {
            return;
        }

        let mouse_proportion = (mouse_x as f64 / self.model.graph_width() as f64).clamp(0.0, 1.0);
        let step_under_mouse = view_min + mouse_proportion * view_range;

        let mut new_range = match direction {
            ZoomDirection::In => view_range * (1.0 - DEFAULT_ZOOM_FACTOR),
            ZoomDirection::Out => view_range * (1.0 + DEFAULT_ZOOM_FACTOR),
        };
        new_range = new_range
            .min(self.model.max_x() - self.model.min_x())
            .max(MIN_ZOOM_RANGE);

        let mut new_min = step_under_mouse - new_range * mouse_proportion;
        let mut new_max = step_under_mouse + new_range * (1.0 - mouse_proportion);

        // Tail anchor: when zooming in at far right, keep the data tail
        // visible.
        if direction == ZoomDirection::In
            && mouse_proportion >= TAIL_ANCHOR_MOUSE_THRESHOLD
            && self.x_max.is_finite()
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
            new_max = (new_min + new_range).min(dom_max);
        }
        if new_max > dom_max {
            new_max = dom_max;
            new_min = (new_max - new_range).max(dom_min);
        }

        self.model.set_view_x_range(new_min, new_max);
        self.sync_layout();
        self.user_view_min_x = new_min;
        self.user_view_max_x = new_max;
        self.is_zoomed = true;
        self.dirty = true;
    }

    /// Resets user zoom, restoring the auto-fitted X view.
    pub fn reset_zoom(&mut self) {
        if !self.is_zoomed {
            return;
        }
        self.is_zoomed = false;
        self.update_ranges();
        self.dirty = true;
    }

    pub fn is_zoomed(&self) -> bool {
        self.is_zoomed
    }

    /// Renders all series using braille patterns.
    pub fn draw(&mut self) {
        self.model.clear();

        let scale = self.y_scale;
        let unit = self.y_tick_unit;
        let max_label_w = self.max_x_label_width();

        self.model.draw_xy_axis();
        match self.x_axis_style {
            XAxisStyle::Step => {
                self.model
                    .draw_x_labels(&move |_, v| format_x_axis_tick(v, max_label_w));
            }
            XAxisStyle::Time => {
                let fmt = self.time_x_tick_formatter(max_label_w);
                self.model.draw_x_labels(&fmt);
            }
        }
        self.model
            .draw_y_labels(&move |_, v| format_y_tick(scale, unit, v));

        if self.model.graph_width() <= 0 || self.model.graph_height() <= 0 {
            self.dirty = false;
            return;
        }

        let start_x = if self.model.y_step() > 0 {
            self.model.origin().0 + 1
        } else {
            0
        };

        for i in 0..self.order.len() {
            let key = self.order[i].clone();
            self.draw_series(&key, start_x);
        }

        self.draw_inspection_overlay(start_x);
        self.dirty = false;
    }

    /// Renders a single series onto the canvas.
    fn draw_series(&mut self, key: &str, start_x: i32) {
        let graph_w = self.model.graph_width();
        let graph_h = self.model.graph_height();
        let view_min_x = self.model.view_min_x();
        let view_max_x = self.model.view_max_x();
        let view_min_y = self.model.view_min_y();
        let view_max_y = self.model.view_max_y();
        let eps = self.pixel_eps_x(view_max_x - view_min_x);
        let y_scale_mode = self.y_scale;

        let Some(s) = self.data.get(key) else { return };
        if s.x.is_empty() {
            return;
        }

        // Binary search for the visible window.
        let lb = s.x.partition_point(|&x| x < view_min_x);
        let ub = s.x.partition_point(|&x| x <= view_max_x + eps);
        if ub <= lb {
            return;
        }

        let mut grid = BrailleGrid::new(
            graph_w as usize,
            graph_h as usize,
            0.0,
            graph_w as f64,
            0.0,
            graph_h as f64,
        );

        let x_scale = graph_w as f64 / (view_max_x - view_min_x);
        let y_scale = graph_h as f64 / (view_max_y - view_min_y);

        let mut segments: Vec<Vec<(f64, f64)>> = Vec::new();
        let mut current: Vec<(f64, f64)> = Vec::new();

        for i in lb..ub {
            let Some(y_value) = scale_y_value(y_scale_mode, s.y[i]) else {
                if !current.is_empty() {
                    segments.push(std::mem::take(&mut current));
                }
                continue;
            };

            let x = (s.x[i] - view_min_x) * x_scale;
            let y = (y_value - view_min_y) * y_scale;

            if x < 0.0 || x > graph_w as f64 || y < 0.0 || y > graph_h as f64 {
                if !current.is_empty() {
                    segments.push(std::mem::take(&mut current));
                }
                continue;
            }
            current.push((x, y));
        }
        if !current.is_empty() {
            segments.push(current);
        }

        for points in &segments {
            if points.len() == 1 {
                let p = grid.grid_point(points[0].0, points[0].1);
                grid.set(p.0, p.1);
                continue;
            }
            for w in points.windows(2) {
                let gp1 = grid.grid_point(w[0].0, w[0].1);
                let gp2 = grid.grid_point(w[1].0, w[1].1);
                draw_line(&mut grid, gp1, gp2);
            }
        }

        let patterns = grid.braille_patterns();
        let style = s.style;
        self.draw_braille_patterns_occluded(start_x, 0, &patterns, style);
    }

    /// Draws braille runes with opaque compositing: replaces existing cells
    /// entirely, preventing color "spilling" when multiple series overlap.
    fn draw_braille_patterns_occluded(
        &mut self,
        px: i32,
        py: i32,
        patterns: &[Vec<char>],
        style: Style,
    ) {
        for (y, row) in patterns.iter().enumerate() {
            for (x, &r) in row.iter().enumerate() {
                if r as u32 != BRAILLE_BLOCK_OFFSET && super::braille::is_braille_pattern(r) {
                    self.model
                        .canvas
                        .set_cell(px + x as i32, py + y as i32, Cell { ch: r, style });
                }
            }
        }
    }

    /// Renders the data inspection hairline and legend.
    fn draw_inspection_overlay(&mut self, graph_start_x: i32) {
        if !self.inspection.active
            || self.model.graph_width() <= 0
            || self.model.graph_height() <= 0
        {
            return;
        }

        let graph_h = self.model.graph_height();
        let graph_w = self.model.graph_width();

        // Hairline X in canvas coordinates.
        let canvas_x = graph_start_x + self.inspection.mouse_x;

        // Vertical hairline.
        let line_style = theme::inspection_line_style();
        for y in 0..graph_h {
            self.model.canvas.set_cell(
                canvas_x,
                y,
                Cell {
                    ch: BOX_LIGHT_VERTICAL,
                    style: line_style,
                },
            );
        }

        // Anchor inspection at a single data X; show values for all series
        // at that X.
        let anchor_x = self.inspection.data_x;
        if !anchor_x.is_finite() || self.order.is_empty() {
            return;
        }

        struct LegendEntry {
            label: Vec<char>,
            block_style: Style,
        }

        let block_runes: &[char] = &['▬', '▬'];
        let legend_style = theme::inspection_legend_style();
        let mut entries: Vec<LegendEntry> = Vec::with_capacity(self.order.len());
        let mut max_label_width = 0usize;

        // Build entries in render order: topmost series first.
        for key in self.order.iter().rev() {
            let Some(s) = self.data.get(key) else {
                continue;
            };
            if s.x.is_empty() {
                continue;
            }

            let Some(idx) = nearest_index_for_x(&s.x, anchor_x) else {
                continue;
            };
            if idx >= s.y.len() {
                continue;
            }

            let y_val = s.y[idx];
            let label = self.format_inspection_label(key, s.x[idx], y_val);
            let label: Vec<char> = label.chars().collect();
            max_label_width = max_label_width.max(label.len());

            let block_style = s.style.patch(legend_style);
            entries.push(LegendEntry { label, block_style });
        }

        if entries.is_empty() {
            return;
        }

        // Don't draw more legend rows than we have vertical space for.
        entries.truncate(graph_h as usize);

        let total_legend_width = block_runes.len() as i32 + 1 + max_label_width as i32;
        let right_bound = graph_start_x + graph_w;

        // Prefer placing the legend to the right of the hairline if it fits.
        let mut legend_x = canvas_x + 1;
        if legend_x + total_legend_width >= right_bound {
            legend_x = canvas_x - 1 - total_legend_width;
        }
        if legend_x < graph_start_x {
            legend_x = graph_start_x;
        }

        // Vertically center the legend rows within the graph.
        let legend_height = entries.len() as i32;
        let mut legend_y_start = (graph_h / 2 - legend_height / 2).max(0);
        if legend_y_start + legend_height > graph_h {
            legend_y_start = (graph_h - legend_height).max(0);
        }

        // Render each legend row: colored block(s) + space + "X: Y".
        for (i, entry) in entries.iter().enumerate() {
            let y = legend_y_start + i as i32;
            let mut x = legend_x;

            for &r in block_runes {
                self.model.canvas.set_cell(
                    x,
                    y,
                    Cell {
                        ch: r,
                        style: entry.block_style,
                    },
                );
                x += 1;
            }
            self.model.canvas.set_cell(
                x,
                y,
                Cell {
                    ch: ' ',
                    style: legend_style,
                },
            );
            x += 1;
            for &ch in &entry.label {
                self.model.canvas.set_cell(
                    x,
                    y,
                    Cell {
                        ch,
                        style: legend_style,
                    },
                );
                x += 1;
            }
        }
    }

    fn format_inspection_label(&self, series_key: &str, x: f64, y: f64) -> String {
        match self.inspection_label_style {
            InspectionLabelStyle::Step => {
                format!("{}: {}", format_go_float(x), format_sig_figs(y, 4))
            }
            InspectionLabelStyle::Time(unit) => {
                let span = go_round(self.model.view_max_x() - self.model.view_min_x());
                let layout = if span >= 48.0 * 3600.0 {
                    "%b %-d %H:%M:%S"
                } else {
                    "%H:%M:%S"
                };
                let label = format!(
                    "{} {}",
                    timefmt::format_unix(go_round(x) as i64, layout),
                    unit.format(y)
                );
                if series_key.is_empty()
                    || series_key == crate::systemmetrics::DEFAULT_SYSTEM_METRIC_SERIES_NAME
                {
                    label
                } else {
                    format!("{series_key}: {label}")
                }
            }
        }
    }

    /// Builds the timestamp X tick formatter, capturing the view state.
    /// Ports TimeSeriesLineChart.formatXAxisTick.
    fn time_x_tick_formatter(&self, max_width: usize) -> impl Fn(i32, f64) -> String + use<> {
        const PREFERRED_TIME_LABEL_WIDTH: usize = 5; // len("15:04")

        let view_min = self.model.view_min_x();
        let view_max = self.model.view_max_x();
        let view_range = view_max - view_min;
        let span_secs = go_round(view_range);
        let graph_w = self.model.graph_width();
        let x_step = self.model.x_step();
        let pixel_eps = self.pixel_eps_x(view_range);

        // Endpoint mode: when regular labels don't fit, only label the ends.
        let endpoint_width = if graph_w <= 0 {
            0
        } else {
            (graph_w / 2).max(1) as usize
        };
        let use_endpoints =
            max_width > 0 && max_width < PREFERRED_TIME_LABEL_WIDTH && endpoint_width > 0;

        move |_i, v| {
            if !v.is_finite() {
                return String::new();
            }
            let layouts = timefmt::system_time_layouts(span_secs);
            let mut max_width = max_width;
            if use_endpoints {
                let is_endpoint = if view_range <= 0.0 {
                    true
                } else {
                    let eps = (pixel_eps * 2.0).max(view_range / x_step.max(1) as f64 * 0.25);
                    (v - view_min).abs() <= eps || (v - view_max).abs() <= eps
                };
                if !is_endpoint {
                    return String::new();
                }
                max_width = endpoint_width;
            }
            if max_width == 0 {
                max_width = PREFERRED_TIME_LABEL_WIDTH;
            }
            timefmt::fit_time_layouts(go_round(v) as i64, max_width, layouts)
        }
    }

    /// The data point nearest to mouse_x in the topmost series.
    fn find_nearest_data_point(&self, mouse_x: i32) -> Option<(f64, f64, usize)> {
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
        let best_idx = nearest_index_for_x(&s.x, target_x)?;
        Some((s.x[best_idx], s.y[best_idx], best_idx))
    }

    /// Approximately 1 horizontal pixel in X data units.
    pub(crate) fn pixel_eps_x(&self, x_range: f64) -> f64 {
        if self.model.graph_width() <= 0 || x_range <= 0.0 {
            return 0.0;
        }
        x_range / self.model.graph_width() as f64
    }

    /// Draws only if the chart is marked dirty.
    pub fn draw_if_needed(&mut self) {
        if self.dirty {
            self.draw();
        }
    }

    pub fn mark_dirty(&mut self) {
        self.dirty = true;
    }

    /// Updates the chart's canvas dimensions.
    pub fn resize(&mut self, width: usize, height: usize) {
        if self.model.width() == width && self.model.height() == height {
            return;
        }
        self.model.resize(width, height);
        self.sync_layout();
        self.update_ranges();
        self.dirty = true;
    }

    /// Minimizes canvas memory for off-screen charts.
    pub fn park(&mut self) {
        self.resize(PARKED_CANVAS_SIZE, PARKED_CANVAS_SIZE);
    }

    /// Sets the style for the named series, if present.
    pub fn set_series_style(&mut self, key: &str, style: Style) {
        if let Some(series) = self.data.get_mut(key) {
            series.style = style;
            self.dirty = true;
        }
    }

    /// Sets the style for the topmost series.
    pub fn set_graph_style(&mut self, style: Style) {
        if let Some(key) = self.order.last().cloned()
            && let Some(series) = self.data.get_mut(&key)
        {
            series.style = style;
        }
    }

    pub fn series_count(&self) -> usize {
        self.data.len()
    }

    pub fn series(&self, key: &str) -> Option<&Series> {
        self.data.get(key)
    }

    /// Removes a series by key and recomputes bounds.
    pub fn remove_series(&mut self, key: &str) {
        if self.data.remove(key).is_none() {
            return;
        }
        self.order.retain(|k| k != key);
        self.recompute_bounds();
        self.update_ranges();
        self.dirty = true;
    }

    /// Aggregates bounds from all series. O(n) in number of series.
    fn recompute_bounds(&mut self) {
        self.x_min = f64::INFINITY;
        self.x_max = f64::NEG_INFINITY;
        self.y_min = f64::INFINITY;
        self.y_max = f64::NEG_INFINITY;

        for s in self.data.values() {
            if s.x.is_empty() || s.y.is_empty() {
                continue;
            }
            let (x_min, x_max, y_min, y_max) = s.bounds();
            self.x_min = self.x_min.min(x_min);
            self.x_max = self.x_max.max(x_max);
            self.y_min = self.y_min.min(y_min);
            self.y_max = self.y_max.max(y_max);
        }
    }

    /// Snaps the crosshair to the sample nearest to `target_x`.
    fn snap_inspection_to_data_x(&mut self, target_x: f64) {
        let graph_w = self.model.graph_width();
        let x_range = self.model.view_max_x() - self.model.view_min_x();
        let view_min_x = self.model.view_min_x();

        let Some(s) = self.top_series() else { return };
        if !self.inspection.active || graph_w <= 0 || s.x.is_empty() || x_range <= 0.0 {
            return;
        }

        let Some(idx) = nearest_index_for_x(&s.x, target_x) else {
            return;
        };
        let (data_x, data_y) = (s.x[idx], s.y[idx]);

        self.inspection.data_x = data_x;
        self.inspection.data_y = data_y;

        // Pixel snap to the exact data X under the current view.
        let mouse_x_frac = (self.inspection.data_x - view_min_x) / x_range;
        let mouse_x = go_round(mouse_x_frac * graph_w as f64) as i32;
        self.inspection.mouse_x = mouse_x.clamp(0, graph_w - 1);
        self.dirty = true;
    }

    /// Activates inspection at the sample nearest to `target_x`.
    pub fn inspect_at_data_x(&mut self, target_x: f64) {
        let Some(s) = self.top_series() else { return };
        if s.x.is_empty() || self.model.graph_width() <= 0 {
            return;
        }
        self.inspection.active = true;
        self.snap_inspection_to_data_x(target_x);
    }

    /// Keeps the crosshair on the same data X after view/domain changes.
    pub(crate) fn refresh_inspection_after_view_change(&mut self) {
        if !self.inspection.active {
            return;
        }
        self.snap_inspection_to_data_x(self.inspection.data_x);
    }

    /// Begins inspection at the given mouse X position.
    pub fn start_inspection(&mut self, mouse_x: i32) {
        let Some(s) = self.top_series() else { return };
        if s.x.is_empty() || self.model.graph_width() <= 0 {
            return;
        }
        self.inspection.active = true;
        self.update_inspection(mouse_x);
    }

    /// Moves the crosshair to a new mouse X position.
    pub fn update_inspection(&mut self, mouse_x: i32) {
        if !self.inspection.active || self.model.graph_width() <= 0 {
            return;
        }
        // Clamp to the drawable graph area.
        self.inspection.mouse_x = mouse_x.clamp(0, self.model.graph_width() - 1);

        if let Some((data_x, _, _)) = self.find_nearest_data_point(mouse_x) {
            self.snap_inspection_to_data_x(data_x);
        }
        self.dirty = true;
    }

    /// Exits inspection mode.
    pub fn end_inspection(&mut self) {
        self.inspection = ChartInspection::default();
        self.dirty = true;
    }

    pub fn is_inspecting(&self) -> bool {
        self.inspection.active
    }

    /// The inspected point's coordinates.
    pub fn inspection_data(&self) -> (f64, f64, bool) {
        (
            self.inspection.data_x,
            self.inspection.data_y,
            self.inspection.active,
        )
    }

    /// Moves a series to the end of draw order (visually on top).
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

    /// The series keys in their current draw order (last is on top).
    pub fn draw_order(&self) -> &[String] {
        &self.order
    }
}

/// Formats a Y axis tick label, undoing log projection first.
fn format_y_tick(scale: AxisScaleMode, unit: Unit, v: f64) -> String {
    if !v.is_finite() {
        return String::new();
    }
    let mut raw = v;
    if scale == AxisScaleMode::Log {
        raw = 10f64.powf(v);
        if !raw.is_finite() {
            return String::new();
        }
    }
    unit.format(raw)
}

pub(crate) fn calculate_log_range(min_positive: f64, max_positive: f64) -> (f64, f64) {
    let min_log = min_positive.log10();
    let max_log = max_positive.log10();
    let padding = ((max_log - min_log) * 0.1).max(MIN_LOG_SCALE_MARGIN);
    (min_log - padding, max_log + padding)
}

fn scale_y_value(mode: AxisScaleMode, y: f64) -> Option<f64> {
    if !y.is_finite() {
        return None;
    }
    if mode != AxisScaleMode::Log {
        return Some(y);
    }
    if y <= 0.0 {
        return None;
    }
    Some(y.log10())
}

/// The index closest to `target_x` in a sorted slice.
fn nearest_index_for_x(xs: &[f64], target_x: f64) -> Option<usize> {
    if xs.is_empty() {
        return None;
    }
    let j = xs.partition_point(|&x| x < target_x);

    let mut best: Option<(usize, f64)> = None;
    for i in [j.wrapping_sub(1), j, j + 1] {
        if i >= xs.len() {
            continue;
        }
        let d = (xs[i] - target_x).abs();
        if best.is_none_or(|(_, bd)| d < bd) {
            best = Some((i, d));
        }
    }
    best.map(|(i, _)| i)
}

/// Formats a float like Go's `fmt.Sprintf("%v", x)`.
fn format_go_float(x: f64) -> String {
    if x == x.trunc() && x.abs() < 1e15 {
        format!("{}", x as i64)
    } else {
        format!("{x}")
    }
}

/// Truncates a title to fit `max_width`, adding an ellipsis if needed.
/// Tries to break at a separator for cleaner truncation.
pub fn truncate_title(title: &str, max_width: usize) -> String {
    if title.width() <= max_width {
        return title.to_string();
    }
    if max_width <= 3 {
        return "...".to_string();
    }

    let available_width = max_width - 3;

    // Find the largest byte offset whose prefix fits.
    let mut best_truncate_at = 0;
    for (i, _) in title.char_indices() {
        if title[..i].width() > available_width {
            break;
        }
        best_truncate_at = i;
    }

    if best_truncate_at > available_width / 2 {
        // Look for a separator near the truncation point for a cleaner break.
        for sep in ["/", "_", ".", "-", ":"] {
            if let Some(idx) = title[..best_truncate_at].rfind(sep)
                && idx > best_truncate_at * 2 / 3
            {
                best_truncate_at = idx + sep.len();
                break;
            }
        }
    }

    if best_truncate_at == 0 {
        best_truncate_at = 1;
    }
    while best_truncate_at < title.len() && !title.is_char_boundary(best_truncate_at) {
        best_truncate_at += 1;
    }
    if best_truncate_at > title.len() {
        best_truncate_at = title.len();
    }

    format!("{}...", &title[..best_truncate_at])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn metric(x: &[f64], y: &[f64]) -> MetricData {
        MetricData {
            x: x.to_vec(),
            y: y.to_vec(),
        }
    }

    #[test]
    fn add_data_updates_bounds_and_ranges() {
        let mut c = EpochLineChart::new("loss");
        c.resize(40, 10);
        c.add_data("loss", &metric(&[0.0, 1.0, 2.0], &[3.0, 2.0, 1.0]));
        assert_eq!(c.series_count(), 1);
        // X domain padded to the default max.
        assert_eq!(c.model.max_x(), DEFAULT_MAX_X);
        // Y range padded by 10%.
        assert!(c.model.view_min_y() < 1.0);
        assert!(c.model.view_max_y() > 3.0);
        c.draw();
    }

    #[test]
    fn log_scale_requires_positive_values() {
        let mut c = EpochLineChart::new("m");
        c.resize(40, 10);
        c.add_data("m", &metric(&[0.0, 1.0], &[-1.0, -2.0]));
        assert!(!c.set_y_scale(AxisScaleMode::Log));
        c.add_data("m", &metric(&[2.0], &[10.0]));
        assert!(c.set_y_scale(AxisScaleMode::Log));
        assert!(c.is_log_y());
    }

    #[test]
    fn zoom_preserves_view() {
        let mut c = EpochLineChart::new("m");
        c.resize(60, 12);
        let xs: Vec<f64> = (0..100).map(|i| i as f64).collect();
        let ys: Vec<f64> = (0..100).map(|i| (i as f64).sin()).collect();
        c.add_data("m", &metric(&xs, &ys));
        let before = c.model.view_max_x() - c.model.view_min_x();
        c.handle_zoom(ZoomDirection::In, c.model.graph_width() / 2);
        let after = c.model.view_max_x() - c.model.view_min_x();
        assert!(after < before);
        assert!(c.is_zoomed());
        // New data does not reset the zoomed view.
        c.add_data("m", &metric(&[100.0], &[0.5]));
        let after2 = c.model.view_max_x() - c.model.view_min_x();
        assert!((after - after2).abs() < 1e-9);
    }

    #[test]
    fn truncate_title_basic() {
        assert_eq!(truncate_title("short", 10), "short");
        assert_eq!(truncate_title("abcdefghij", 3), "...");
        let t = truncate_title("train/metrics/loss_value", 15);
        assert!(t.ends_with("..."));
        assert!(t.width() <= 15);
    }

    #[test]
    fn nearest_index() {
        let xs = [0.0, 10.0, 20.0];
        assert_eq!(nearest_index_for_x(&xs, -5.0), Some(0));
        assert_eq!(nearest_index_for_x(&xs, 14.0), Some(1));
        assert_eq!(nearest_index_for_x(&xs, 16.0), Some(2));
        assert_eq!(nearest_index_for_x(&xs, 100.0), Some(2));
    }
}
