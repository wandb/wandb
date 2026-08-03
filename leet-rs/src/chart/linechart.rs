//! Core line chart model: canvas + axes + coordinate ranges.
//!
//! A port of the parts of ntcharts' `linechart.Model` used by LEET.

use ratatui::style::Style;

use super::canvas::{Canvas, Cell};

pub const LINE_HORIZONTAL: char = '─';
pub const LINE_VERTICAL: char = '│';
pub const LINE_UP_RIGHT: char = '└';

/// Label formatter: (tick index in graph columns/rows, data value) -> label.
pub type LabelFormatter<'a> = &'a dyn Fn(i32, f64) -> String;

/// Chart origin and graph geometry plus X/Y data and view ranges.
#[derive(Debug)]
pub struct LineChartModel {
    pub canvas: Canvas,

    x_step: i32,
    y_step: i32,

    min_x: f64,
    max_x: f64,
    min_y: f64,
    max_y: f64,

    view_min_x: f64,
    view_max_x: f64,
    view_min_y: f64,
    view_max_y: f64,

    origin_x: i32,
    origin_y: i32,
    graph_width: i32,
    graph_height: i32,

    pub axis_style: Style,
    pub label_style: Style,
}

impl LineChartModel {
    #[allow(clippy::too_many_arguments)] // Mirrors ntcharts' constructor.
    pub fn new(
        w: usize,
        h: usize,
        min_x: f64,
        max_x: f64,
        min_y: f64,
        max_y: f64,
        x_step: i32,
        y_step: i32,
    ) -> Self {
        Self {
            canvas: Canvas::new(w, h),
            x_step,
            y_step,
            min_x,
            max_x,
            min_y,
            max_y,
            view_min_x: min_x,
            view_max_x: max_x,
            view_min_y: min_y,
            view_max_y: max_y,
            origin_x: 0,
            origin_y: 0,
            graph_width: 0,
            graph_height: 0,
            axis_style: Style::new(),
            label_style: Style::new(),
        }
    }

    pub fn width(&self) -> usize {
        self.canvas.width()
    }

    pub fn height(&self) -> usize {
        self.canvas.height()
    }

    pub fn graph_width(&self) -> i32 {
        self.graph_width
    }

    pub fn graph_height(&self) -> i32 {
        self.graph_height
    }

    /// Canvas coordinates of the axes' origin.
    pub fn origin(&self) -> (i32, i32) {
        (self.origin_x, self.origin_y)
    }

    pub fn x_step(&self) -> i32 {
        self.x_step
    }

    pub fn y_step(&self) -> i32 {
        self.y_step
    }

    pub fn min_x(&self) -> f64 {
        self.min_x
    }

    pub fn max_x(&self) -> f64 {
        self.max_x
    }

    pub fn view_min_x(&self) -> f64 {
        self.view_min_x
    }

    pub fn view_max_x(&self) -> f64 {
        self.view_max_x
    }

    pub fn view_min_y(&self) -> f64 {
        self.view_min_y
    }

    pub fn view_max_y(&self) -> f64 {
        self.view_max_y
    }

    pub fn clear(&mut self) {
        self.canvas.clear();
    }

    pub fn resize(&mut self, w: usize, h: usize) {
        self.canvas.resize(w, h);
    }

    /// Updates the expected (domain) X range.
    pub fn set_x_range(&mut self, min: f64, max: f64) {
        self.min_x = min;
        self.max_x = max;
    }

    /// Updates the expected (domain) Y range.
    pub fn set_y_range(&mut self, min: f64, max: f64) {
        self.min_y = min;
        self.max_y = max;
    }

    /// Updates the displayed X range, bounded by the domain.
    pub fn set_view_x_range(&mut self, min: f64, max: f64) -> bool {
        let v_min = self.min_x.max(min);
        let v_max = self.max_x.min(max);
        if v_min < v_max {
            self.view_min_x = v_min;
            self.view_max_x = v_max;
            return true;
        }
        false
    }

    /// Updates the displayed Y range, bounded by the domain.
    pub fn set_view_y_range(&mut self, min: f64, max: f64) -> bool {
        let v_min = self.min_y.max(min);
        let v_max = self.max_y.min(max);
        if v_min < v_max {
            self.view_min_y = v_min;
            self.view_max_y = v_max;
            return true;
        }
        false
    }

