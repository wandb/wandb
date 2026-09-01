//! Braille dot grid, axis drawing, and the linechart backend.
//!
//! Port of exactly the ntcharts subset leet's charts touch
//! (docs/PORTING.md):
//!
//! - `canvas/runes/runes.go`: braille pattern dot grid + rune composition,
//!   the rune constants the axes use, `IsBraillePattern`.
//! - `canvas/graph/graph.go`: `BrailleGrid` (2 dots/cell wide, 4 dots/cell
//!   high, float scaling) and the axis line helpers behind
//!   `DrawXYAxisAndLabel`.
//! - `linechart/linechart.go`: `LineChart` — the `linechart.Model` that
//!   `EpochLineChart` embeds (ranges, view ranges, graph sizing/origin,
//!   axis + label drawing).
//!
//! leet suppresses ntcharts' Y labels at draw time via a formatter swap and
//! draws its own (`epochlinechart.go` `drawYLabels`);
//! `draw_xy_axis_and_label` and the private `draw_y_label` are still ported
//! verbatim because the X-label path and the formatter-swap trick both go
//! through them.
//!
//! Not ported (unused by leet): `PatternDots`, `PatternDotsGrid.Unset`,
//! `BraillePatternFromPatternDots`, `SetPatternDots`,
//! `CombineBraillePatterns` (leet composites braille occludedly itself),
//! line/arc/candlestick/block rune tables and combiners, `DrawBrailleRune`/
//! `DrawBraillePatterns` (merging variants), `GetLinePoints*`/
//! `GetCirclePoints*`/`DrawColumns`/`DrawRows`/`DrawCandlestick*`,
//! `linechart.Model.Style`, `Draw*`/`ScaleFloat64Point*`/`AutoAdjustRange`
//! (the `AutoMinX`/`AutoMaxX` flags set by `WithAutoXRange` are kept but are
//! inert, as in leet's Go usage), `SetXStep`/`SetYStep`, `SetViewXYRange`,
//! `MaxInterpolationPoints`, focus/Update/View/zone plumbing.
//
// Derived from NimbleMarkets/ntcharts
// (https://github.com/NimbleMarkets/ntcharts), vendored at
// core/vendor/github.com/NimbleMarkets/ntcharts.
// ntcharts - Copyright (c) 2024-2026 Neomantra Corp.
// Used under the MIT License (see LICENSE.txt in the vendored tree).

use crate::canvas::{
    Canvas, Cell, CellStyle, Float64Point, Point, canvas_point_from_float64_point,
};
use leet_data::go_fmt;

// ---------------------------------------------------------------------------
// canvas/runes subset.
// ---------------------------------------------------------------------------

pub const NULL: char = '\u{0000}';

pub const LINE_HORIZONTAL: char = '\u{2500}'; // ─
pub const LINE_VERTICAL: char = '\u{2502}'; // │
pub const LINE_UP_RIGHT: char = '\u{2514}'; // └

/*
Braille dot number offsets

Unicode Braille Patterns can be computed by
adding hex values to the beginning block offset

[0][3] = [0x0001][0x0008]
[1][4]   [0x0002][0x0010]
[2][5]   [0x0004][0x0020]
[6][7]   [0x0040][0x0080]
*/

/// Beginning of Unicode Braille Patterns (empty Braille Pattern).
pub const BRAILLE_BLOCK_OFFSET: char = '\u{2800}';

const BRAILLE_DOT_NUMBER_OFFSETS: [u32; 8] = [
    0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080,
];

/// IsBraillePattern returns whether a given rune is considered a Braille
/// Pattern rune.
pub fn is_braille_pattern(r: char) -> bool {
    ('\u{2800}'..='\u{28FF}').contains(&r)
}

/// PatternDotsGrid is a 2D array where each row and column indicates whether
/// a dot in a sequence of Braille Patterns runes should be displayed.
/// Example:
///
/// ```text
///  width = 4, height = 4 will give 2 Braille Pattern runes
///  [0][3][0][3]
///  [1][4][1][4]
///  [2][5][2][5]
///  [6][7][6][7]
///
/// setting (0,0) will set Dot 0 of first braille rune
/// setting (0,3) will set Dot 6 of first braille rune
/// setting (3,0) will set Dot 3 of second braille rune
/// setting (3,3) will set Dot 7 of second braille rune
/// ```
#[derive(Debug, Clone)]
pub struct PatternDotsGrid {
    w: i64, // grid width
    h: i64, // grid height
    // each index indicates whether to display Braille Pattern dot
    g: Vec<Vec<bool>>,
}

impl PatternDotsGrid {
    /// NewPatternDotsGrid returns a new initialized PatternDotsGrid.
    pub fn new(w: i64, h: i64) -> PatternDotsGrid {
        let mut g = PatternDotsGrid {
            w,
            h,
            g: Vec::new(),
        };
        g.reset();
        g
    }

    /// Reset will reset the internal grid.
    pub fn reset(&mut self) {
        // PARITY: Go's `make` would panic on negative sizes; clamped
        // (unreachable via leet — BrailleGrid is only built after
        // GraphWidth/GraphHeight > 0 checks).
        self.g = vec![vec![false; self.w.max(0) as usize]; self.h.max(0) as usize];
    }

