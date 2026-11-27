//! Braille dot grid, a port of ntcharts' BrailleGrid + PatternDotsGrid.
//!
//! Each braille pattern rune is 2 dots wide and 4 dots tall, so a canvas of
//! W×H cells is backed by a (2W)×(4H) dot grid.

/// Beginning of Unicode Braille Patterns (the empty pattern).
pub const BRAILLE_BLOCK_OFFSET: u32 = 0x2800;

/// Braille dot bit offsets in dot-number order 1..8.
const DOT_OFFSETS: [u32; 8] = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80];

/// A 2D dot grid with (X, Y) floating point coordinates used to produce
/// braille pattern runes. Uses canvas coordinates: (0,0) is top left.
pub struct BrailleGrid {
    min_x: f64,
    max_x: f64,
    min_y: f64,
    max_y: f64,
    g_width: usize,
    g_height: usize,
    dots: Vec<bool>,
}

impl BrailleGrid {
    /// Creates a grid for a canvas of `w`×`h` cells covering the given data
    /// ranges.
    pub fn new(w: usize, h: usize, min_x: f64, max_x: f64, min_y: f64, max_y: f64) -> Self {
        let g_width = w * 2;
        let g_height = h * 4;
        Self {
            min_x,
            max_x,
            min_y,
            max_y,
            g_width,
            g_height,
            dots: vec![false; g_width * g_height],
        }
    }

    /// Converts a Cartesian data point to grid (dot) coordinates.
    pub fn grid_point(&self, fx: f64, fy: f64) -> (i32, i32) {
        let mut sx = 0.0;
        let mut sy = 0.0;
        let dx = self.max_x - self.min_x;
        let dy = self.max_y - self.min_y;
        if dx > 0.0 {
            sx = (fx - self.min_x) * (self.g_width as f64 - 1.0) / dx;
        }
        if dy > 0.0 {
            sy = (fy - self.min_y) * (self.g_height as f64 - 1.0) / dy;
        }
        // Cartesian -> canvas coordinates with origin at bottom left.
        let x = go_round(sx) as i32;
        let y = self.g_height as i32 - 1 - go_round(sy) as i32;
        (x, y)
    }

    /// Sets the dot at grid coordinates.
    pub fn set(&mut self, x: i32, y: i32) {
        if x < 0 || y < 0 || x as usize >= self.g_width || y as usize >= self.g_height {
            return;
        }
        self.dots[y as usize * self.g_width + x as usize] = true;
    }

    fn get(&self, x: usize, y: usize) -> bool {
        if x >= self.g_width || y >= self.g_height {
            return false;
        }
        self.dots[y * self.g_width + x]
    }

    /// Returns rows of braille pattern runes covering the whole grid.
    pub fn braille_patterns(&self) -> Vec<Vec<char>> {
        let mut rows = Vec::with_capacity(self.g_height.div_ceil(4));
        let mut y = 0;
        while y < self.g_height {
            let mut row = Vec::with_capacity(self.g_width.div_ceil(2));
            let mut x = 0;
            while x < self.g_width {
                row.push(self.braille_pattern_at(x, y));
                x += 2;
            }
            rows.push(row);
            y += 4;
        }
        rows
    }

    fn braille_pattern_at(&self, x: usize, y: usize) -> char {
        let mut b = BRAILLE_BLOCK_OFFSET;
        // Left column: dots 1, 2, 3, 7.
        if self.get(x, y) {
            b |= DOT_OFFSETS[0];
        }
        if self.get(x, y + 1) {
            b |= DOT_OFFSETS[1];
        }
        if self.get(x, y + 2) {
            b |= DOT_OFFSETS[2];
        }
        if self.get(x, y + 3) {
            b |= DOT_OFFSETS[6];
        }
        // Right column: dots 4, 5, 6, 8.
        if self.get(x + 1, y) {
            b |= DOT_OFFSETS[3];
        }
        if self.get(x + 1, y + 1) {
            b |= DOT_OFFSETS[4];
        }
        if self.get(x + 1, y + 2) {
            b |= DOT_OFFSETS[5];
        }
        if self.get(x + 1, y + 3) {
            b |= DOT_OFFSETS[7];
        }
        char::from_u32(b).unwrap_or(' ')
    }
}

/// Draws a line between two grid points using Bresenham's algorithm.
pub fn draw_line(grid: &mut BrailleGrid, p1: (i32, i32), p2: (i32, i32)) {
    let dx = (p2.0 - p1.0).abs();
    let dy = (p2.1 - p1.1).abs();
    let sx = if p1.0 > p2.0 { -1 } else { 1 };
    let sy = if p1.1 > p2.1 { -1 } else { 1 };

    let mut err = dx - dy;
    let (mut x, mut y) = p1;

    loop {
        grid.set(x, y);
        if x == p2.0 && y == p2.1 {
            break;
        }
        let e2 = 2 * err;
        if e2 > -dy {
            err -= dy;
            x += sx;
        }
        if e2 < dx {
            err += dx;
            y += sy;
        }
    }
}

/// Rounds half away from zero, matching Go's `math.Round`.
pub fn go_round(v: f64) -> f64 {
    if v < 0.0 {
        -(-v + 0.5).floor()
    } else {
        (v + 0.5).floor()
    }
}

/// True if `r` is a braille pattern rune.
pub fn is_braille_pattern(r: char) -> bool {
    (0x2800..=0x28FF).contains(&(r as u32))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_dot_patterns() {
        // 1x1 canvas = 2x4 dots.
        let mut g = BrailleGrid::new(1, 1, 0.0, 1.0, 0.0, 1.0);
        g.set(0, 0); // top-left dot => dot 1
        let rows = g.braille_patterns();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].len(), 1);
        assert_eq!(rows[0][0] as u32, 0x2801);

        let mut g = BrailleGrid::new(1, 1, 0.0, 1.0, 0.0, 1.0);
        g.set(1, 3); // bottom-right dot => dot 8
        assert_eq!(g.braille_patterns()[0][0] as u32, 0x2880);
    }

    #[test]
    fn grid_point_maps_corners() {
        let g = BrailleGrid::new(4, 2, 0.0, 4.0, 0.0, 2.0);
        // Bottom-left data point -> bottom-left grid dot.
        assert_eq!(g.grid_point(0.0, 0.0), (0, 7));
        // Top-right data point -> top-right grid dot.
        assert_eq!(g.grid_point(4.0, 2.0), (7, 0));
    }

    #[test]
    fn bresenham_diagonal() {
        let mut g = BrailleGrid::new(2, 1, 0.0, 1.0, 0.0, 1.0);
        draw_line(&mut g, (0, 3), (3, 0));
        // Diagonal dots set: (0,3), (1,2), (2,1), (3,0).
        let rows = g.braille_patterns();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].len(), 2);
        // Left cell: (0,3)=dot7, (1,2)=dot6 => 0x40 | 0x20.
        assert_eq!(rows[0][0] as u32, 0x2800 | 0x40 | 0x20);
        // Right cell: (2,1)=dot2, (3,0)=dot4 => 0x02 | 0x08.
        assert_eq!(rows[0][1] as u32, 0x2800 | 0x02 | 0x08);
    }

    #[test]
    fn go_round_half_away_from_zero() {
        assert_eq!(go_round(0.5), 1.0);
        assert_eq!(go_round(-0.5), -1.0);
        assert_eq!(go_round(1.4), 1.0);
    }
}