    /// Recomputes origin and graph dimensions. Must be called after canvas
    /// resizes or view Y range changes, before drawing or reading geometry.
    ///
    /// `y_fmt` is consulted to measure the widest Y tick label.
    pub fn update_graph_sizes(&mut self, y_fmt: LabelFormatter) {
        let w = self.canvas.width() as i32;
        let h = self.canvas.height() as i32;

        let mut origin = (0, h - 1);
        let mut g_width = w;
        let mut g_height = h;

        if self.x_step > 0 {
            // Last 2 rows are used by the X axis and its tick values.
            origin.1 -= 1;
            g_height -= 2;
        }
        if self.y_step > 0 {
            // Reserve space left of the Y axis for the widest tick label.
            let mut last_val = String::new();
            let mut value_len = 0i32;
            let range = self.view_max_y - self.view_min_y;
            let increment = range / g_height as f64;
            let mut i = 0;
            while i <= g_height {
                let v = self.view_min_y + increment * i as f64;
                let s = y_fmt(i, v);
                if last_val != s {
                    value_len = value_len.max(s.chars().count() as i32);
                    last_val = s;
                }
                i += self.y_step;
            }
            origin.0 += value_len;
            g_width -= value_len + 1;
        }

        self.origin_x = origin.0;
        self.origin_y = origin.1;
        self.graph_width = g_width;
        self.graph_height = g_height;
    }

    /// Draws the X and Y axes (corner, vertical, horizontal lines).
    pub fn draw_xy_axis(&mut self) {
        let style = self.axis_style;
        if self.y_step > 0 && self.x_step > 0 {
            self.canvas.set_cell(
                self.origin_x,
                self.origin_y,
                Cell {
                    ch: LINE_UP_RIGHT,
                    style,
                },
            );
            for y in (0..self.origin_y).rev() {
                self.canvas.set_cell(
                    self.origin_x,
                    y,
                    Cell {
                        ch: LINE_VERTICAL,
                        style,
                    },
                );
            }
            for x in self.origin_x + 1..self.canvas.width() as i32 {
                self.canvas.set_cell(
                    x,
                    self.origin_y,
                    Cell {
                        ch: LINE_HORIZONTAL,
                        style,
                    },
                );
            }
        } else if self.y_step > 0 {
            for y in (0..=self.origin_y).rev() {
                self.canvas.set_cell(
                    self.origin_x,
                    y,
                    Cell {
                        ch: LINE_VERTICAL,
                        style,
                    },
                );
            }
        } else if self.x_step > 0 {
            for x in self.origin_x..self.canvas.width() as i32 {
                self.canvas.set_cell(
                    x,
                    self.origin_y,
                    Cell {
                        ch: LINE_HORIZONTAL,
                        style,
                    },
                );
            }
        }
    }

    /// Draws X axis tick values below the X axis every `x_step` columns.
    /// Labels are skipped when they would repeat, overflow the canvas, or
    /// collide with a previously drawn label.
    pub fn draw_x_labels(&mut self, x_fmt: LabelFormatter) {
        let n = self.x_step;
        if n <= 0 || self.graph_width <= 0 {
            return;
        }

        let range = self.view_max_x - self.view_min_x;
        let increment = range / self.graph_width as f64;
        let last = self.graph_width - 1;
        let mut last_val = String::new();
        let mut i = 0;
        loop {
            // Can only draw if the cell to the left is empty.
            if self
                .canvas
                .cell(self.origin_x + i - 1, self.origin_y + 1)
                .ch
                == '\0'
            {
                let v = self.view_min_x + increment * i as f64;
                let s = x_fmt(i, v);
                let end = s.chars().count() as i32 + self.origin_x + i;
                if s != last_val && end <= self.canvas.width() as i32 {
                    self.canvas.set_string(
                        self.origin_x + i,
                        self.origin_y + 1,
                        &s,
                        self.label_style,
                    );
                    last_val = s;
                }
            }
            if i == last {
                break;
            }
            i = (i + n).min(last);
        }
    }

    /// Draws Y-axis tick labels at rows 0, y_step, 2*y_step, ... and
    /// optionally at graph_height when there's enough gap above the previous
    /// tick (LEET's fixed version of ntcharts' drawYLabel).
    pub fn draw_y_labels(&mut self, y_fmt: LabelFormatter) {
        let y_step = self.y_step;
        let graph_h = self.graph_height;
        if y_step <= 0 || graph_h <= 0 {
            return;
        }
        let increment = (self.view_max_y - self.view_min_y) / graph_h as f64;

        let mut last_val = String::new();
        let mut last_i = 0;
        let mut i = 0;
        while i <= graph_h {
            let v = self.view_min_y + increment * i as f64;
            let s = y_fmt(i, v);
            if !s.is_empty() && s != last_val {
                self.canvas.set_string(
                    self.origin_x - s.chars().count() as i32,
                    self.origin_y - i,
                    &s,
                    self.label_style,
                );
                last_val = s;
            }
            last_i = i;
            i += y_step;
        }
        // Add a top tick when the last stepped tick fell short of graph_h
        // and there's room for a non-adjacent label.
        if last_i < graph_h && graph_h - last_i >= (y_step + 1) / 2 {
            let v = self.view_min_y + increment * graph_h as f64;
            let s = y_fmt(graph_h, v);
            if !s.is_empty() && s != last_val {
                self.canvas.set_string(
                    self.origin_x - s.chars().count() as i32,
                    self.origin_y - graph_h,
                    &s,
                    self.label_style,
                );
            }
        }
    }
}