    /// Set will set value in grid at given column and row.
    pub fn set(&mut self, x: i64, y: i64) {
        if !(0..self.w).contains(&x) || !(0..self.h).contains(&y) {
            return;
        }
        self.g[y as usize][x as usize] = true;
    }

    /// BraillePatterns returns a 2D grid of Braille Pattern runes based on
    /// internal grid values.
    pub fn braille_patterns(&self) -> Vec<Vec<char>> {
        let mut p = Vec::new();
        let mut y = 0;
        while y < self.h {
            let mut xb = Vec::new();
            let mut x = 0;
            while x < self.w {
                xb.push(self.get_braille_pattern(x, y));
                x += 2; // each braille pattern rune has a width of 2
            }
            p.push(xb);
            y += 4; // each braille pattern rune has a height of 4
        }
        p
    }

    /// getBraillePattern returns the Braille Pattern rune starting at
    /// internal grid column and row.
    fn get_braille_pattern(&self, x: i64, y: i64) -> char {
        if !(0..self.w).contains(&x) || !(0..self.h).contains(&y) {
            return NULL;
        }
        let (xu, yu) = (x as usize, y as usize);
        let mut b = BRAILLE_BLOCK_OFFSET as u32;
        // set left side of braille pattern
        if self.g[yu][xu] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[0];
        }
        if y + 1 < self.h && self.g[yu + 1][xu] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[1];
        }
        if y + 2 < self.h && self.g[yu + 2][xu] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[2];
        }
        if y + 3 < self.h && self.g[yu + 3][xu] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[6];
        }
        // set right side of braille pattern
        if x + 1 < self.w && self.g[yu][xu + 1] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[3];
        }
        if y + 1 < self.h && x + 1 < self.w && self.g[yu + 1][xu + 1] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[4];
        }
        if y + 2 < self.h && x + 1 < self.w && self.g[yu + 2][xu + 1] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[5];
        }
        if y + 3 < self.h && x + 1 < self.w && self.g[yu + 3][xu + 1] {
            b |= BRAILLE_DOT_NUMBER_OFFSETS[7];
        }
        char::from_u32(b).expect("0x2800..=0x28FF are valid scalar values")
    }
}

// ---------------------------------------------------------------------------
// canvas/graph subset.
// ---------------------------------------------------------------------------

/// BrailleGrid wraps a [`PatternDotsGrid`] to implement a 2D grid with
/// (X, Y) floating point coordinates used to display Braille Pattern runes.
/// Since Braille Pattern runes are 4 high and 2 wide, the BrailleGrid will
/// internally scale the width and height sizes to match those patterns.
/// BrailleGrid uses canvas coordinates system with (0,0) being top left.
#[derive(Debug, Clone)]
pub struct BrailleGrid {
    // PARITY: Go stores the canvas dimensions; nothing in the ported subset
    // reads them back.
    #[allow(dead_code)]
    c_width: i64, // canvas width
    #[allow(dead_code)]
    c_height: i64, // canvas height

    min_x: f64,
    max_x: f64,
    min_y: f64,
    max_y: f64,

    g_width: i64,  // grid width
    g_height: i64, // grid height
    grid: PatternDotsGrid,
}

impl BrailleGrid {
    /// NewBrailleGrid returns a new initialized BrailleGrid with given canvas
    /// width, canvas height and minimums and maximums X and Y values of the
    /// data points.
    pub fn new(w: i64, h: i64, min_x: f64, max_x: f64, min_y: f64, max_y: f64) -> BrailleGrid {
        let grid_w = w * 2;
        let grid_h = h * 4;
        let mut g = BrailleGrid {
            c_width: w,
            c_height: h,
            min_x,
            max_x,
            min_y,
            max_y,
            g_width: grid_w,
            g_height: grid_h,
            grid: PatternDotsGrid::new(grid_w, grid_h),
        };
        g.clear();
        g
    }

    /// Clear will reset the internal grid.
    pub fn clear(&mut self) {
        self.grid.reset();
    }

    /// GridPoint returns a canvas Point representing a point in the braille
    /// grid in the canvas coordinates system from a Float64Point data point
    /// in the Cartesian coordinates system.
    pub fn grid_point(&self, f: Float64Point) -> Point {
        let mut sf = Float64Point { x: 0.0, y: 0.0 };
        let dx = self.max_x - self.min_x;
        let dy = self.max_y - self.min_y;
        if dx > 0.0 {
            // PARITY: keep Go's arithmetic shape — the scale factor is
            // computed first, then a single multiply (no algebraic
            // rearrangement, no FMA).
            let xs = (self.g_width - 1) as f64 / dx;
            sf.x = (f.x - self.min_x) * xs;
        }
        if dy > 0.0 {
            let ys = (self.g_height - 1) as f64 / dy;
            sf.y = (f.y - self.min_y) * ys;
        }
        canvas_point_from_float64_point(
            Point {
                x: 0,
                y: self.g_height - 1,
            },
            sf,
        )
    }

    /// Set will set point on grid from given canvas Point.
    pub fn set(&mut self, p: Point) {
        self.grid.set(p.x, p.y);
    }

