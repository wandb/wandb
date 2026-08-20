//! Grid layout math and pagination shared by chart grids.

use crate::theme::{CHART_BORDER_SIZE, CHART_TITLE_HEIGHT};

/// Describes the desired (configured) grid and the minimums required for one
/// chart cell to render reasonably.
#[derive(Debug, Clone, Copy)]
pub struct GridSpec {
    /// Configured rows (before clamping).
    pub rows: i32,
    /// Configured cols (before clamping).
    pub cols: i32,
    /// Inner chart width (no borders).
    pub min_cell_w: i32,
    /// Inner chart height (no borders + title line).
    pub min_cell_h: i32,
    /// Lines reserved above the grid (section header etc.).
    pub header_lines: i32,
}

/// The final rows/cols after clamping to available space.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GridSize {
    pub rows: i32,
    pub cols: i32,
}

/// Computed sizes for one cell (uniform across the grid). The `with_padding`
/// variants include the border/title overhead placed around charts.
#[derive(Debug, Clone, Copy, Default)]
pub struct GridDims {
    /// Inner chart width (usable by the chart).
    pub cell_w: i32,
    /// Inner chart height (usable by the chart).
    pub cell_h: i32,
    /// Full cell slot width (including border/title).
    pub cell_w_with_padding: i32,
    /// Full cell slot height (including border/title).
    pub cell_h_with_padding: i32,
}

/// What type of UI element is focused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FocusType {
    #[default]
    None,
    MainChart,
    SystemChart,
}

/// Tracks the currently focused chart in a grid.
#[derive(Debug, Clone, Default)]
pub struct Focus {
    pub ty: FocusType,
    pub row: i32,
    pub col: i32,
    pub title: String,
}

impl Focus {
    pub fn new() -> Self {
        Self {
            ty: FocusType::None,
            row: -1,
            col: -1,
            title: String::new(),
        }
    }

    pub fn set(&mut self, ty: FocusType, row: i32, col: i32, title: &str) {
        self.ty = ty;
        self.row = row;
        self.col = col;
        self.title = title.to_string();
    }

    pub fn reset(&mut self) {
        self.ty = FocusType::None;
        self.row = -1;
        self.col = -1;
        self.title.clear();
    }
}

/// Rows*cols with basic safety.
pub fn items_per_page(size: GridSize) -> usize {
    if size.rows <= 0 || size.cols <= 0 {
        return 0;
    }
    (size.rows * size.cols) as usize
}

/// Clamps rows/cols so that at least the configured minimum chart sizes fit
/// in the current viewport.
pub fn effective_grid_size(avail_w: i32, mut avail_h: i32, spec: GridSpec) -> GridSize {
    // Subtract header space from available height (never below 0).
    avail_h = (avail_h - spec.header_lines).max(0);

    // Minimum padded cell sizes: chart + borders + title.
    let min_w_with_pad = spec.min_cell_w + CHART_BORDER_SIZE as i32;
    let min_h_with_pad = spec.min_cell_h + CHART_BORDER_SIZE as i32 + CHART_TITLE_HEIGHT;

    // Compute the maximum grid that fits.
    let max_cols = if min_w_with_pad > 0 {
        (avail_w / min_w_with_pad).max(1)
    } else {
        1
    };
    let max_rows = if min_h_with_pad > 0 {
        (avail_h / min_h_with_pad).max(1)
    } else {
        1
    };

    // Clamp to what fits, never below 1.
    GridSize {
        rows: spec.rows.max(1).min(max_rows),
        cols: spec.cols.max(1).min(max_cols),
    }
}

