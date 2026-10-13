//! A styled character canvas, mirroring ntcharts' canvas.Model semantics.

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::Style;

/// A single canvas cell. `ch == '\0'` means unset (renders as blank).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Cell {
    pub ch: char,
    pub style: Style,
}

pub const NULL_CELL: Cell = Cell {
    ch: '\0',
    style: Style::new(),
};

/// A width×height grid of styled runes with (0,0) at the top left.
#[derive(Debug, Clone)]
pub struct Canvas {
    width: usize,
    height: usize,
    cells: Vec<Cell>,
}

impl Canvas {
    pub fn new(width: usize, height: usize) -> Self {
        Self {
            width,
            height,
            cells: vec![NULL_CELL; width * height],
        }
    }

    pub fn width(&self) -> usize {
        self.width
    }

    pub fn height(&self) -> usize {
        self.height
    }

    pub fn clear(&mut self) {
        self.cells.fill(NULL_CELL);
    }

    pub fn resize(&mut self, width: usize, height: usize) {
        if width == self.width && height == self.height {
            return;
        }
        self.width = width;
        self.height = height;
        self.cells = vec![NULL_CELL; width * height];
    }

    pub fn cell(&self, x: i32, y: i32) -> Cell {
        if x < 0 || y < 0 || x as usize >= self.width || y as usize >= self.height {
            return NULL_CELL;
        }
        self.cells[y as usize * self.width + x as usize]
    }

    pub fn set_cell(&mut self, x: i32, y: i32, cell: Cell) {
        if x < 0 || y < 0 || x as usize >= self.width || y as usize >= self.height {
            return;
        }
        self.cells[y as usize * self.width + x as usize] = cell;
    }

    pub fn set_string(&mut self, x: i32, y: i32, s: &str, style: Style) {
        let mut cx = x;
        for ch in s.chars() {
            self.set_cell(cx, y, Cell { ch, style });
            cx += 1;
        }
    }

    /// Renders the canvas into a ratatui buffer at the given area's origin,
    /// clipping to the area.
    pub fn render(&self, area: Rect, buf: &mut Buffer) {
        let max_y = (self.height as u16).min(area.height);
        let max_x = (self.width as u16).min(area.width);
        for y in 0..max_y {
            for x in 0..max_x {
                let cell = self.cells[y as usize * self.width + x as usize];
                if cell.ch == '\0' {
                    continue;
                }
                if let Some(buf_cell) = buf.cell_mut((area.x + x, area.y + y)) {
                    buf_cell.set_char(cell.ch);
                    buf_cell.set_style(cell.style);
                }
            }
        }
    }
}
