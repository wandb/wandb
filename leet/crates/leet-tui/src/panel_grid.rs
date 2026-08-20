//! Port of `core/internal/leet/panelgrid.go`.
//!
//! Pure grid math: Go int fields port as `isize` (PORTING.md numeric rules);
//! clamping matches Go exactly.

// PARITY: ChartBorderSize/ChartTitleHeight live in styles.go in Go; the Rust
// styles module hosts them as i64 — cast once here so the grid math stays isize.
const CHART_BORDER_SIZE: isize = leet_charts::styles::CHART_BORDER_SIZE as isize;
const CHART_TITLE_HEIGHT: isize = leet_charts::styles::CHART_TITLE_HEIGHT as isize;

/// GridSpec describes the desired (configured) grid and the minimums required
/// for one chart cell to render reasonably.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct GridSpec {
    /// Configured rows (before clamping).
    pub rows: isize,
    /// Configured cols (before clamping).
    pub cols: isize,
    /// Inner chart width (no borders).
    pub min_cell_w: isize,
    /// Inner chart height (no borders + title line).
    pub min_cell_h: isize,
    /// Lines reserved above the grid (section header etc.).
    pub header_lines: isize,
}

/// GridSize is the final rows/cols after clamping to available space.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct GridSize {
    pub rows: isize,
    pub cols: isize,
}

/// GridDims are the computed sizes for one cell (uniform across the grid).
/// `*_with_padding` includes the border/title overhead the caller places around charts.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct GridDims {
    /// Inner chart width (usable by the chart).
    pub cell_w: isize,
    /// Inner chart height (usable by the chart).
    pub cell_h: isize,
    /// Full cell slot width (including border/title).
    pub cell_w_with_padding: isize,
    /// Full cell slot height (including border/title).
    pub cell_h_with_padding: isize,
}

/// Focus tracks the currently focused chart in the grid.
// PARITY: Go names the first field `Type`; `type` is a Rust keyword, so it
// ports as `focus_type`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Focus {
    pub focus_type: FocusType,
    pub row: isize,
    pub col: isize,
    pub title: String,
}

impl Focus {
    /// Port of Go `NewFocus`.
    pub fn new() -> Self {
        Focus {
            focus_type: FocusType::None,
            row: -1,
            col: -1,
            title: String::new(),
        }
    }

    /// Set sets the focus state.
    pub fn set(&mut self, t: FocusType, row: isize, col: isize, title: String) {
        self.focus_type = t;
        self.row = row;
        self.col = col;
        self.title = title;
    }

    /// Reset resets the focus state to factory settings.
    pub fn reset(&mut self) {
        self.focus_type = FocusType::None;
        self.row = -1;
        self.col = -1;
        self.title = String::new();
    }
}

impl Default for Focus {
    // PARITY: Go constructs Focus exclusively via NewFocus (Row/Col start at
    // -1, not the zero value), so Default mirrors NewFocus.
    fn default() -> Self {
        Focus::new()
    }
}

/// FocusType indicates what type of UI element is focused.
// PARITY: Go declares `type FocusType int` with iota values 0..2
// (FocusNone is the zero value).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum FocusType {
    #[default]
    None,
    MainChart,
    SystemChart,
}

/// ItemsPerPage returns Rows*Cols with basic safety.
pub fn items_per_page(size: GridSize) -> isize {
    if size.rows <= 0 || size.cols <= 0 {
        return 0;
    }
    size.rows * size.cols
}