/// Uniform per-cell sizes for the given grid size.
pub fn compute_grid_dims(avail_w: i32, mut avail_h: i32, spec: GridSpec) -> GridDims {
    let size = effective_grid_size(avail_w, avail_h, spec);

    // Subtract header lines (never below 0).
    avail_h = (avail_h - spec.header_lines).max(0);

    // Padded cell sizes.
    let cell_w_with_pad = if size.cols > 0 {
        avail_w / size.cols
    } else {
        0
    };
    let cell_h_with_pad = if size.rows > 0 {
        avail_h / size.rows
    } else {
        0
    };

    // Inner chart sizes (respect minimums).
    let inner_w = (cell_w_with_pad - CHART_BORDER_SIZE as i32)
        .max(spec.min_cell_w)
        .max(0);
    let inner_h = (cell_h_with_pad - CHART_BORDER_SIZE as i32 - CHART_TITLE_HEIGHT)
        .max(spec.min_cell_h)
        .max(0);

    GridDims {
        cell_w: inner_w,
        cell_h: inner_h,
        cell_w_with_padding: cell_w_with_pad,
        cell_h_with_padding: cell_h_with_pad,
    }
}

/// Grid page navigation.
#[derive(Debug, Clone, Copy, Default)]
pub struct GridNavigator {
    current_page: usize,
    total_pages: usize,
}

impl GridNavigator {
    /// Changes the current page by direction (-1 for prev, +1 for next),
    /// wrapping around. Returns true if navigation occurred.
    pub fn navigate(&mut self, direction: i32) -> bool {
        if self.total_pages <= 1 {
            return false;
        }

        let old_page = self.current_page;
        let total = self.total_pages as i32;
        let mut page = self.current_page as i32 + direction;
        if page < 0 {
            page = total - 1;
        } else if page >= total {
            page = 0;
        }
        self.current_page = page as usize;
        self.current_page != old_page
    }

    /// Recalculates total pages based on item count and page size.
    pub fn update_total_pages(&mut self, item_count: usize, items_per_page: usize) {
        if items_per_page == 0 {
            self.total_pages = 0;
            return;
        }
        self.total_pages = item_count.div_ceil(items_per_page);

        // Ensure current page is valid.
        if self.current_page >= self.total_pages && self.total_pages > 0 {
            self.current_page = self.total_pages - 1;
        }
    }

    pub fn current_page(&self) -> usize {
        self.current_page
    }

    pub fn set_current_page(&mut self, page: usize) {
        self.current_page = page;
    }

    pub fn total_pages(&self) -> usize {
        self.total_pages
    }

    /// Jumps to the first page. Returns true if the page changed.
    pub fn go_home(&mut self) -> bool {
        if self.total_pages == 0 || self.current_page == 0 {
            return false;
        }
        self.current_page = 0;
        true
    }

    /// Jumps to the last page. Returns true if the page changed.
    pub fn go_end(&mut self) -> bool {
        if self.total_pages == 0 {
            return false;
        }
        let last = self.total_pages - 1;
        if self.current_page == last {
            return false;
        }
        self.current_page = last;
        true
    }

    /// The start and end indices for the current page.
    pub fn page_bounds(&self, item_count: usize, items_per_page: usize) -> (usize, usize) {
        let start = self.current_page * items_per_page;
        let end = (start + items_per_page).min(item_count);
        (start.min(end), end)
    }
}

pub(crate) fn clamp_i32(v: i32, lo: i32, hi: i32) -> i32 {
    v.max(lo).min(hi)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(rows: i32, cols: i32) -> GridSpec {
        GridSpec {
            rows,
            cols,
            min_cell_w: 20,
            min_cell_h: 5,
            header_lines: 1,
        }
    }

    #[test]
    fn effective_size_clamps_to_viewport() {
        // 80x24 viewport: max cols = 80/22 = 3, max rows = 23/8 = 2.
        let size = effective_grid_size(80, 24, spec(4, 4));
        assert_eq!(size, GridSize { rows: 2, cols: 3 });
    }

    #[test]
    fn dims_respect_minimums() {
        let dims = compute_grid_dims(10, 5, spec(1, 1));
        assert!(dims.cell_w >= 20);
        assert!(dims.cell_h >= 5);
    }

    #[test]
    fn navigator_wraps() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(25, 10);
        assert_eq!(nav.total_pages(), 3);
        assert!(nav.navigate(-1));
        assert_eq!(nav.current_page(), 2);
        assert!(nav.navigate(1));
        assert_eq!(nav.current_page(), 0);
        assert!(!nav.go_home());
        assert!(nav.go_end());
        assert_eq!(nav.page_bounds(25, 10), (20, 25));
    }
}