    /// BraillePatterns returns a 2D grid of braille pattern runes to draw on
    /// to the canvas.
    pub fn braille_patterns(&self) -> Vec<Vec<char>> {
        self.grid.braille_patterns()
    }
}

/// DrawVerticalLineUp draws a vertical line going up starting from (X,Y)
/// coordinates. Applies given style to all runes.
/// Coordinates (0,0) is top left of canvas.
pub fn draw_vertical_line_up(m: &mut Canvas, p: Point, s: CellStyle) {
    let x = p.x;
    let r = Cell::new_with_style(LINE_VERTICAL, s);
    let mut i = p.y;
    while i >= 0 {
        m.set_cell(Point { x, y: i }, r);
        i -= 1;
    }
}

/// DrawHorizonalLineRight (sic — ntcharts' spelling) draws a horizontal line
/// going to the right starting from (X,Y) coordinates.
/// Applies given style to all runes.
/// Coordinates (0,0) is top left of canvas.
pub fn draw_horizonal_line_right(m: &mut Canvas, p: Point, s: CellStyle) {
    let y = p.y;
    let r = Cell::new_with_style(LINE_HORIZONTAL, s);
    let mut i = p.x;
    while i < m.width() {
        m.set_cell(Point { x: i, y }, r);
        i += 1;
    }
}

/// DrawXYAxis draws X and Y axes with origin at (X,Y) coordinates with given
/// style. Y axis extends up, and X axis extends right.
/// Coordinates (0,0) is top left of canvas.
pub fn draw_xy_axis(m: &mut Canvas, p: Point, s: CellStyle) {
    m.set_cell(p, Cell::new_with_style(LINE_UP_RIGHT, s));
    draw_vertical_line_up(m, Point { x: p.x, y: p.y - 1 }, s);
    draw_horizonal_line_right(m, Point { x: p.x + 1, y: p.y }, s);
}

// ---------------------------------------------------------------------------
// Go math.Min / math.Max semantics.
// ---------------------------------------------------------------------------

/// Go `math.Max`: +Inf beats NaN, NaN propagates otherwise, and ±0 prefers
/// +0. Rust `f64::max` IGNORES NaN, so ported Go Min/Max calls must use this
/// (PORTING.md, float math).
pub fn math_max(x: f64, y: f64) -> f64 {
    // special cases, in Go's order
    if x == f64::INFINITY || y == f64::INFINITY {
        return f64::INFINITY;
    }
    if x.is_nan() || y.is_nan() {
        return f64::NAN;
    }
    if x == 0.0 && x == y {
        if x.is_sign_negative() {
            return y;
        }
        return x;
    }
    if x > y { x } else { y }
}

/// Go `math.Min`: -Inf beats NaN, NaN propagates otherwise, and ±0 prefers
/// -0. See [`math_max`].
pub fn math_min(x: f64, y: f64) -> f64 {
    // special cases, in Go's order
    if x == f64::NEG_INFINITY || y == f64::NEG_INFINITY {
        return f64::NEG_INFINITY;
    }
    if x.is_nan() || y.is_nan() {
        return f64::NAN;
    }
    if x == 0.0 && x == y {
        if x.is_sign_negative() {
            return x;
        }
        return y;
    }
    if x < y { x } else { y }
}

// ---------------------------------------------------------------------------
// linechart subset.
// ---------------------------------------------------------------------------

/// LabelFormatter converts a float64 into text for displaying the X and Y
/// axis labels given an index of label and numeric value.
/// Index increments from minimum value to maximum values.
pub type LabelFormatter = Box<dyn Fn(i64, f64) -> String>;

/// DefaultLabelFormatter returns a LabelFormatter that converts float64 to
/// integers (Go `fmt.Sprintf("%.0f", v)`).
pub fn default_label_formatter() -> LabelFormatter {
    Box::new(|_i, v| go_fmt::format_float_f(v, 0))
}

/// getGraphSizeAndOrigin calculates and returns the linechart origin and
/// graph width and height.
fn get_graph_size_and_origin(
    w: i64,
    h: i64,
    min_y: f64,
    max_y: f64,
    x_step: i64,
    y_step: i64,
    y_fmter: &dyn Fn(i64, f64) -> String,
) -> (Point, i64, i64) {
    // graph width and height exclude area used by axes
    // origin point is canvas coordinates of where axes are drawn
    let mut origin = Point { x: 0, y: h - 1 };
    let mut g_width = w;
    let mut g_height = h;
    if x_step > 0 {
        // use last 2 rows of canvas to plot X axis and tick values
        origin.y -= 1;
        g_height -= 2;
    }
    if y_step > 0 {
        // find out how many spaces left of the Y axis
        // to reserve for axis tick value by checking the string length
        // of all values to be displayed
        let mut last_val = String::new();
        let mut value_len: i64 = 0;
        let range_sz = max_y - min_y; // range of possible expected values
        let increment = range_sz / g_height as f64;
        let mut i: i64 = 0;
        while i <= g_height {
            // PARITY: Go shape `minY + (increment * float64(i))`.
            let v = min_y + (increment * i as f64); // value to set left of Y axis
            let s = y_fmter(i, v);
            if last_val != s {
                // PARITY: Go len(s) counts BYTES, not display width.
                if s.len() as i64 > value_len {
                    value_len = s.len() as i64;
                }
                last_val = s;
            }
            i += y_step;
        }
        origin.x += value_len;
        g_width -= value_len + 1; // ignore Y axis and tick values
    }
    (origin, g_width, g_height)
}