/// EffectiveGridSize clamps Rows/Cols so that at least the configured minimum
/// chart sizes fit in the current viewport.
pub fn effective_grid_size(avail_w: isize, mut avail_h: isize, spec: GridSpec) -> GridSize {
    // Subtract header space from available height (never below 0).
    if avail_h > spec.header_lines {
        avail_h -= spec.header_lines;
    } else {
        avail_h = 0;
    }

    // Minimum padded cell sizes: chart + borders + title.
    let min_w_with_pad = spec.min_cell_w + CHART_BORDER_SIZE;
    let min_h_with_pad = spec.min_cell_h + CHART_BORDER_SIZE + CHART_TITLE_HEIGHT;

    // Compute the maximum grid that fits.
    let mut max_cols = 1;
    if min_w_with_pad > 0 {
        let c = avail_w / min_w_with_pad;
        if c > 1 {
            max_cols = c;
        }
    }
    let mut max_rows = 1;
    if min_h_with_pad > 0 {
        let r = avail_h / min_h_with_pad;
        if r > 1 {
            max_rows = r;
        }
    }

    // Clamp to what fits, never below 1.
    let rows = spec.rows.max(1).min(max_rows);
    let cols = spec.cols.max(1).min(max_cols);

    GridSize { rows, cols }
}

/// ComputeGridDims returns uniform per-cell sizes for the given grid size.
pub fn compute_grid_dims(avail_w: isize, mut avail_h: isize, spec: GridSpec) -> GridDims {
    let size = effective_grid_size(avail_w, avail_h, spec);

    // Subtract header lines (never below 0).
    if avail_h > spec.header_lines {
        avail_h -= spec.header_lines;
    } else {
        avail_h = 0;
    }

    // Padded cell sizes.
    let mut cell_w_with_pad = 0;
    if size.cols > 0 {
        cell_w_with_pad = avail_w / size.cols;
    }
    let mut cell_h_with_pad = 0;
    if size.rows > 0 {
        cell_h_with_pad = avail_h / size.rows;
    }

    // Inner chart sizes (respect minimums).
    let inner_w = (cell_w_with_pad - CHART_BORDER_SIZE)
        .max(spec.min_cell_w)
        .max(0);
    let inner_h = (cell_h_with_pad - CHART_BORDER_SIZE - CHART_TITLE_HEIGHT)
        .max(spec.min_cell_h)
        .max(0);

    GridDims {
        cell_w: inner_w,
        cell_h: inner_h,
        cell_w_with_padding: cell_w_with_pad,
        cell_h_with_padding: cell_h_with_pad,
    }
}

/// GridNavigator provides grid navigation functionality.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct GridNavigator {
    current_page: isize,
    total_pages: isize,
}

impl GridNavigator {
    /// Navigate changes the current page by direction (-1 for prev, +1 for next).
    /// Returns true if navigation occurred, false if already at boundary.
    pub fn navigate(&mut self, direction: isize) -> bool {
        if self.total_pages <= 1 {
            return false;
        }

        let old_page = self.current_page;
        self.current_page += direction;

        // Wrap around.
        if self.current_page < 0 {
            self.current_page = self.total_pages - 1;
        } else if self.current_page >= self.total_pages {
            self.current_page = 0;
        }

        self.current_page != old_page
    }

    /// UpdateTotalPages recalculates total pages based on item count and page size.
    pub fn update_total_pages(&mut self, item_count: isize, items_per_page: isize) {
        if items_per_page <= 0 {
            self.total_pages = 0;
            return;
        }
        self.total_pages = (item_count + items_per_page - 1) / items_per_page;

        // Ensure current page is valid.
        if self.current_page >= self.total_pages && self.total_pages > 0 {
            self.current_page = self.total_pages - 1;
        }
        if self.current_page < 0 {
            self.current_page = 0;
        }
    }

    /// CurrentPage returns the current page index.
    pub fn current_page(&self) -> isize {
        self.current_page
    }

    /// TotalPages returns the total number of pages.
    pub fn total_pages(&self) -> isize {
        self.total_pages
    }

    /// GoHome jumps to the first page. Returns true if the page changed.
    pub fn go_home(&mut self) -> bool {
        if self.total_pages <= 0 || self.current_page == 0 {
            return false;
        }
        self.current_page = 0;
        true
    }

    /// GoEnd jumps to the last page. Returns true if the page changed.
    pub fn go_end(&mut self) -> bool {
        if self.total_pages <= 0 {
            return false;
        }
        let last = self.total_pages - 1;
        if self.current_page == last {
            return false;
        }
        self.current_page = last;
        true
    }

