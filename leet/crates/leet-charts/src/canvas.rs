//! Canvas: a 2D grid of styled runes — the render target for all charts.
//!
//! Port of the subset of ntcharts `canvas/canvas.go` that leet touches.
//! Per docs/PORTING.md (Canvas render-target row), charts render into
//! [`Canvas`] instead of returning ANSI strings; `leet-tui` blits the cell
//! grid into the ratatui buffer. Tests diff [`Canvas::text_rows`] (the
//! `View()`/ToString equivalent, styles stripped) against the Go rune grid.
//!
//! Not ported (unused by leet): `SetCursor`, `Fill`/`FillLine`, `SetStyle`,
//! `SetLines*`, `SetRune*`, `GetCellStyle`/`SetCellStyle`, `Shift*`,
//! focus/Update/KeyMap/zone plumbing, `Float64Point.Mul/Add/Sub`,
//! `CanvasYCoordinate(s)`, `CanvasPoints`, `CanvasFloat64Point`,
//! `NewFloat64PointFromPoint`.
//
// Derived from NimbleMarkets/ntcharts
// (https://github.com/NimbleMarkets/ntcharts), vendored at
// core/vendor/github.com/NimbleMarkets/ntcharts.
// ntcharts - Copyright (c) 2024-2026 Neomantra Corp.
// Used under the MIT License (see LICENSE.txt in the vendored tree).

use crate::styles::Rgb;

/// Point mirrors Go's `image.Point`: canvas coordinates, (0,0) is top left.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Point {
    pub x: i64,
    pub y: i64,
}

/// Vector sum (Go `image.Point.Add`); also callable as `p.add(q)`.
impl std::ops::Add for Point {
    type Output = Point;

    fn add(self, p: Point) -> Point {
        Point {
            x: self.x + p.x,
            y: self.y + p.y,
        }
    }
}

/// Float64Point represents a point in a coordinate system with floating
/// point precision.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Float64Point {
    pub x: f64,
    pub y: f64,
}

/// NewPointFromFloat64Point returns a new Point from a given Float64Point.
///
/// PARITY: Go `math.Round` rounds half away from zero; `f64::round` matches
/// (NOT round-half-to-even).
pub fn new_point_from_float64_point(f: Float64Point) -> Point {
    Point {
        x: f.x.round() as i64,
        y: f.y.round() as i64,
    }
}

/// CanvasPoint returns a Point in the canvas coordinates system (X,Y is top
/// left) from a given Point in the Cartesian coordinates system (X,Y is
/// bottom left) by passing the graph origin in the canvas coordinates system.
pub fn canvas_point(origin: Point, p: Point) -> Point {
    Point {
        x: origin.x + p.x,
        y: origin.y - p.y,
    }
}

/// CanvasPointFromFloat64Point rounds coordinates to the nearest integer and
/// converts Cartesian coordinates to canvas coordinates.
pub fn canvas_point_from_float64_point(origin: Point, f: Float64Point) -> Point {
    canvas_point(origin, new_point_from_float64_point(f))
}

/// The style subset leet applies to canvas cells (`lipgloss.Style`
/// stand-in): a resolved foreground color, a resolved background color
/// (used by the inspection-legend overlay — Go `inspectionLegendStyle`
/// sets `Background`, epochlinechart.go `drawInspectionOverlay`), plus
/// the bold flag. Adaptive colors are resolved to [`Rgb`] before
/// reaching the canvas (`AdaptiveColor::resolve`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CellStyle {
    pub fg: Option<Rgb>,
    pub bg: Option<Rgb>,
    pub bold: bool,
}

/// Cell contains a rune and its style for rendering.
///
/// The default Cell mirrors Go's zero value: the Null rune `'\u{0000}'`
/// (rendered as a space) with no styling.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Cell {
    pub ch: char,
    pub fg: Option<Rgb>,
    pub bg: Option<Rgb>,
    pub bold: bool,
}

impl Cell {
    /// NewCellWithStyle returns Cell with given rune and style.
    pub fn new_with_style(ch: char, s: CellStyle) -> Cell {
        Cell {
            ch,
            fg: s.fg,
            bg: s.bg,
            bold: s.bold,
        }
    }
}

