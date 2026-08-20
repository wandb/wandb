//! Normalized cell grid — the common representation both sides of the
//! differential harness are reduced to before diffing.
//!
//! The Go oracle's PTY output is parsed into a grid via `avt`; the Rust
//! implementation renders into ratatui's `TestBackend` and converts from
//! there. Diff policy (tiers, masks) lives in `diff.rs`.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CellColor {
    Indexed(u8),
    Rgb(u8, u8, u8),
}

/// Attribute bitmask: bold=1, faint=2, italic=4, underline=8, blink=16,
/// inverse=32, strikethrough=64.
pub type Attrs = u8;

pub const ATTR_BOLD: Attrs = 1;
pub const ATTR_FAINT: Attrs = 2;
pub const ATTR_ITALIC: Attrs = 4;
pub const ATTR_UNDERLINE: Attrs = 8;
pub const ATTR_BLINK: Attrs = 16;
pub const ATTR_INVERSE: Attrs = 32;
pub const ATTR_STRIKETHROUGH: Attrs = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Cell {
    pub ch: char,
    /// 0 for the continuation cell of a wide character.
    pub width: u8,
    pub fg: Option<CellColor>,
    pub bg: Option<CellColor>,
    pub attrs: Attrs,
}

impl Default for Cell {
    fn default() -> Self {
        Cell {
            ch: ' ',
            width: 1,
            fg: None,
            bg: None,
            attrs: 0,
        }
    }
}

impl Cell {
    /// A blank cell for character-tier comparison purposes: a space or a
    /// wide-char continuation, regardless of style.
    pub fn is_char_blank(&self) -> bool {
        self.ch == ' ' || self.width == 0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CursorState {
    pub col: usize,
    pub row: usize,
    pub visible: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Grid {
    pub cols: usize,
    pub rows: usize,
    /// Row-major, exactly `cols * rows` entries.
    pub cells: Vec<Cell>,
    pub cursor: CursorState,
}

impl Grid {
    pub fn blank(cols: usize, rows: usize) -> Self {
        Grid {
            cols,
            rows,
            cells: vec![Cell::default(); cols * rows],
            cursor: CursorState {
                col: 0,
                row: 0,
                visible: false,
            },
        }
    }

    pub fn cell(&self, col: usize, row: usize) -> &Cell {
        &self.cells[row * self.cols + col]
    }

    pub fn cell_mut(&mut self, col: usize, row: usize) -> &mut Cell {
        &mut self.cells[row * self.cols + col]
    }

    /// Plain-text rows (chars only), used in reports and snapshots.
    pub fn text_rows(&self) -> Vec<String> {
        (0..self.rows)
            .map(|r| {
                (0..self.cols)
                    .map(|c| {
                        let cell = self.cell(c, r);
                        if cell.width == 0 { '\0' } else { cell.ch }
                    })
                    .filter(|&ch| ch != '\0')
                    .collect()
            })
            .collect()
    }

    /// Blank out a rectangular region (used for DSL masks).
    pub fn mask(&mut self, x: usize, y: usize, w: usize, h: usize) {
        for row in y..(y + h).min(self.rows) {
            for col in x..(x + w).min(self.cols) {
                *self.cell_mut(col, row) = Cell::default();
            }
        }
    }
}

/// Convert an `avt` screen view into a `Grid`.
pub fn grid_from_avt(vt: &avt::Vt) -> Grid {
    let (cols, rows) = vt.size();
    let mut grid = Grid::blank(cols, rows);
    let cursor = vt.cursor();
    grid.cursor = CursorState {
        col: cursor.col,
        row: cursor.row,
        visible: cursor.visible,
    };

    for (row, line) in vt.view().iter().enumerate().take(rows) {
        for (col, cell) in line.cells().iter().enumerate().take(cols) {
            let pen = cell.pen();
            let mut attrs = 0u8;
            if pen.is_bold() {
                attrs |= ATTR_BOLD;
            }
            if pen.is_faint() {
                attrs |= ATTR_FAINT;
            }
            if pen.is_italic() {
                attrs |= ATTR_ITALIC;
            }
            if pen.is_underline() {
                attrs |= ATTR_UNDERLINE;
            }
            if pen.is_blink() {
                attrs |= ATTR_BLINK;
            }
            if pen.is_inverse() {
                attrs |= ATTR_INVERSE;
            }
            if pen.is_strikethrough() {
                attrs |= ATTR_STRIKETHROUGH;
            }
            *grid.cell_mut(col, row) = Cell {
                ch: cell.char(),
                width: cell.width() as u8,
                fg: pen.foreground().map(convert_color),
                bg: pen.background().map(convert_color),
                attrs,
            };
        }
    }
    grid
}

fn convert_color(c: avt::Color) -> CellColor {
    match c {
        avt::Color::Indexed(i) => CellColor::Indexed(i),
        avt::Color::RGB(rgb) => CellColor::Rgb(rgb.r, rgb.g, rgb.b),
    }
}