/// LineChart is the ported subset of ntcharts `linechart.Model`: the state
/// of a linechart with an embedded [`Canvas`]. `EpochLineChart` embeds it
/// (Go embeds `linechart.Model`).
pub struct LineChart {
    pub canvas: Canvas,
    /// Style applied when drawing X and Y axes.
    pub axis_style: CellStyle,
    /// Style applied when drawing X and Y number values.
    pub label_style: CellStyle,
    /// Converts X number values to display strings.
    pub x_label_formatter: LabelFormatter,
    /// Converts Y number values to display strings.
    pub y_label_formatter: LabelFormatter,
    x_step: i64, // number of steps when displaying X axis values
    y_step: i64, // number of steps when displaying Y axis values

    // the expected min and max values
    min_x: f64,
    max_x: f64,
    min_y: f64,
    max_y: f64,

    // current min and max axes values to display
    view_min_x: f64,
    view_max_x: f64,
    view_min_y: f64,
    view_max_y: f64,

    // whether to automatically set expected values when a value appears
    // beyond the existing bounds.
    // PARITY: set by with_auto_x_range like Go's WithAutoXRange, but inert —
    // AutoAdjustRange is only invoked by ntcharts Draw* methods leet never
    // calls (leet draws series braille itself).
    pub auto_min_x: bool,
    pub auto_max_x: bool,
    pub auto_min_y: bool,
    pub auto_max_y: bool,

    // start of X and Y axes lines on canvas for graphing area
    origin: Point,
    graph_width: i64,  // width of graphing area - excludes X axis and labels
    graph_height: i64, // height of graphing area - excludes Y axis and labels
}

impl LineChart {
    /// New returns a LineChart initialized with given width, height and
    /// expected data value ranges. Width and height includes area used for
    /// chart labeling. If xStep is 0, then will not draw X axis or values
    /// below X axis. If yStep is 0, then will not draw Y axis or values left
    /// of Y axis.
    ///
    /// The two ntcharts options leet uses are the builder methods
    /// [`Self::with_xy_steps`] and [`Self::with_auto_x_range`].
    pub fn new(w: i64, h: i64, min_x: f64, max_x: f64, min_y: f64, max_y: f64) -> LineChart {
        let mut m = LineChart {
            canvas: Canvas::new(w, h),
            axis_style: CellStyle::default(),
            label_style: CellStyle::default(),
            x_label_formatter: default_label_formatter(),
            y_label_formatter: default_label_formatter(),
            y_step: 2,
            x_step: 2,
            min_x,
            max_x,
            min_y,
            max_y,
            view_min_x: min_x,
            view_max_x: max_x,
            view_min_y: min_y,
            view_max_y: max_y,
            auto_min_x: false,
            auto_max_x: false,
            auto_min_y: false,
            auto_max_y: false,
            origin: Point::default(),
            graph_width: 0,
            graph_height: 0,
        };
        m.update_graph_sizes();
        m
    }

    /// WithXYSteps sets the number of steps when drawing X and Y axes
    /// values.
    ///
    /// Go applies options inside `New` before its single `UpdateGraphSizes`
    /// call; `update_graph_sizes` is a pure recomputation from the current
    /// fields, so re-running it here yields the identical final state.
    pub fn with_xy_steps(mut self, x_step: i64, y_step: i64) -> LineChart {
        self.x_step = x_step;
        self.y_step = y_step;
        self.update_graph_sizes();
        self
    }

    /// WithAutoXRange enables automatically setting the minimum and maximum
    /// expected X values if new data values are beyond the current range.
    pub fn with_auto_x_range(mut self) -> LineChart {
        self.auto_min_x = true;
        self.auto_max_x = true;
        self
    }

    /// UpdateGraphSizes updates the origin, graph width and graph height.
    /// This method should be called whenever the X and Y axes values have
    /// changed.
    pub fn update_graph_sizes(&mut self) {
        let (origin, g_width, g_height) = get_graph_size_and_origin(
            self.canvas.width(),
            self.canvas.height(),
            self.view_min_y,
            self.view_max_y,
            self.x_step,
            self.y_step,
            self.y_label_formatter.as_ref(),
        );
        self.origin = origin;
        self.graph_width = g_width;
        self.graph_height = g_height;
    }

    /// Width returns linechart width.
    pub fn width(&self) -> i64 {
        self.canvas.width()
    }

    /// Height returns linechart height.
    pub fn height(&self) -> i64 {
        self.canvas.height()
    }

    /// GraphWidth returns linechart graphing area width.
    pub fn graph_width(&self) -> i64 {
        self.graph_width
    }

    /// GraphHeight returns linechart graphing area height.
    pub fn graph_height(&self) -> i64 {
        self.graph_height
    }

    /// MinX returns linechart expected minimum X value.
    pub fn min_x(&self) -> f64 {
        self.min_x
    }

    /// MaxX returns linechart expected maximum X value.
    pub fn max_x(&self) -> f64 {
        self.max_x
    }

    /// MinY returns linechart expected minimum Y value.
    pub fn min_y(&self) -> f64 {
        self.min_y
    }