/// Model contains the state of a canvas: a rows×cols grid of [`Cell`]s with
/// a simulated viewport (Go `canvas.Model`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Canvas {
    // overall canvas size (Go image.Rectangle `area`; 0,0 is top left)
    width: i64,
    height: i64,
    content: Vec<Vec<Cell>>,

    /// Simulated viewport width to display contents of the canvas.
    pub view_width: i64,
    /// Simulated viewport height to display contents of the canvas.
    pub view_height: i64,

    // internal coordinates tracking the viewport cursor; the contents will
    // be displayed from top to bottom and left to right of the cursor
    cursor: Point,
}

impl Canvas {
    /// New returns a canvas initialized with given width and height.
    pub fn new(w: i64, h: i64) -> Canvas {
        // PARITY: Go's `make` would panic on negative sizes; clamped to 0
        // like resize (leet only constructs 1x1 parked charts).
        let w = w.max(0);
        let h = h.max(0);
        Canvas {
            width: w,
            height: h,
            content: vec![vec![Cell::default(); w as usize]; h as usize],
            view_width: w,
            view_height: h,
            cursor: Point::default(),
        }
    }

    /// Width returns canvas width.
    pub fn width(&self) -> i64 {
        self.width
    }

    /// Height returns canvas height.
    pub fn height(&self) -> i64 {
        self.height
    }

    /// Resize will resize canvas to new height and width, and resets cursor.
    /// Will truncate existing content if canvas size shrinks. Does not change
    /// viewport for displaying contents. Negative w or h are clamped to 0 —
    /// Go's make([]T, n) would otherwise panic, and dimension underflow is
    /// common in UI layout math (e.g. msg.Height-N during initial
    /// WindowSizeMsg).
    pub fn resize(&mut self, w: i64, h: i64) {
        let w = w.max(0);
        let h = h.max(0);
        // create new lines and copy over previous contents
        let mut new_lines = vec![vec![Cell::default(); w as usize]; h as usize];
        for (i, line) in new_lines.iter_mut().enumerate() {
            if (i as i64) < self.height {
                // copy over previous line
                for (j, r) in self.content[i].iter().enumerate() {
                    if (j as i64) >= w {
                        break;
                    }
                    line[j] = *r;
                }
            }
        }
        self.width = w;
        self.height = h;
        self.cursor = Point { x: 0, y: 0 };
        self.content = new_lines;
    }

    /// Clear will reset canvas contents.
    pub fn clear(&mut self) {
        let dx = self.width as usize;
        for line in &mut self.content {
            *line = vec![Cell::default(); dx];
        }
    }

    /// SetStringWithStyle copies string as rune values into the canvas line
    /// starting at coordinates (X, Y). Style will be applied to all Cells.
    /// Truncates values exceeding the canvas width.
    pub fn set_string_with_style(&mut self, p: Point, l: &str, s: CellStyle) -> bool {
        let runes: Vec<char> = l.chars().collect();
        self.set_runes_with_style(p, &runes, s)
    }

    /// SetRunesWithStyle copies rune values into the canvas line starting at
    /// coordinates (X, Y). Style will be applied to all Cells.
    /// Truncates values exceeding the canvas width.
    pub fn set_runes_with_style(&mut self, p: Point, l: &[char], s: CellStyle) -> bool {
        if !self.inside_y_bounds(p.y) {
            return false;
        }
        let mut x_idx = p.x;
        for &r in l {
            if self.inside_x_bounds(x_idx) {
                self.content[p.y as usize][x_idx as usize] = Cell::new_with_style(r, s);
            }
            x_idx += 1;
        }
        true
    }

    /// SetCell sets a Cell using (X,Y) coordinates of canvas.
    pub fn set_cell(&mut self, p: Point, c: Cell) -> bool {
        if !self.in_area(p) {
            return false;
        }
        self.content[p.y as usize][p.x as usize] = c;
        true
    }

    /// Cell returns the Cell located at (X,Y) coordinates of canvas.
    /// Returns the default Cell if coordinates are out of bounds.
    pub fn cell(&self, p: Point) -> Cell {
        if !self.in_area(p) {
            return Cell::default();
        }
        self.content[p.y as usize][p.x as usize]
    }

    /// The text content of the viewport, one string per visible row — the
    /// styling-stripped equivalent of Go `View()` (which joins these rows
    /// with newlines). Null runes render as spaces, exactly like Go.
    pub fn text_rows(&self) -> Vec<String> {
        let mut rows = Vec::new();
        let end_y = self.cursor.y + self.view_height - 1;
        let end_x = self.cursor.x + self.view_width - 1;
        let mut i = self.cursor.y;
        while i <= end_y {
            if i >= self.height {
                break;
            }
            let mut row = String::new();
            let mut j = self.cursor.x;
            while j <= end_x {
                if j >= self.width {
                    break;
                }
                let cell = self.content[i as usize][j as usize];
                if cell.ch == '\u{0000}' {
                    row.push(' ');
                } else {
                    row.push(cell.ch);
                }
                j += 1;
            }
            rows.push(row);
            i += 1;
        }
        rows
    }