    /// PageBounds returns the start and end indices for the current page.
    pub fn page_bounds(&self, item_count: isize, items_per_page: isize) -> (isize, isize) {
        let start_idx = self.current_page * items_per_page;
        let end_idx = (start_idx + items_per_page).min(item_count);
        (start_idx, end_idx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// TestEffectiveGridSize_ClampsToAvailableSpace tests that grid size is
    /// clamped to fit within available space.
    #[test]
    fn effective_grid_size_clamps_to_available_space() {
        let spec = GridSpec {
            rows: 3,
            cols: 4,
            min_cell_w: 20,
            min_cell_h: 10,
            header_lines: 2,
        };

        // With padding: minWWithPad = 20 + 2 = 22, minHWithPad = 10 + 2 + 1 = 13
        // Available space after header: 100 - 2 = 98
        // Max cols: 120 / 22 = 5, max rows: 98 / 13 = 7
        // Requested 3x4, both fit, so should get 3x4
        let size = effective_grid_size(120, 100, spec);
        assert_eq!(size.rows, 3);
        assert_eq!(size.cols, 4);

        // Too narrow: only 1 column fits
        let size = effective_grid_size(30, 100, spec);
        assert_eq!(size.rows, 3);
        assert_eq!(size.cols, 1);

        // Too short: only 1 row fits (after header)
        let size = effective_grid_size(120, 15, spec);
        assert_eq!(size.rows, 1);
        assert_eq!(size.cols, 4);

        // Both dimensions too small: should clamp to 1x1
        let size = effective_grid_size(25, 15, spec);
        assert_eq!(size.rows, 1);
        assert_eq!(size.cols, 1);
    }

    #[test]
    fn compute_grid_dims_calculates_correct_dimensions() {
        let spec = GridSpec {
            rows: 2,
            cols: 3,
            min_cell_w: 20,
            min_cell_h: 10,
            header_lines: 0,
        };

        let dims = compute_grid_dims(120, 60, spec);

        // 120 / 3 cols = 40 per cell with padding
        assert_eq!(dims.cell_w_with_padding, 40);
        // 60 / 2 rows = 30 per cell with padding
        assert_eq!(dims.cell_h_with_padding, 30);

        // Inner dimensions: cellWWithPad - ChartBorderSize (2)
        // Should be at least MinCellW (20)
        assert!(dims.cell_w >= 20);
        assert!(dims.cell_h >= 10);
    }

    #[test]
    fn compute_grid_dims_respects_minimums() {
        let spec = GridSpec {
            rows: 2,
            cols: 2,
            min_cell_w: 50,
            min_cell_h: 30,
            header_lines: 0,
        };

        // Very small viewport - should still respect minimums
        let dims = compute_grid_dims(30, 20, spec);

        assert!(dims.cell_w >= spec.min_cell_w);
        assert!(dims.cell_h >= spec.min_cell_h);
    }

    #[test]
    fn grid_navigator_navigate() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(30, 10); // 3 pages

        // Initial page is 0
        assert_eq!(nav.current_page(), 0);

        // Navigate forward
        let changed = nav.navigate(1);
        assert!(changed);
        assert_eq!(nav.current_page(), 1);

        // Navigate forward again
        let changed = nav.navigate(1);
        assert!(changed);
        assert_eq!(nav.current_page(), 2);

        // Navigate forward - should wrap to page 0
        let changed = nav.navigate(1);
        assert!(changed);
        assert_eq!(nav.current_page(), 0);

        // Navigate backward - should wrap to last page
        let changed = nav.navigate(-1);
        assert!(changed);
        assert_eq!(nav.current_page(), 2);

        // Navigate backward
        let changed = nav.navigate(-1);
        assert!(changed);
        assert_eq!(nav.current_page(), 1);
    }

    #[test]
    fn grid_navigator_go_home_and_go_end() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(30, 10); // 3 pages

        // GoHome is a no-op when already at page 0.
        assert!(!nav.go_home());
        assert_eq!(nav.current_page(), 0);

        // GoEnd jumps to the last page.
        assert!(nav.go_end());
        assert_eq!(nav.current_page(), 2);

        // GoEnd is a no-op when already at the last page.
        assert!(!nav.go_end());
        assert_eq!(nav.current_page(), 2);

        // GoHome returns from the last page to the first.
        assert!(nav.go_home());
        assert_eq!(nav.current_page(), 0);
    }

