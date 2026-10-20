//! French fries chart: one row per series with the visible time window
//! compressed into color-coded buckets, producing a compact heatmap.

use std::collections::HashMap;

use ratatui::style::{Modifier, Style};
use unicode_width::UnicodeWidthStr;

use crate::systemmetrics::{DEFAULT_SYSTEM_METRIC_SERIES_NAME, MetricDef};
use crate::theme::{
    self, Adaptive, BOX_LIGHT_VERTICAL, DEFAULT_FRENCH_FRIES_COLOR_SCHEME, EM_DASH,
};

use super::braille::go_round;
use super::canvas::{Canvas, Cell};
use super::epoch::{PARKED_CANVAS_SIZE, truncate_title};
use super::timefmt::{compact_duration, fit_time_layouts, system_time_layouts};

const FRENCH_FRIES_CELL: char = '█';

struct Sample {
    timestamp: i64,
    values: HashMap<String, f64>,
}

#[derive(Default)]
struct Inspection {
    active: bool,
    mouse_x: i32,
    data_x: f64,
}

struct RowBand {
    series_name: String,
    label: String,
    start_y: usize,
    height: usize,
}

impl RowBand {
    fn center_y(&self) -> usize {
        if self.height == 0 {
            return self.start_y;
        }
        self.start_y + (self.height - 1) / 2
    }
}

#[derive(Default)]
struct Layout {
    label_width: usize,
    plot_start_x: usize,
    plot_width: usize,
    plot_height: usize,
    /// Row of the time axis, or None.
    time_axis_y: Option<usize>,
    max_visible_rows: usize,
    bands: Vec<RowBand>,
}

#[derive(Clone, Copy, Default)]
struct BucketCell {
    timestamp: i64,
    value: f64,
    ok: bool,
}

/// Heatmap-style chart for multi-series system metrics.
pub struct FrenchFriesChart {
    def: &'static MetricDef,

    width: usize,
    height: usize,

    /// Full observed history so the chart can reuse the same windowing and
    /// zoom semantics as the underlying line chart.
    samples: Vec<Sample>,

    series: std::collections::HashSet<String>,

    last_update: i64,
    view_min_x: f64,
    view_max_x: f64,
    view_ready: bool,

    inspection: Inspection,

    dirty: bool,
    canvas: Canvas,

    colors: Vec<Adaptive>,
}

pub struct FrenchFriesChartParams {
    pub width: usize,
    pub height: usize,
    pub def: &'static MetricDef,
    pub colors: Vec<Adaptive>,
    /// Current time in unix seconds.
    pub now: i64,
}

impl FrenchFriesChart {
    pub fn new(params: FrenchFriesChartParams) -> Self {
        let colors = if params.colors.is_empty() {
            theme::french_fries_colors(DEFAULT_FRENCH_FRIES_COLOR_SCHEME).to_vec()
        } else {
            params.colors
        };

        let mut chart = Self {
            def: params.def,
            width: 0,
            height: 0,
            samples: Vec::new(),
            series: Default::default(),
            last_update: params.now,
            view_min_x: 0.0,
            view_max_x: 0.0,
            view_ready: false,
            inspection: Inspection::default(),
            dirty: true,
            canvas: Canvas::new(0, 0),
            colors,
        };
        chart.resize(params.width, params.height);
        chart
    }

