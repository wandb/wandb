package leet

// GridSpec describes the desired (configured) grid and the minimums required
// for one chart cell to render reasonably.
type GridSpec struct {
	Rows        int // configured rows (before clamping)
	Cols        int // configured cols (before clamping)
	MinCellW    int // inner chart width (no borders)
	MinCellH    int // inner chart height (no borders + title line)
	HeaderLines int // lines reserved above the grid (section header etc.)
}

// GridSize is the final rows/cols after clamping to available space.
type GridSize struct {
	Rows int
	Cols int
}

// GridDims are the computed sizes for one cell (uniform across the grid).
// *WithPadding includes the border/title overhead the caller places around charts.
type GridDims struct {
	CellW            int // inner chart width (usable by the chart)
	CellH            int // inner chart height (usable by the chart)
	CellWWithPadding int // full cell slot width (including border/title)
	CellHWithPadding int // full cell slot height (including border/title)
}

// Focus tracks the currently focused chart in the grid.
type Focus struct {
	Type     FocusType
	Row, Col int
	Title    string
}

func NewFocus() *Focus {
	return &Focus{Type: FocusNone, Row: -1, Col: -1}
}

// Reset resets the focus state to factory settings.
func (f *Focus) Reset() {
	f.Type = FocusNone
	f.Row, f.Col = -1, -1
}

// FocusType indicates what type of UI element is focused.
type FocusType int

const (
	FocusNone FocusType = iota
	FocusMainChart
	FocusSystemChart
)

// ItemsPerPage returns Rows*Cols with basic safety.
func ItemsPerPage(size GridSize) int {
	if size.Rows <= 0 || size.Cols <= 0 {
		return 0
	}
	return size.Rows * size.Cols
}

// EffectiveGridSize clamps Rows/Cols so that at least the configured minimum
// chart sizes fit in the current viewport.
func EffectiveGridSize(availW, availH int, spec GridSpec) GridSize {
	// Subtract header space from available height (never below 0).
	if availH > spec.HeaderLines {
		availH -= spec.HeaderLines
	} else {
		availH = 0
	}

	// Minimum padded cell sizes: chart + borders + title.
	minWWithPad := spec.MinCellW + ChartBorderSize
	minHWithPad := spec.MinCellH + ChartBorderSize + ChartTitleHeight

	// Compute the maximum grid that fits.
	maxCols := 1
	if minWWithPad > 0 {
		if c := availW / minWWithPad; c > 1 {
			maxCols = c
		}
	}
	maxRows := 1
	if minHWithPad > 0 {
		if r := availH / minHWithPad; r > 1 {
			maxRows = r
		}
	}

	// Clamp to what fits, never below 1.
	rows := min(max(spec.Rows, 1), maxRows)
	cols := min(max(spec.Cols, 1), maxCols)

	return GridSize{Rows: rows, Cols: cols}
}

// ComputeGridDims returns uniform per-cell sizes for the given grid size.
func ComputeGridDims(availW, availH int, spec GridSpec) GridDims {
	size := EffectiveGridSize(availW, availH, spec)

	// Subtract header lines (never below 0).
	if availH > spec.HeaderLines {
		availH -= spec.HeaderLines
	} else {
		availH = 0
	}

	// Padded cell sizes.
	cellWWithPad := 0
	if size.Cols > 0 {
		cellWWithPad = availW / size.Cols
	}
	cellHWithPad := 0
	if size.Rows > 0 {
		cellHWithPad = availH / size.Rows
	}

	// Inner chart sizes (respect minimums).
	innerW := max(max(cellWWithPad-ChartBorderSize, spec.MinCellW), 0)
	innerH := max(max(cellHWithPad-ChartBorderSize-ChartTitleHeight, spec.MinCellH), 0)

	return GridDims{
		CellW:            innerW,
		CellH:            innerH,
		CellWWithPadding: cellWWithPad,
		CellHWithPadding: cellHWithPad,
	}
}

// GridNavigator provides grid navigation functionality.
type GridNavigator struct {
	currentPage int
	totalPages  int
}

// Navigate changes the current page by direction (-1 for prev, +1 for next).
// Returns true if navigation occurred, false if already at boundary.
func (gn *GridNavigator) Navigate(direction int) bool {
	if gn.totalPages <= 1 {
		return false
	}

	oldPage := gn.currentPage
	gn.currentPage += direction

	// Wrap around.
	if gn.currentPage < 0 {
		gn.currentPage = gn.totalPages - 1
	} else if gn.currentPage >= gn.totalPages {
		gn.currentPage = 0
	}

	return gn.currentPage != oldPage
}

// UpdateTotalPages recalculates total pages based on item count and page size.
func (gn *GridNavigator) UpdateTotalPages(itemCount, itemsPerPage int) {
	if itemsPerPage <= 0 {
		gn.totalPages = 0
		return
	}
	gn.totalPages = (itemCount + itemsPerPage - 1) / itemsPerPage

	// Ensure current page is valid.
	if gn.currentPage >= gn.totalPages && gn.totalPages > 0 {
		gn.currentPage = gn.totalPages - 1
	}
	if gn.currentPage < 0 {
		gn.currentPage = 0
	}
}

// CurrentPage returns the current page index.
func (gn *GridNavigator) CurrentPage() int {
	return gn.currentPage
}

// TotalPages returns the total number of pages.
func (gn *GridNavigator) TotalPages() int {
	return gn.totalPages
}

// PageBounds returns the start and end indices for the current page.
func (gn *GridNavigator) PageBounds(itemCount, itemsPerPage int) (startIdx, endIdx int) {
	startIdx = gn.currentPage * itemsPerPage
	endIdx = min(startIdx+itemsPerPage, itemCount)
	return startIdx, endIdx
}