    /// MaxY returns linechart expected maximum Y value.
    pub fn max_y(&self) -> f64 {
        self.max_y
    }

    /// ViewMinX returns linechart displayed minimum X value.
    pub fn view_min_x(&self) -> f64 {
        self.view_min_x
    }

    /// ViewMaxX returns linechart displayed maximum X value.
    pub fn view_max_x(&self) -> f64 {
        self.view_max_x
    }

    /// ViewMinY returns linechart displayed minimum Y value.
    pub fn view_min_y(&self) -> f64 {
        self.view_min_y
    }

    /// ViewMaxY returns linechart displayed maximum Y value.
    pub fn view_max_y(&self) -> f64 {
        self.view_max_y
    }

    /// XStep returns number of steps when displaying X axis values.
    pub fn x_step(&self) -> i64 {
        self.x_step
    }

    /// YStep returns number of steps when displaying Y axis values.
    pub fn y_step(&self) -> i64 {
        self.y_step
    }

    /// Origin returns a canvas Point with the coordinates of the linechart
    /// graph (X,Y) origin.
    pub fn origin(&self) -> Point {
        self.origin
    }

    /// Clear will reset linechart canvas including axes and labels.
    pub fn clear(&mut self) {
        self.canvas.clear();
    }

    /// SetXRange updates the minimum and maximum expected X values.
    pub fn set_x_range(&mut self, min: f64, max: f64) {
        self.min_x = min;
        self.max_x = max;
    }

    /// SetYRange updates the minimum and maximum expected Y values.
    pub fn set_y_range(&mut self, min: f64, max: f64) {
        self.min_y = min;
        self.max_y = max;
    }

    /// SetXYRange updates the minimum and maximum expected X and Y values.
    pub fn set_xy_range(&mut self, min_x: f64, max_x: f64, min_y: f64, max_y: f64) {
        self.set_x_range(min_x, max_x);
        self.set_y_range(min_y, max_y);
    }

    /// SetViewXRange updates the displayed minimum and maximum X values.
    /// Minimum and maximum values will be bounded by the expected X values.
    /// Returns whether or not displayed X values have updated.
    pub fn set_view_x_range(&mut self, min: f64, max: f64) -> bool {
        let v_min = math_max(self.min_x, min);
        let v_max = math_min(self.max_x, max);
        if v_min < v_max {
            self.view_min_x = v_min;
            self.view_max_x = v_max;
            self.update_graph_sizes();
            return true;
        }
        false
    }

    /// SetViewYRange updates the displayed minimum and maximum Y values.
    /// Minimum and maximum values will be bounded by the expected Y values.
    /// Returns whether or not displayed Y values have updated.
    pub fn set_view_y_range(&mut self, min: f64, max: f64) -> bool {
        let v_min = math_max(self.min_y, min);
        let v_max = math_min(self.max_y, max);
        if v_min < v_max {
            self.view_min_y = v_min;
            self.view_max_y = v_max;
            self.update_graph_sizes();
            return true;
        }
        false
    }

    /// Resize will change linechart display width and height.
    /// Existing runes on the linechart will not be redrawn.
    pub fn resize(&mut self, w: i64, h: i64) {
        self.canvas.resize(w, h);
        // PARITY: Go assigns the raw (unclamped) w/h to the view fields even
        // though the canvas area clamps negatives.
        self.canvas.view_width = w;
        self.canvas.view_height = h;
        self.update_graph_sizes();
    }

    /// drawYLabel draws Y axis values left of the Y axis every n step.
    /// Repeating values will be hidden. Does nothing if n <= 0.
    fn draw_y_label(&mut self, n: i64) {
        // from origin going up, draw data value left of the Y axis every n
        // steps; origin X coordinates already set such that there is space
        // available
        if n <= 0 {
            return;
        }
        let mut last_val = String::new();
        let range_sz = self.view_max_y - self.view_min_y; // range of possible expected values
        let increment = range_sz / self.graph_height as f64;
        let mut i: i64 = 0;
        while i <= self.graph_height {
            let v = self.view_min_y + (increment * i as f64); // value to set left of Y axis
            let s = (self.y_label_formatter)(i, v);
            if last_val != s {
                // PARITY: Go len(s) counts BYTES.
                self.canvas.set_string_with_style(
                    Point {
                        x: self.origin.x - s.len() as i64,
                        y: self.origin.y - i,
                    },
                    &s,
                    self.label_style,
                );
                last_val = s;
            }
            if i == self.graph_height {
                break;
            }
            i = (i + n).min(self.graph_height);
        }
    }