    pub fn def(&self) -> &'static MetricDef {
        self.def
    }

    pub fn title(&self) -> String {
        self.def.title()
    }

    pub fn title_detail(&self) -> String {
        let total = self.sorted_series_names().len();
        if total <= 1 {
            return String::new();
        }

        let layout = self.layout();
        if layout.max_visible_rows == 0 || total <= layout.max_visible_rows {
            return format!("[{total}]");
        }

        summarize_series(&self.visible_series_names(layout.max_visible_rows), total)
    }

    /// The rendered canvas (drawing first if dirty).
    pub fn canvas(&mut self) -> &Canvas {
        self.draw_if_needed();
        &self.canvas
    }

    /// Minimizes memory for off-screen charts by shrinking to 1x1.
    pub fn park(&mut self) {
        self.resize(PARKED_CANVAS_SIZE, PARKED_CANVAS_SIZE);
    }

    pub fn resize(&mut self, width: usize, height: usize) {
        if self.width == width && self.height == height {
            return;
        }
        self.width = width;
        self.height = height;
        self.dirty = true;
    }

    pub fn draw_if_needed(&mut self) {
        if self.dirty {
            self.draw();
        }
    }

    pub fn add_data_point(&mut self, series_name: &str, timestamp: i64, value: f64) {
        let series_name = if series_name.is_empty() {
            DEFAULT_SYSTEM_METRIC_SERIES_NAME
        } else {
            series_name
        };
        self.series.insert(series_name.to_string());

        if self.samples.last().is_none_or(|s| s.timestamp != timestamp) {
            self.samples.push(Sample {
                timestamp,
                values: HashMap::new(),
            });
        }
        self.samples
            .last_mut()
            .expect("sample just ensured")
            .values
            .insert(series_name.to_string(), value);
        self.last_update = timestamp;

        if !self.view_ready {
            self.set_default_view_window();
        }
        self.dirty = true;
    }

    pub fn graph_width(&self) -> usize {
        self.layout().plot_width
    }

    pub fn graph_height(&self) -> usize {
        self.layout().plot_height
    }

    pub fn graph_start_x(&self) -> usize {
        1 + self.layout().plot_start_x
    }

    pub fn last_update(&self) -> i64 {
        self.last_update
    }

    pub fn view_mode_label(&self) -> String {
        let (view_min_x, view_max_x) = self.effective_view_window_readonly();
        let span = view_max_x - view_min_x;
        if span > 0.0 {
            return format!("window {}", compact_duration(go_round(span) as i64));
        }
        let visible = self.samples.len().min(self.graph_width());
        if visible == 0 {
            return "heatmap".to_string();
        }
        format!("heatmap {visible} samples")
    }

    pub fn scale_label(&self) -> &'static str {
        "heatmap"
    }

    /// Updates the time window used to bucket samples into columns.
    pub fn set_view_window(&mut self, min_x: f64, max_x: f64) {
        if !min_x.is_finite() || !max_x.is_finite() || max_x <= min_x {
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
            self.inspect_at_data_x(self.inspection.data_x);
        }
    }

    pub fn start_inspection_at(&mut self, mouse_x: i32) {
        if self.graph_width() == 0 || self.graph_height() == 0 {
            return;
        }
        self.inspection.active = true;
        self.update_inspection_at(mouse_x);
    }

    pub fn update_inspection_at(&mut self, mouse_x: i32) {
        if !self.inspection.active {
            return;
        }

        let layout = self.layout();
        if layout.plot_width == 0 || layout.plot_height == 0 || layout.bands.is_empty() {
            return;
        }

        self.inspection.mouse_x = mouse_x.clamp(0, layout.plot_width as i32 - 1);
        self.inspection.data_x = self.data_x_for_mouse(self.inspection.mouse_x, layout.plot_width);
        self.dirty = true;
    }

    pub fn end_inspection(&mut self) {
        self.inspection = Inspection::default();
        self.dirty = true;
    }

    pub fn is_inspecting(&self) -> bool {
        self.inspection.active
    }

    pub fn inspect_at_data_x(&mut self, target_x: f64) {
        let layout = self.layout();
        if layout.plot_width == 0 || layout.plot_height == 0 || layout.bands.is_empty() {
            return;
        }
        self.inspection.active = true;
        self.inspection.mouse_x = self.bucket_for_data_x(target_x, layout.plot_width) as i32;
        self.inspection.data_x = target_x;
        self.dirty = true;
    }

    pub fn inspection_data(&self) -> (f64, f64, bool) {
        (self.inspection.data_x, 0.0, self.inspection.active)
    }

    fn draw(&mut self) {
        self.canvas.resize(self.width, self.height);
        self.canvas.clear();
        if self.width == 0 || self.height == 0 {
            self.dirty = false;
            return;
        }
        // Initialize all cells to spaces (the Go version renders a full
        // rectangle of characters).
        for y in 0..self.height as i32 {
            for x in 0..self.width as i32 {
                self.canvas.set_cell(
                    x,
                    y,
                    Cell {
                        ch: ' ',
                        style: Style::new(),
                    },
                );
            }
        }

        let layout = self.layout();
        let bucketed = self.bucketed_series(&layout);
        let selected_bucket = if self.inspection.active && layout.plot_width > 0 {
            Some(
                self.inspection
                    .mouse_x
                    .clamp(0, layout.plot_width as i32 - 1) as usize,
            )
        } else {
            None
        };

        for band in &layout.bands {
            let cells = &bucketed[&band.series_name];
            for y in band.start_y..band.start_y + band.height {
                for (x, bucket) in cells.iter().enumerate().take(layout.plot_width) {
                    let cell = if bucket.ok {
                        self.color_for_value(bucket.value)
                    } else {
                        Cell {
                            ch: ' ',
                            style: Style::new(),
                        }
                    };
                    self.canvas
                        .set_cell((layout.plot_start_x + x) as i32, y as i32, cell);
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

    fn render_band_label(&mut self, layout: &Layout, band: &RowBand) {
        if layout.label_width == 0 || band.label.is_empty() {
            return;
        }
        let row = band.center_y();
        let mut label = band.label.clone();
        if label.width() > layout.label_width - 1 {
            label = truncate_title(&label, layout.label_width - 1);
        }
        let start = (layout.label_width as i32 - 1 - label.width() as i32).max(0);
        for (i, ch) in label.chars().enumerate() {
            let x = start + i as i32;
            if x >= layout.label_width as i32 - 1 {
                break;
            }
            self.canvas.set_cell(
                x,
                row as i32,
                Cell {
                    ch,
                    style: Style::new(),
                },
            );
        }
    }

    fn render_inspection_hairline(&mut self, layout: &Layout, selected_bucket: Option<usize>) {
        let Some(bucket) = selected_bucket else {
            return;
        };
        if !self.inspection.active || bucket >= layout.plot_width {
            return;
        }

        let x = (layout.plot_start_x + bucket) as i32;
        let style = theme::inspection_line_style();
        for y in 0..layout.plot_height {
            self.canvas.set_cell(
                x,
                y as i32,
                Cell {
                    ch: BOX_LIGHT_VERTICAL,
                    style,
                },
            );
        }
    }

    fn render_inspection_labels(
        &mut self,
        layout: &Layout,
        bucketed: &HashMap<String, Vec<BucketCell>>,
    ) {
        if !self.inspection.active || layout.plot_width == 0 || layout.plot_height == 0 {
            return;
        }
        let bucket = self
            .inspection
            .mouse_x
            .clamp(0, layout.plot_width as i32 - 1) as usize;

        let mut labels: HashMap<&str, String> = HashMap::with_capacity(layout.bands.len());
        let mut max_label_width = 0usize;
        for band in &layout.bands {
            let label = match bucketed.get(&band.series_name) {
                Some(cells) => self.inspection_value_label(&band.series_name, cells[bucket]),
                None => EM_DASH.to_string(),
            };
            max_label_width = max_label_width.max(label.width());
            labels.insert(band.series_name.as_str(), label);
        }
        if max_label_width == 0 {
            return;
        }

        let legend_style = theme::inspection_legend_style();
        let start_x = selected_label_start_x(bucket, layout.plot_width, max_label_width);
        for band in &layout.bands {
            let row = band.center_y() as i32;
            let mut label = labels[band.series_name.as_str()].clone();
            if label.width() > max_label_width {
                label = truncate_title(&label, max_label_width);
            }
            for (i, ch) in label.chars().enumerate() {
                let x = (layout.plot_start_x + start_x + i) as i32;
                if x < layout.plot_start_x as i32
                    || x >= (layout.plot_start_x + layout.plot_width) as i32
                {
                    continue;
                }
                self.canvas.set_cell(
                    x,
                    row,
                    Cell {
                        ch,
                        style: legend_style,
                    },
                );
            }
        }
    }

    fn inspection_value_label(&self, series_name: &str, bucket: BucketCell) -> String {
        let value_label = if bucket.ok {
            self.def.unit.format(bucket.value)
        } else {
            EM_DASH.to_string()
        };

        let series_label = compact_system_metric_series_label(series_name);
        if series_label.is_empty() {
            value_label
        } else {
            format!("{series_label}: {value_label}")
        }
    }

    fn render_time_labels(&mut self, layout: &Layout) {
        let Some(y) = layout.time_axis_y else { return };
        if layout.plot_width == 0 || self.height == 0 {
            return;
        }
        let (view_min_x, view_max_x) = self.effective_view_window_readonly();
        if view_max_x <= view_min_x {
            return;
        }

        let span = go_round(view_max_x - view_min_x);
        let layouts = system_time_layouts(span);

        let min_label = fit_time_layouts(go_round(view_min_x) as i64, layout.plot_width, layouts);
        let max_label = fit_time_layouts(go_round(view_max_x) as i64, layout.plot_width, layouts);
        let mut labels = vec![
            (min_label, 0usize),
            (
                max_label.clone(),
                (layout.plot_width as i32 - max_label.width() as i32).max(0) as usize,
            ),
        ];

        let mid_x = (view_min_x + view_max_x) / 2.0;
        let mid_text = fit_time_layouts(go_round(mid_x) as i64, layout.plot_width, layouts);
        let mid_pos = (layout.plot_width as i32 / 2 - mid_text.width() as i32 / 2).max(0) as usize;
        if !mid_text.is_empty() && layout.plot_width >= mid_text.width() * 3 {
            labels.push((mid_text, mid_pos));
        }

        for (text, pos) in labels {
            for (i, ch) in text.chars().enumerate() {
                let x = (layout.plot_start_x + pos + i) as i32;
                if x < layout.plot_start_x as i32 || x >= self.width as i32 {
                    continue;
                }
                self.canvas.set_cell(
                    x,
                    y as i32,
                    Cell {
                        ch,
                        style: Style::new(),
                    },
                );
            }
        }
    }

    fn render_inspection_time_label(
        &mut self,
        layout: &Layout,
        bucketed: &HashMap<String, Vec<BucketCell>>,
    ) {
        if !self.inspection.active || layout.plot_width == 0 {
            return;
        }
        let Some(time_axis_y) = layout.time_axis_y else {
            return;
        };

        let bucket = self
            .inspection
            .mouse_x
            .clamp(0, layout.plot_width as i32 - 1) as usize;
        let mut data_x = self.inspection.data_x;
        if let Some(ts) = bucket_timestamp(bucketed, bucket) {
            data_x = ts as f64;
        }

        let (view_min_x, view_max_x) = self.effective_view_window_readonly();
        let span = go_round(view_max_x - view_min_x);
        let label = fit_time_layouts(
            go_round(data_x) as i64,
            layout.plot_width,
            system_time_layouts(span),
        );
        if label.is_empty() {
            return;
        }

        let bold = Style::new().add_modifier(Modifier::BOLD);
        let start_x = selected_label_start_x(bucket, layout.plot_width, label.width());
        for (i, ch) in label.chars().enumerate() {
            let x = (layout.plot_start_x + start_x + i) as i32;
            if x < layout.plot_start_x as i32
                || x >= (layout.plot_start_x + layout.plot_width) as i32
            {
                continue;
            }
            self.canvas
                .set_cell(x, time_axis_y as i32, Cell { ch, style: bold });
        }
    }

    fn layout(&self) -> Layout {
        let mut layout = Layout::default();
        if self.width == 0 || self.height == 0 {
            return layout;
        }

        let mut time_axis_rows = 0;
        if self.height >= 2 {
            time_axis_rows = 1;
            layout.time_axis_y = Some(self.height - 1);
        }
        layout.plot_height = self.height.saturating_sub(time_axis_rows);
        layout.max_visible_rows = layout.plot_height;
        let visible_series = self.visible_series_names(layout.max_visible_rows);

        let mut max_label_width = 0;
        let labels: Vec<String> = visible_series
            .iter()
            .map(|name| compact_system_metric_series_label(name))
            .collect();
        for label in &labels {
            max_label_width = max_label_width.max(label.width());
        }
        if max_label_width > 0 && self.width >= max_label_width + 2 {
            layout.label_width = max_label_width + 1;
        }
        layout.plot_start_x = layout.label_width;
        layout.plot_width = self.width.saturating_sub(layout.plot_start_x);
        if layout.plot_width == 0 {
            layout.label_width = 0;
            layout.plot_start_x = 0;
            layout.plot_width = self.width;
        }

        if visible_series.is_empty() || layout.plot_height == 0 {
            return layout;
        }

        let base_band_height = (layout.plot_height / visible_series.len()).max(1);
        let extra_rows = layout
            .plot_height
            .saturating_sub(visible_series.len() * base_band_height);
        let mut y = 0;
        for (i, name) in visible_series.iter().enumerate() {
            let mut band_height = base_band_height;
            if i < extra_rows {
                band_height += 1;
            }
            layout.bands.push(RowBand {
                series_name: name.clone(),
                label: labels[i].clone(),
                start_y: y,
                height: band_height,
            });
            y += band_height;
        }
        layout
    }

    fn visible_sample_range(&self, view_min_x: f64, view_max_x: f64) -> (usize, usize) {
        let start = self
            .samples
            .partition_point(|s| (s.timestamp as f64) < view_min_x);
        let end = self
            .samples
            .partition_point(|s| s.timestamp as f64 <= view_max_x);
        (start, end)
    }

    fn bucketed_series(&self, layout: &Layout) -> HashMap<String, Vec<BucketCell>> {
        let mut bucketed: HashMap<String, Vec<BucketCell>> =
            HashMap::with_capacity(layout.bands.len());
        for band in &layout.bands {
            bucketed.insert(
                band.series_name.clone(),
                vec![BucketCell::default(); layout.plot_width],
            );
        }
        if layout.plot_width == 0 {
            return bucketed;
        }

        let (view_min_x, view_max_x) = self.effective_view_window_readonly();
        if view_max_x <= view_min_x {
            return bucketed;
        }

        // Accumulate sum and count per bucket so the final value is an
        // average. Averaging keeps the display stable when a single sample
        // shifts between neighbouring buckets on a small view-window change.
        #[derive(Clone, Copy, Default)]
        struct Accum {
            sum: f64,
            count: usize,
            timestamp: i64,
        }
        let mut accums: HashMap<&str, Vec<Accum>> = HashMap::with_capacity(layout.bands.len());
        for band in &layout.bands {
            accums.insert(
                band.series_name.as_str(),
                vec![Accum::default(); layout.plot_width],
            );
        }

        let (start, end) = self.visible_sample_range(view_min_x, view_max_x);
        for sample in &self.samples[start..end] {
            let ts = sample.timestamp as f64;
            let bucket = self.bucket_for_data_x(ts, layout.plot_width);
            for (series_name, value) in &sample.values {
                let Some(a) = accums.get_mut(series_name.as_str()) else {
                    continue;
                };
                a[bucket].sum += value;
                a[bucket].count += 1;
                if sample.timestamp > a[bucket].timestamp {
                    a[bucket].timestamp = sample.timestamp;
                }
            }
        }

        for (series_name, cells) in bucketed.iter_mut() {
            let a = &accums[series_name.as_str()];
            for (i, cell) in cells.iter_mut().enumerate() {
                if a[i].count > 0 {
                    *cell = BucketCell {
                        timestamp: a[i].timestamp,
                        value: a[i].sum / a[i].count as f64,
                        ok: true,
                    };
                }
            }
        }

        bucketed
    }

    fn color_for_value(&self, value: f64) -> Cell {
        if !value.is_finite() || self.colors.is_empty() {
            return Cell {
                ch: ' ',
                style: Style::new(),
            };
        }

        let mut min_y = self.def.min_y;
        let mut max_y = self.def.max_y;
        if max_y <= min_y {
            min_y = 0.0;
            max_y = 100.0;
        }

        let normalized = ((value - min_y) / (max_y - min_y)).clamp(0.0, 1.0);
        let idx = go_round(normalized * (self.colors.len() - 1) as f64) as usize;
        Cell {
            ch: FRENCH_FRIES_CELL,
            style: Style::new().fg(self.colors[idx].color()),
        }
    }

    fn set_default_view_window(&mut self) {
        let Some(first) = self.samples.first() else {
            self.view_ready = false;
            return;
        };
        let min_x = first.timestamp as f64;
        let mut max_x = self.samples.last().expect("non-empty").timestamp as f64;
        if max_x <= min_x {
            max_x = min_x + 1.0;
        }
        self.view_min_x = min_x;
        self.view_max_x = max_x;
        self.view_ready = true;
    }

    /// The effective view window without mutating state (falls back to the
    /// full sample range when no window is set).
    fn effective_view_window_readonly(&self) -> (f64, f64) {
        if self.view_ready && self.view_max_x > self.view_min_x {
            return (self.view_min_x, self.view_max_x);
        }
        let Some(first) = self.samples.first() else {
            return (0.0, 0.0);
        };
        let min_x = first.timestamp as f64;
        let mut max_x = self.samples.last().expect("non-empty").timestamp as f64;
        if max_x <= min_x {
            max_x = min_x + 1.0;
        }
        (min_x, max_x)
    }

    fn data_x_for_mouse(&self, mouse_x: i32, plot_width: usize) -> f64 {
        let (view_min_x, view_max_x) = self.effective_view_window_readonly();
        if plot_width <= 1 || view_max_x <= view_min_x {
            return view_min_x;
        }
        // Map the mouse position to the center of the corresponding bucket.
        let bucket_width = (view_max_x - view_min_x) / plot_width as f64;
        let clamped = mouse_x.clamp(0, plot_width as i32 - 1) as f64;
        view_min_x + (clamped + 0.5) * bucket_width
    }

    fn bucket_for_data_x(&self, data_x: f64, plot_width: usize) -> usize {
        let (view_min_x, view_max_x) = self.effective_view_window_readonly();
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
        (bucket.max(0) as usize).min(plot_width - 1)
    }

    fn sorted_series_names(&self) -> Vec<String> {
        let mut names: Vec<String> = self.series.iter().cloned().collect();
        names.sort_by(|a, b| system_metric_series_cmp(a, b));
        names
    }

    fn visible_series_names(&self, max_rows: usize) -> Vec<String> {
        let names = self.sorted_series_names();
        if max_rows == 0 || names.is_empty() {
            return Vec::new();
        }
        if names.len() <= max_rows {
            return names;
        }
        if max_rows == 1 {
            return names[..1].to_vec();
        }

        let mut visible = names[..max_rows - 1].to_vec();
        visible.push(names[names.len() - 1].clone());
        visible
    }
}

fn selected_label_start_x(mouse_x: usize, plot_width: usize, label_width: usize) -> usize {
    if label_width == 0 || plot_width == 0 {
        return 0;
    }
    let mut start = mouse_x as i32 + 1;
    if start as usize + label_width > plot_width {
        start = (mouse_x as i32 - label_width as i32).max(0);
    }
    (start.max(0) as usize).min(plot_width.saturating_sub(label_width))
}

fn bucket_timestamp(bucketed: &HashMap<String, Vec<BucketCell>>, bucket: usize) -> Option<i64> {
    let mut best: Option<i64> = None;
    for cells in bucketed.values() {
        let Some(cell) = cells.get(bucket) else {
            continue;
        };
        if !cell.ok {
            continue;
        }
        if best.is_none_or(|b| cell.timestamp > b) {
            best = Some(cell.timestamp);
        }
    }
    best
}

fn summarize_series(names: &[String], total: usize) -> String {
    if total <= names.len() {
        return format!("[{total}]");
    }

    let labels: Vec<String> = if names.len() <= 3 {
        names
            .iter()
            .map(|n| compact_system_metric_series_label(n))
            .collect()
    } else {
        vec![
            compact_system_metric_series_label(&names[0]),
            compact_system_metric_series_label(&names[1]),
            "...".to_string(),
            compact_system_metric_series_label(&names[names.len() - 1]),
        ]
    };

    format!("[{}/{}]", labels.join(","), total)
}

/// Compacts a series label; indexed series show just their index.
pub fn compact_system_metric_series_label(name: &str) -> String {
    if name.is_empty() || name == DEFAULT_SYSTEM_METRIC_SERIES_NAME {
        return String::new();
    }
    let fields: Vec<&str> = name.split_whitespace().collect();
    let Some(last) = fields.last() else {
        return name.to_string();
    };
    if last.parse::<i64>().is_ok() {
        return last.to_string();
    }
    name.to_string()
}

/// Orders series by (prefix, numeric index) when both are indexed,
/// otherwise lexicographically.
pub fn system_metric_series_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    let sa = split_series_index(a);
    let sb = split_series_index(b);
    if let (Some((ap, ai)), Some((bp, bi))) = (sa, sb)
        && ap == bp
    {
        return ai.cmp(&bi);
    }
    a.cmp(b)
}

fn split_series_index(name: &str) -> Option<(String, i64)> {
    let fields: Vec<&str> = name.split_whitespace().collect();
    if fields.len() < 2 {
        return None;
    }
    let index: i64 = fields[fields.len() - 1].parse().ok()?;
    Some((fields[..fields.len() - 1].join(" "), index))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::systemmetrics::match_metric_def;

    #[test]
    fn series_ordering() {
        let mut names = vec![
            "GPU 10".to_string(),
            "GPU 2".to_string(),
            "GPU 1".to_string(),
            "Other".to_string(),
        ];
        names.sort_by(|a, b| system_metric_series_cmp(a, b));
        assert_eq!(names, ["GPU 1", "GPU 2", "GPU 10", "Other"]);
    }

    #[test]
    fn compact_labels() {
        assert_eq!(compact_system_metric_series_label("GPU 3"), "3");
        assert_eq!(compact_system_metric_series_label("Default"), "");
        assert_eq!(
            compact_system_metric_series_label("nvme0n1 read"),
            "nvme0n1 read"
        );
    }

    #[test]
    fn draws_buckets() {
        let def = match_metric_def("gpu.0.gpu").unwrap();
        let mut c = FrenchFriesChart::new(FrenchFriesChartParams {
            width: 40,
            height: 8,
            def,
            colors: Vec::new(),
            now: 1_700_000_000,
        });
        for i in 0..50 {
            c.add_data_point("GPU 0", 1_700_000_000 + i, (i % 100) as f64);
            c.add_data_point("GPU 1", 1_700_000_000 + i, ((i * 2) % 100) as f64);
        }
        assert_eq!(c.title_detail(), "[2]");
        c.draw_if_needed();
        assert_eq!(c.canvas.width(), 40);
    }
}