    #[test]
    fn grid_navigator_navigate_single_page() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(5, 10); // Only 1 page

        let changed = nav.navigate(1);
        assert!(!changed);
        assert_eq!(nav.current_page(), 0);

        let changed = nav.navigate(-1);
        assert!(!changed);
        assert_eq!(nav.current_page(), 0);
    }

    #[test]
    fn grid_navigator_update_total_pages() {
        let mut nav = GridNavigator::default();

        // Start with 3 pages
        nav.update_total_pages(30, 10);
        assert_eq!(nav.total_pages(), 3);
        assert_eq!(nav.current_page(), 0);

        // Navigate to last page
        nav.navigate(1);
        nav.navigate(1);
        assert_eq!(nav.current_page(), 2);

        // Reduce to 2 pages - current page should be clamped
        nav.update_total_pages(15, 10);
        assert_eq!(nav.total_pages(), 2);
        assert_eq!(nav.current_page(), 1); // Clamped from 2 to 1

        // Reduce to 1 page
        nav.update_total_pages(5, 10);
        assert_eq!(nav.total_pages(), 1);
        assert_eq!(nav.current_page(), 0); // Clamped to 0

        // Zero items
        nav.update_total_pages(0, 10);
        assert_eq!(nav.total_pages(), 0);
        assert_eq!(nav.current_page(), 0);
    }

    #[test]
    fn grid_navigator_get_page_bounds() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(25, 10); // 3 pages

        // Page 0: items 0-9
        let (start, end) = nav.page_bounds(25, 10);
        assert_eq!(start, 0);
        assert_eq!(end, 10);

        // Page 1: items 10-19
        nav.navigate(1);
        let (start, end) = nav.page_bounds(25, 10);
        assert_eq!(start, 10);
        assert_eq!(end, 20);

        // Page 2: items 20-24 (partial page)
        nav.navigate(1);
        let (start, end) = nav.page_bounds(25, 10);
        assert_eq!(start, 20);
        assert_eq!(end, 25);
    }

    #[test]
    fn grid_navigator_get_page_bounds_edge_cases() {
        let mut nav = GridNavigator::default();

        // Empty list
        nav.update_total_pages(0, 10);
        let (start, end) = nav.page_bounds(0, 10);
        assert_eq!(start, 0);
        assert_eq!(end, 0);

        // Single item
        nav.update_total_pages(1, 10);
        let (start, end) = nav.page_bounds(1, 10);
        assert_eq!(start, 0);
        assert_eq!(end, 1);

        // Exactly one page
        nav.update_total_pages(10, 10);
        let (start, end) = nav.page_bounds(10, 10);
        assert_eq!(start, 0);
        assert_eq!(end, 10);
    }

    #[test]
    fn grid_navigator_lifecycle() {
        let mut nav = GridNavigator::default();

        // Start with no data
        assert_eq!(nav.total_pages(), 0);
        assert_eq!(nav.current_page(), 0);

        // Add initial data
        nav.update_total_pages(50, 10); // 5 pages
        assert_eq!(nav.total_pages(), 5);

        // Navigate through pages
        for i in 1..5 {
            nav.navigate(1);
            assert_eq!(nav.current_page(), i);
        }

        // Wrap around
        nav.navigate(1);
        assert_eq!(nav.current_page(), 0);

        // Add more data while on page 0
        nav.update_total_pages(100, 10); // 10 pages
        assert_eq!(nav.total_pages(), 10);
        assert_eq!(nav.current_page(), 0); // Should stay on valid page

        // Navigate to last page
        for _ in 0..9 {
            nav.navigate(1);
        }
        assert_eq!(nav.current_page(), 9);

        // Reduce data significantly
        nav.update_total_pages(15, 10); // 2 pages
        assert_eq!(nav.total_pages(), 2);
        assert_eq!(nav.current_page(), 1); // Clamped from 9 to 1
    }
}