    /// drawXLabel draws X axis values below the X axis every n step.
    /// Repeating values will be hidden. Does nothing if n <= 0.
    fn draw_x_label(&mut self, n: i64) {
        // from origin going right, draw data value below the X axis every n
        // steps
        if n <= 0 {
            return;
        }
        let mut last_val = String::new();
        let range_sz = self.view_max_x - self.view_min_x; // range of possible expected values
        let increment = range_sz / self.graph_width as f64;
        let last = self.graph_width - 1;
        let mut i: i64 = 0;
        while i < self.graph_width {
            // can only set if rune to the left of target coordinates is empty
            let c = self.canvas.cell(Point {
                x: self.origin.x + i - 1,
                y: self.origin.y + 1,
            });
            if c.ch == NULL {
                let v = self.view_min_x + (increment * i as f64); // value to set under X axis
                let s = (self.x_label_formatter)(i, v);
                // dont display if number will be cut off or value repeats
                // PARITY: Go len(s) counts BYTES.
                let s_len = s.len() as i64 + self.origin.x + i;
                if (s != last_val) && (s_len <= self.canvas.width()) {
                    self.canvas.set_string_with_style(
                        Point {
                            x: self.origin.x + i,
                            y: self.origin.y + 1,
                        },
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

    /// DrawXYAxisAndLabel draws the X, Y axes and their labels.
    pub fn draw_xy_axis_and_label(&mut self) {
        let draw_y = self.y_step > 0;
        let draw_x = self.x_step > 0;
        if draw_y && draw_x {
            draw_xy_axis(&mut self.canvas, self.origin, self.axis_style);
        } else {
            if draw_y {
                // draw Y axis
                draw_vertical_line_up(&mut self.canvas, self.origin, self.axis_style);
            }
            if draw_x {
                // draw X axis
                draw_horizonal_line_right(&mut self.canvas, self.origin, self.axis_style);
            }
        }
        self.draw_y_label(self.y_step);
        self.draw_x_label(self.x_step);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    // ----- runes: braille rune composition ---------------------------------

    #[test]
    fn braille_rune_composition_single_dots() {
        // Dot numbering within one braille cell (2 wide x 4 high):
        // [0][3] / [1][4] / [2][5] / [6][7] with bit offsets
        // 0x01/0x08, 0x02/0x10, 0x04/0x20, 0x40/0x80.
        let cases: [(i64, i64, char); 8] = [
            (0, 0, '\u{2801}'),
            (0, 1, '\u{2802}'),
            (0, 2, '\u{2804}'),
            (0, 3, '\u{2840}'),
            (1, 0, '\u{2808}'),
            (1, 1, '\u{2810}'),
            (1, 2, '\u{2820}'),
            (1, 3, '\u{2880}'),
        ];
        for (x, y, want) in cases {
            let mut g = PatternDotsGrid::new(2, 4);
            g.set(x, y);
            assert_eq!(g.braille_patterns(), vec![vec![want]], "dot ({x},{y})");
        }
    }

    #[test]
    fn braille_rune_composition_combined() {
        let mut g = PatternDotsGrid::new(2, 4);
        for y in 0..4 {
            g.set(0, y);
        }
        // Left column: 0x01|0x02|0x04|0x40 = 0x47.
        assert_eq!(g.braille_patterns(), vec![vec!['\u{2847}']]); // ⡇
        for y in 0..4 {
            g.set(1, y);
        }
        // All eight dots: 0xFF.
        assert_eq!(g.braille_patterns(), vec![vec!['\u{28FF}']]); // ⣿
    }

    #[test]
    fn braille_patterns_multi_cell_grid() {
        // width=4, height=8 → 2 runes per row, 2 rune rows.
        let mut g = PatternDotsGrid::new(4, 8);
        g.set(3, 7); // bottom-right dot of the bottom-right rune
        let p = g.braille_patterns();
        assert_eq!(p.len(), 2);
        assert_eq!(p[0], vec!['\u{2800}', '\u{2800}']);
        assert_eq!(p[1], vec!['\u{2800}', '\u{2880}']);
    }

    #[test]
    fn pattern_dots_grid_ignores_out_of_bounds() {
        let mut g = PatternDotsGrid::new(2, 4);
        g.set(-1, 0);
        g.set(0, -1);
        g.set(2, 0);
        g.set(0, 4);
        assert_eq!(g.braille_patterns(), vec![vec!['\u{2800}']]);
    }

    #[test]
    fn is_braille_pattern_range() {
        assert!(is_braille_pattern('\u{2800}'));
        assert!(is_braille_pattern('\u{28FF}'));
        assert!(!is_braille_pattern('\u{27FF}'));
        assert!(!is_braille_pattern('\u{2900}'));
        assert!(!is_braille_pattern('a'));
        assert!(!is_braille_pattern(NULL));
    }

    // ----- graph: BrailleGrid coordinate math -------------------------------

    #[test]
    fn grid_point_rounds_half_away_from_zero() {
        // 2x1 canvas cells → 4x4 dot grid; ranges chosen so both scale
        // factors are exactly 1: xs = (4-1)/3 = 1, ys = (4-1)/3 = 1.
        let g = BrailleGrid::new(2, 1, 0.0, 3.0, 0.0, 3.0);
        // Cartesian origin maps to the bottom dot row (canvas y = gH-1 = 3).
        assert_eq!(
            g.grid_point(Float64Point { x: 0.0, y: 0.0 }),
            Point { x: 0, y: 3 }
        );
        // .5 dot boundaries round away from zero (Go math.Round), including
        // 2.5 → 3 which banker's rounding would send to 2.
        assert_eq!(
            g.grid_point(Float64Point { x: 0.5, y: 0.0 }),
            Point { x: 1, y: 3 }
        );
        assert_eq!(
            g.grid_point(Float64Point { x: 1.5, y: 0.0 }),
            Point { x: 2, y: 3 }
        );
        assert_eq!(
            g.grid_point(Float64Point { x: 2.5, y: 0.0 }),
            Point { x: 3, y: 3 }
        );
        assert_eq!(
            g.grid_point(Float64Point { x: 0.0, y: 0.5 }),
            Point { x: 0, y: 2 }
        );
        assert_eq!(
            g.grid_point(Float64Point { x: 0.0, y: 2.5 }),
            Point { x: 0, y: 0 }
        );
        // Out-of-range data yields out-of-grid dots here; clamping happens
        // in Set, not in GridPoint. sf=(-0.5, 3.5) rounds to (-1, 4) and
        // canvas-flips to (-1, -1).
        assert_eq!(
            g.grid_point(Float64Point { x: -0.5, y: 3.5 }),
            Point { x: -1, y: -1 }
        );
    }

    #[test]
    fn grid_point_degenerate_range_stays_on_axis() {
        // dx <= 0 leaves the scaled X at its zero value (Go's sf.X).
        let g = BrailleGrid::new(2, 1, 5.0, 5.0, 0.0, 3.0);
        assert_eq!(
            g.grid_point(Float64Point { x: 42.0, y: 0.0 }),
            Point { x: 0, y: 3 }
        );
        // dy <= 0 likewise pins Y to the grid's bottom row.
        let g = BrailleGrid::new(2, 1, 0.0, 3.0, 7.0, 7.0);
        assert_eq!(
            g.grid_point(Float64Point { x: 0.0, y: 100.0 }),
            Point { x: 0, y: 3 }
        );
    }

    #[test]
    fn braille_grid_set_and_patterns_roundtrip() {
        // 1x1 cell → 2x4 dots; xs = (2-1)/1 = 1, ys = (4-1)/1 = 3.
        let mut g = BrailleGrid::new(1, 1, 0.0, 1.0, 0.0, 1.0);
        g.set(g.grid_point(Float64Point { x: 0.0, y: 0.0 })); // dot (0,3): 0x40
        g.set(g.grid_point(Float64Point { x: 1.0, y: 1.0 })); // dot (1,0): 0x08
        assert_eq!(g.braille_patterns(), vec![vec!['\u{2848}']]);
        // Out-of-grid sets are ignored (grid clamping).
        g.set(Point { x: 0, y: 4 });
        g.set(Point { x: -1, y: 0 });
        g.set(Point { x: 2, y: 0 });
        assert_eq!(g.braille_patterns(), vec![vec!['\u{2848}']]);
        g.clear();
        assert_eq!(g.braille_patterns(), vec![vec!['\u{2800}']]);
    }

    // ----- graph: axis helpers ----------------------------------------------

    #[test]
    fn axis_helpers_draw_expected_runes() {
        let mut c = Canvas::new(4, 3);
        draw_xy_axis(&mut c, Point { x: 1, y: 1 }, CellStyle::default());
        assert_eq!(
            c.text_rows(),
            vec![" │  ".to_string(), " └──".to_string(), "    ".to_string(),]
        );
    }

    // ----- Go math.Min/math.Max ---------------------------------------------

    #[test]
    fn math_min_max_go_semantics() {
        assert!(math_max(f64::NAN, 1.0).is_nan());
        assert!(math_min(f64::NAN, 1.0).is_nan());
        // Infinities beat NaN (Go checks IsInf first).
        assert_eq!(math_max(f64::NAN, f64::INFINITY), f64::INFINITY);
        assert_eq!(math_min(f64::NAN, f64::NEG_INFINITY), f64::NEG_INFINITY);
        assert_eq!(math_max(-1.0, 2.0), 2.0);
        assert_eq!(math_min(-1.0, 2.0), -1.0);
        // Signed zero handling.
        assert!(math_max(-0.0, 0.0).is_sign_positive());
        assert!(math_min(-0.0, 0.0).is_sign_negative());
    }

    // ----- linechart ----------------------------------------------------------

    #[test]
    fn linechart_parked_graph_sizes() {
        // leet parks charts at 1x1 with WithXYSteps(4, 5), WithAutoXRange()
        // (epochlinechart.go NewEpochLineChart). Hand-traced through Go
        // getGraphSizeAndOrigin: origin=(0,-1), gWidth=0, gHeight=-1.
        let m = LineChart::new(1, 1, 0.0, 20.0, 0.0, 1.0)
            .with_xy_steps(4, 5)
            .with_auto_x_range();
        assert_eq!((m.width(), m.height()), (1, 1));
        assert_eq!(m.origin(), Point { x: 0, y: -1 });
        assert_eq!(m.graph_width(), 0);
        assert_eq!(m.graph_height(), -1);
        assert_eq!((m.x_step(), m.y_step()), (4, 5));
        assert!(m.auto_min_x && m.auto_max_x);
        assert!(!m.auto_min_y && !m.auto_max_y);
        // Drawing on a parked chart is a harmless no-op, as in Go.
        let mut m = m;
        m.draw_xy_axis_and_label();
        assert_eq!(m.canvas.text_rows(), vec![" ".to_string()]);
    }

    #[test]
    fn linechart_draw_xy_axis_and_label_frame() {
        // Hand-traced through the Go code: 10x6 canvas, steps (4,5), ranges
        // X 0..20 / Y 0..1.
        //   getGraphSizeAndOrigin: origin=(1,4), gWidth=8, gHeight=4
        //   drawYLabel(5): "0" at (0,4); "1" at (0,0)
        //   drawXLabel(4): increment=20/8=2.5 → "0"@(1,5), "10"@(5,5),
        //                  "18"@(8,5) (17.5 formats to "18" via %.0f)
        let mut m = LineChart::new(1, 1, 0.0, 20.0, 0.0, 1.0).with_xy_steps(4, 5);
        m.resize(10, 6);
        assert_eq!(m.origin(), Point { x: 1, y: 4 });
        assert_eq!(m.graph_width(), 8);
        assert_eq!(m.graph_height(), 4);
        m.draw_xy_axis_and_label();
        assert_eq!(
            m.canvas.text_rows(),
            vec![
                "1│        ".to_string(),
                " │        ".to_string(),
                " │        ".to_string(),
                " │        ".to_string(),
                "0└────────".to_string(),
                " 0   10 18".to_string(),
            ]
        );
        // clear() resets axes and labels too.
        m.clear();
        assert_eq!(m.canvas.text_rows(), vec![" ".repeat(10); 6]);
    }

    #[test]
    fn linechart_x_label_skips_repeats_and_occupied_cells() {
        // 6x4 canvas, steps (1,1), X 0..100 / Y 0..1. Hand-traced:
        //   origin=(1,2), gWidth=4, gHeight=2
        //   drawYLabel(1): "0"@(0,2); i=1 → v=0.5 → "0" repeats (hidden);
        //                  "1"@(0,0)
        //   drawXLabel(1): "0"@(1,3); i=1 skipped (left cell occupied by
        //                  "0"); "50"@(3,3); i=3 skipped (left cell '5')
        let mut m = LineChart::new(1, 1, 0.0, 100.0, 0.0, 1.0).with_xy_steps(1, 1);
        m.resize(6, 4);
        assert_eq!(m.origin(), Point { x: 1, y: 2 });
        assert_eq!(m.graph_width(), 4);
        assert_eq!(m.graph_height(), 2);
        m.draw_xy_axis_and_label();
        assert_eq!(
            m.canvas.text_rows(),
            vec![
                "1│    ".to_string(),
                " │    ".to_string(),
                "0└────".to_string(),
                " 0 50 ".to_string(),
            ]
        );
    }

    #[test]
    fn linechart_set_view_x_range_bounded() {
        let mut m = LineChart::new(1, 1, 0.0, 20.0, 0.0, 1.0).with_xy_steps(4, 5);
        // Bounded by the expected X range.
        assert!(m.set_view_x_range(-5.0, 30.0));
        assert_eq!((m.view_min_x(), m.view_max_x()), (0.0, 20.0));
        assert!(m.set_view_x_range(2.0, 7.0));
        assert_eq!((m.view_min_x(), m.view_max_x()), (2.0, 7.0));
        // Inverted or NaN ranges are rejected and leave the view unchanged.
        assert!(!m.set_view_x_range(10.0, 5.0));
        assert!(!m.set_view_x_range(f64::NAN, 10.0));
        assert_eq!((m.view_min_x(), m.view_max_x()), (2.0, 7.0));
        // Expected ranges are NOT bounded (SetXRange assigns directly).
        m.set_xy_range(-3.0, 50.0, -1.0, 2.0);
        assert_eq!((m.min_x(), m.max_x()), (-3.0, 50.0));
        assert_eq!((m.min_y(), m.max_y()), (-1.0, 2.0));
        // View Y range clamps against the new expected Y range.
        assert!(m.set_view_y_range(-10.0, 10.0));
        assert_eq!((m.view_min_y(), m.view_max_y()), (-1.0, 2.0));
    }

    #[test]
    fn linechart_formatter_swap_suppresses_y_labels() {
        // epochlinechart.go Draw() swaps YLabelFormatter to hide ntcharts'
        // Y labels; the empty string never differs from lastVal's initial
        // value, so nothing is drawn left of the axis.
        let mut m = LineChart::new(1, 1, 0.0, 20.0, 0.0, 1.0).with_xy_steps(4, 5);
        m.resize(10, 6);
        let orig = std::mem::replace(
            &mut m.y_label_formatter,
            Box::new(|_, _| String::new()) as LabelFormatter,
        );
        m.draw_xy_axis_and_label();
        m.y_label_formatter = orig;
        assert_eq!(
            m.canvas.text_rows(),
            vec![
                " │        ".to_string(),
                " │        ".to_string(),
                " │        ".to_string(),
                " │        ".to_string(),
                " └────────".to_string(),
                " 0   10 18".to_string(),
            ]
        );
    }

    #[test]
    fn default_label_formatter_matches_go_percent_dot0f() {
        let f = default_label_formatter();
        assert_eq!(f(0, 0.0), "0");
        assert_eq!(f(0, 10.0), "10");
        // Ties round to even, like Go's %.0f / strconv.FormatFloat 'f'.
        assert_eq!(f(0, 17.5), "18");
        assert_eq!(f(0, 2.5), "2");
        assert_eq!(f(0, -1.4), "-1");
    }
}