    /// Whether the point is within canvas bounds (Go `p.In(m.area)`).
    fn in_area(&self, p: Point) -> bool {
        (0..self.width).contains(&p.x) && (0..self.height).contains(&p.y)
    }

    /// insideXBounds returns whether X coordinate is within canvas bounds.
    fn inside_x_bounds(&self, x: i64) -> bool {
        (0..self.width).contains(&x)
    }

    /// insideYBounds returns whether Y coordinate is within canvas bounds.
    fn inside_y_bounds(&self, y: i64) -> bool {
        (0..self.height).contains(&y)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn style() -> CellStyle {
        CellStyle {
            fg: Some(Rgb(0xEE, 0x22, 0x11)),
            bg: None,
            bold: true,
        }
    }

    #[test]
    fn set_cell_and_cell_bounds() {
        let mut c = Canvas::new(3, 2);
        assert!(c.set_cell(Point { x: 0, y: 0 }, Cell::new_with_style('a', style())));
        assert!(c.set_cell(Point { x: 2, y: 1 }, Cell::new_with_style('b', style())));
        assert_eq!(
            c.cell(Point { x: 0, y: 0 }),
            Cell {
                ch: 'a',
                fg: Some(Rgb(0xEE, 0x22, 0x11)),
                bg: None,
                bold: true
            }
        );
        // Out-of-bounds writes are rejected...
        assert!(!c.set_cell(Point { x: -1, y: 0 }, Cell::new_with_style('x', style())));
        assert!(!c.set_cell(Point { x: 3, y: 0 }, Cell::new_with_style('x', style())));
        assert!(!c.set_cell(Point { x: 0, y: 2 }, Cell::new_with_style('x', style())));
        // ...and out-of-bounds reads return the zero-value (Null rune) Cell.
        assert_eq!(c.cell(Point { x: 5, y: 5 }), Cell::default());
        assert_eq!(c.cell(Point { x: 1, y: 0 }).ch, '\u{0000}');
    }

    #[test]
    fn set_string_truncates_at_width_and_skips_negative_x() {
        let mut c = Canvas::new(4, 2);
        // Truncated at the right edge: only 'a' and 'b' land.
        assert!(c.set_string_with_style(Point { x: 2, y: 1 }, "abcd", style()));
        assert_eq!(c.cell(Point { x: 2, y: 1 }).ch, 'a');
        assert_eq!(c.cell(Point { x: 3, y: 1 }).ch, 'b');
        // Negative start X: runes left of column 0 are dropped, the rest
        // land shifted (Go increments xIdx past the bounds check).
        assert!(c.set_string_with_style(Point { x: -1, y: 0 }, "xy", style()));
        assert_eq!(c.cell(Point { x: 0, y: 0 }).ch, 'y');
        assert_eq!(c.cell(Point { x: 1, y: 0 }).ch, '\u{0000}');
        // Y out of bounds returns false without writing.
        assert!(!c.set_string_with_style(Point { x: 0, y: 2 }, "z", style()));
        assert!(!c.set_string_with_style(Point { x: 0, y: -1 }, "z", style()));
    }

    #[test]
    fn resize_preserves_overlap_and_truncates_rest() {
        let mut c = Canvas::new(3, 2);
        c.set_cell(Point { x: 0, y: 0 }, Cell::new_with_style('a', style()));
        c.set_cell(Point { x: 2, y: 1 }, Cell::new_with_style('q', style()));
        c.resize(2, 3);
        assert_eq!((c.width(), c.height()), (2, 3));
        // Overlapping content preserved; truncated column gone; new row is
        // default cells.
        assert_eq!(c.cell(Point { x: 0, y: 0 }).ch, 'a');
        assert_eq!(c.cell(Point { x: 1, y: 1 }).ch, '\u{0000}');
        assert_eq!(c.cell(Point { x: 0, y: 2 }), Cell::default());
        // Viewport is NOT changed by resize (Go comment: "Does not change
        // viewport for displaying contents").
        assert_eq!((c.view_width, c.view_height), (3, 2));
        // Negative sizes clamp to 0 (the vendored ntcharts patch).
        c.resize(-3, -1);
        assert_eq!((c.width(), c.height()), (0, 0));
        assert_eq!(c.text_rows(), Vec::<String>::new());
    }

    #[test]
    fn new_clamps_negative_sizes() {
        let c = Canvas::new(-2, -5);
        assert_eq!((c.width(), c.height()), (0, 0));
        assert_eq!(c.text_rows(), Vec::<String>::new());
    }

    #[test]
    fn clear_resets_cells() {
        let mut c = Canvas::new(2, 2);
        c.set_cell(Point { x: 1, y: 1 }, Cell::new_with_style('z', style()));
        c.clear();
        assert_eq!(c.cell(Point { x: 1, y: 1 }), Cell::default());
        assert_eq!(c.text_rows(), vec!["  ".to_string(), "  ".to_string()]);
    }

    #[test]
    fn text_rows_renders_null_as_space_and_clips_to_view() {
        let mut c = Canvas::new(3, 2);
        c.set_cell(Point { x: 0, y: 0 }, Cell::new_with_style('a', style()));
        c.set_cell(Point { x: 2, y: 1 }, Cell::new_with_style('b', style()));
        assert_eq!(c.text_rows(), vec!["a  ".to_string(), "  b".to_string()]);
        // Viewport smaller than the canvas clips.
        c.view_width = 2;
        c.view_height = 1;
        assert_eq!(c.text_rows(), vec!["a ".to_string()]);
        // Viewport larger than the canvas clips at the canvas bounds.
        c.view_width = 10;
        c.view_height = 10;
        assert_eq!(c.text_rows(), vec!["a  ".to_string(), "  b".to_string()]);
        // Zero-width viewport yields empty rows (Go inner loop never runs).
        c.view_width = 0;
        c.view_height = 2;
        assert_eq!(c.text_rows(), vec![String::new(), String::new()]);
    }

    #[test]
    fn background_color_round_trips_through_cells() {
        // The inspection-legend overlay (epochlinechart.go
        // drawInspectionOverlay) writes background-styled cells:
        // inspectionLegendStyle sets Background #EEEEEE light / #333333
        // dark, and blockStyle inherits it under the series foreground.
        let legend = CellStyle {
            fg: None,
            bg: Some(Rgb(0x33, 0x33, 0x33)),
            bold: false,
        };
        let block = CellStyle {
            fg: Some(Rgb(0xEE, 0x22, 0x11)),
            bg: Some(Rgb(0x33, 0x33, 0x33)),
            bold: false,
        };
        let mut c = Canvas::new(3, 1);
        assert!(c.set_cell(Point { x: 0, y: 0 }, Cell::new_with_style('█', block)));
        assert!(c.set_string_with_style(Point { x: 1, y: 0 }, " x", legend));
        assert_eq!(
            c.cell(Point { x: 0, y: 0 }),
            Cell {
                ch: '█',
                fg: Some(Rgb(0xEE, 0x22, 0x11)),
                bg: Some(Rgb(0x33, 0x33, 0x33)),
                bold: false
            }
        );
        assert_eq!(c.cell(Point { x: 2, y: 0 }).bg, Some(Rgb(0x33, 0x33, 0x33)));
        assert_eq!(c.cell(Point { x: 2, y: 0 }).fg, None);
        // The zero-value Cell carries no background.
        assert_eq!(Cell::default().bg, None);
    }

    #[test]
    fn point_rounding_half_away_from_zero() {
        // math.Round rounds half away from zero — not banker's rounding.
        assert_eq!(
            new_point_from_float64_point(Float64Point { x: 0.5, y: 2.5 }),
            Point { x: 1, y: 3 }
        );
        assert_eq!(
            new_point_from_float64_point(Float64Point { x: 1.5, y: 3.5 }),
            Point { x: 2, y: 4 }
        );
        assert_eq!(
            new_point_from_float64_point(Float64Point { x: -0.5, y: -2.5 }),
            Point { x: -1, y: -3 }
        );
    }

    #[test]
    fn canvas_point_flips_y_about_origin() {
        assert_eq!(
            canvas_point(Point { x: 1, y: 4 }, Point { x: 2, y: 3 }),
            Point { x: 3, y: 1 }
        );
        assert_eq!(
            canvas_point_from_float64_point(Point { x: 0, y: 3 }, Float64Point { x: 1.5, y: 0.5 }),
            Point { x: 2, y: 2 }
        );
    }
}
