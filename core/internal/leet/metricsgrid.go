package leet

import (
	"fmt"
	"sort"
	"sync"

	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

const metricsHeader = "Metrics"

// MetricsGrid manages the main run metrics charts.
//
// It owns charts (create, index, update), maintains filter and pagination state,
// and computes/renders the current page/grid layout.
type MetricsGrid struct {
	// mu guards chart slices/maps and filter state.
	mu sync.RWMutex

	// Configuration and logging.
	config *ConfigManager
	logger *observability.CoreLogger

	// Viewport dimensions.
	width, height int

	// Pagination state.
	nav GridNavigator

	// Charts state.
	all      []*EpochLineChart          // all charts, sorted by Title()
	byTitle  map[string]*EpochLineChart // Title() -> chart
	filtered []*EpochLineChart          // subset matching filter (mirrors all when filter empty)

	// Charts visible on the current page grid.
	currentPage [][]*EpochLineChart

	// Chart focus management.
	focus *Focus // focus.Row/Col only meaningful relative to currentPage

	// Filter state.
	filter FilterState

	// Stable color assignment.
	colorOfTitle map[string]string
	nextColorIdx int
}

func NewMetricsGrid(
	config *ConfigManager,
	focus *Focus,
	logger *observability.CoreLogger,
) *MetricsGrid {
	gridRows, gridCols := config.MetricsGrid()

	mg := &MetricsGrid{
		config:       config,
		all:          make([]*EpochLineChart, 0),
		byTitle:      make(map[string]*EpochLineChart),
		filtered:     make([]*EpochLineChart, 0),
		currentPage:  make([][]*EpochLineChart, gridRows),
		focus:        focus,
		logger:       logger,
		colorOfTitle: make(map[string]string),
	}

	for r := range gridRows {
		mg.currentPage[r] = make([]*EpochLineChart, gridCols)
	}
	return mg
}

// ChartCount returns the total number of metrics charts.
func (mg *MetricsGrid) ChartCount() int {
	mg.mu.RLock()
	defer mg.mu.RUnlock()
	return len(mg.all)
}

// CalculateChartDimensions computes chart dimensions.
func (mg *MetricsGrid) CalculateChartDimensions(windowWidth, windowHeight int) GridDims {
	gridRows, gridCols := mg.config.MetricsGrid()
	return ComputeGridDims(windowWidth, windowHeight, GridSpec{
		Rows:        gridRows,
		Cols:        gridCols,
		MinCellW:    MinChartWidth,
		MinCellH:    MinChartHeight,
		HeaderLines: ChartHeaderHeight,
	})
}

// ProcessHistory ingests a batch of history samples (single step across metrics),
// creating charts as needed, resorting, reapplying filters, and reloading the page.
// It preserves focus on the previously focused chart when possible.
// Returns true if there was anything to draw.
func (mg *MetricsGrid) ProcessHistory(step int, metrics map[string]float64) bool {
	if len(metrics) == 0 {
		return false
	}

	// Remember focused chart title (only if a main chart is actually focused & valid).
	prevTitle := mg.saveFocusTitle()

	needsSort := false
	dims := mg.CalculateChartDimensions(mg.width, mg.height)

	mg.mu.Lock()
	for name, val := range metrics {
		chart, exists := mg.byTitle[name]
		if !exists {
			chart = NewEpochLineChart(dims.CellW, dims.CellH, name)
			mg.all = append(mg.all, chart)
			mg.byTitle[name] = chart
			needsSort = true

			if mg.logger != nil && len(mg.all)%1000 == 0 {
				mg.logger.Debug(fmt.Sprintf("metricsgrid: created %d charts", len(mg.all)))
			}
		}
		chart.AddPoint(float64(step), val)
	}

	// Keep ordering, colors, maps and filtered set in sync.
	if needsSort {
		mg.sortChartsNoLock() // re-sorts + assigns stable colors
		// mg.applyFilterNoLock(mg.filter.applied) // keep filtered mirror / subset
	} else {
		// No new charts; keep pagination but refresh visible page contents.
		mg.loadCurrentPageNoLock()
	}
	mg.mu.Unlock()

	// Restore focus by title (if previously valid and still visible).
	mg.restoreFocus(prevTitle)
	return true
}

// effectiveGridSize returns the grid size that can fit in the current viewport.
func (mg *MetricsGrid) effectiveGridSize() GridSize {
	gridRows, gridCols := mg.config.MetricsGrid()
	return EffectiveGridSize(mg.width, mg.height, GridSpec{
		Rows:        gridRows,
		Cols:        gridCols,
		MinCellW:    MinChartWidth,
		MinCellH:    MinChartHeight,
		HeaderLines: ChartHeaderHeight,
	})
}

// chartsToShowNoLock returns the slice backing the current view.
//
// Caller must hold mg.mu (RLock is fine).
func (mg *MetricsGrid) chartsToShowNoLock() []*EpochLineChart {
	if mg.filter.applied == "" {
		return mg.all
	}
	return mg.filtered
}

// effectiveChartCountNoLock is the count used for nav/pagination.
//
// Caller must hold mg.mu (RLock is fine).
func (mg *MetricsGrid) effectiveChartCountNoLock() int {
	if mg.filter.applied == "" {
		return len(mg.all)
	}
	return len(mg.filtered)
}

// colorForNoLock returns a stable color for a given metric title.
func (mg *MetricsGrid) colorForNoLock(title string) string {
	if c, ok := mg.colorOfTitle[title]; ok {
		return c
	}
	palette := GraphColors()
	c := palette[mg.nextColorIdx%len(palette)]
	mg.colorOfTitle[title] = c
	mg.nextColorIdx++
	return c
}

// sortChartsNoLock sorts charts alphabetically, rebuilds indices, and (re)assigns colors.
//
// Caller must hold mg.mu.
func (mg *MetricsGrid) sortChartsNoLock() {
	sort.Slice(mg.all, func(i, j int) bool {
		return mg.all[i].Title() < mg.all[j].Title()
	})

	mg.byTitle = make(map[string]*EpochLineChart, len(mg.all))
	for _, chart := range mg.all {
		mg.byTitle[chart.Title()] = chart

		// Stable color per title (no reshuffling when new charts arrive).
		col := mg.colorForNoLock(chart.Title())
		chart.graphStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color(col))
	}

	// Ensure filtered mirrors all when filter is empty.
	if mg.filter.applied == "" {
		mg.filtered = append(make([]*EpochLineChart, 0, len(mg.all)), mg.all...)
	}
}

// loadCurrentPage loads the charts for the current page into the grid.
func (mg *MetricsGrid) loadCurrentPage() {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	mg.loadCurrentPageNoLock()
}

// loadCurrentPageNoLock loads the current page without acquiring the mutex.
func (mg *MetricsGrid) loadCurrentPageNoLock() {
	size := mg.effectiveGridSize()

	// Rebuild grid structure
	mg.currentPage = make([][]*EpochLineChart, size.Rows)
	for row := 0; row < size.Rows; row++ {
		mg.currentPage[row] = make([]*EpochLineChart, size.Cols)
	}

	chartsToShow := mg.chartsToShowNoLock()

	startIdx, endIdx := mg.nav.PageBounds(len(chartsToShow), ItemsPerPage(size))

	idx := startIdx
	for row := 0; row < size.Rows && idx < endIdx; row++ {
		for col := 0; col < size.Cols && idx < endIdx; col++ {
			mg.currentPage[row][col] = chartsToShow[idx]
			idx++
		}
	}
}

// UpdateDimensions updates chart sizes based on content viewport.
func (mg *MetricsGrid) UpdateDimensions(contentWidth, contentHeight int) {
	mg.width, mg.height = contentWidth, contentHeight

	// Keep pagination in sync with what fits now.
	mg.mu.Lock()
	size := mg.effectiveGridSize()
	chartCount := mg.effectiveChartCountNoLock()
	mg.nav.UpdateTotalPages(chartCount, ItemsPerPage(size))
	mg.loadCurrentPageNoLock()
	mg.mu.Unlock()

	// Only resize/draw charts that are currently visible.
	mg.drawVisible()
}

// View creates the chart grid view.
func (mg *MetricsGrid) View(dims GridDims) string {
	size := mg.effectiveGridSize()

	header := mg.renderHeader(size)
	grid := mg.renderGrid(dims, size)

	return lipgloss.JoinVertical(lipgloss.Left, header, grid)
}

func (mg *MetricsGrid) renderHeader(size GridSize) string {
	mg.mu.RLock()
	defer mg.mu.RUnlock()

	header := headerStyle.Render(metricsHeader)

	navInfo := ""

	chartCount := mg.effectiveChartCountNoLock()
	totalCount := len(mg.all)
	filterApplied := mg.filter.applied != ""

	itemsPerPage := ItemsPerPage(size)
	totalPages := mg.nav.TotalPages()

	if totalPages > 0 && chartCount > 0 {
		startIdx, endIdx := mg.nav.PageBounds(chartCount, itemsPerPage)
		startIdx++ // Display as 1-indexed

		if filterApplied {
			navInfo = navInfoStyle.Render(
				fmt.Sprintf(" [%d-%d of %d filtered from %d total]",
					startIdx, endIdx, chartCount, totalCount))
		} else {
			navInfo = navInfoStyle.Render(
				fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
		}
	}

	headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)
	headerContainer := headerContainerStyle.Render(headerLine)

	return headerContainer
}

func (mg *MetricsGrid) renderGrid(dims GridDims, size GridSize) string {
	var rows []string
	for row := range size.Rows {
		var cols []string
		for col := range size.Cols {
			cellContent := mg.renderGridCell(row, col, dims)
			cols = append(cols, cellContent)
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}
	gridContent := lipgloss.JoinVertical(lipgloss.Left, rows...)
	gridContainer := gridContainerStyle.Render(gridContent)

	// Add vertical filler to use all available height.
	availableHeight := max(mg.height-ChartHeaderHeight, 0)
	usedHeight := size.Rows * dims.CellHWithPadding
	extra := availableHeight - usedHeight
	if extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		gridContainer = lipgloss.JoinVertical(lipgloss.Left, gridContainer, filler)
	}

	return gridContainer
}

// renderGridCell renders a single grid cell.
func (mg *MetricsGrid) renderGridCell(row, col int, dims GridDims) string {
	mg.mu.RLock()
	defer mg.mu.RUnlock()

	if row < len(mg.currentPage) && col < len(mg.currentPage[row]) && mg.currentPage[row][col] != nil {
		chart := mg.currentPage[row][col]
		chartView := chart.View()

		boxStyle := borderStyle
		if mg.focus.Type == FocusMainChart &&
			row == mg.focus.Row && col == mg.focus.Col {
			boxStyle = focusedBorderStyle
		}

		availableTitleWidth := max(dims.CellWWithPadding-4, 10)
		displayTitle := TruncateTitle(chart.Title(), availableTitleWidth)

		boxContent := lipgloss.JoinVertical(
			lipgloss.Left,
			titleStyle.Render(displayTitle),
			chartView,
		)

		box := boxStyle.Render(boxContent)

		return lipgloss.Place(
			dims.CellWWithPadding,
			dims.CellHWithPadding,
			lipgloss.Left,
			lipgloss.Top,
			box,
		)
	}

	return lipgloss.NewStyle().
		Width(dims.CellWWithPadding).
		Height(dims.CellHWithPadding).
		Render("")
}

// Navigate changes the current page.
func (mg *MetricsGrid) Navigate(direction int) {
	if !mg.nav.Navigate(direction) {
		return
	}

	mg.clearFocus()
	mg.loadCurrentPage()
	mg.drawVisible()
}

// drawVisible draws charts that are currently visible.
//
// Snapshot page first; do not hold mg.mu while drawing.
func (mg *MetricsGrid) drawVisible() {
	page := mg.snapshotCurrentPage()
	dims := mg.CalculateChartDimensions(mg.width, mg.height)

	for row := range len(page) {
		for col := range len(page[row]) {
			if ch := page[row][col]; ch != nil {
				// Ensure visible charts always match current cell dims.
				if ch.Width() != dims.CellW || ch.Height() != dims.CellH {
					ch.Resize(dims.CellW, dims.CellH)
				}
				ch.dirty = true
				ch.Draw()
				ch.dirty = false
			}
		}
	}
}

// snapshotCurrentPage copies the 2D slice headers.
func (mg *MetricsGrid) snapshotCurrentPage() [][]*EpochLineChart {
	mg.mu.RLock()
	defer mg.mu.RUnlock()

	cp := make([][]*EpochLineChart, len(mg.currentPage))
	for i := range mg.currentPage {
		if mg.currentPage[i] == nil {
			continue
		}
		cp[i] = append([]*EpochLineChart(nil), mg.currentPage[i]...)
	}
	return cp
}

// saveFocusTitle returns the title of the currently focused main-grid chart,
// or an empty string if nothing valid is focused.
func (mg *MetricsGrid) saveFocusTitle() string {
	if mg.focus.Type != FocusMainChart {
		return ""
	}
	row, col := mg.focus.Row, mg.focus.Col
	mg.mu.RLock()
	defer mg.mu.RUnlock()
	if row >= 0 && col >= 0 &&
		row < len(mg.currentPage) &&
		col < len(mg.currentPage[row]) &&
		mg.currentPage[row][col] != nil {
		return mg.currentPage[row][col].Title()
	}
	return ""
}

// restoreFocus tries to restore focus to the chart with the given title.
func (mg *MetricsGrid) restoreFocus(previousTitle string) {
	if previousTitle == "" || mg.focus.Type != FocusMainChart {
		return
	}
	size := mg.effectiveGridSize()

	mg.mu.RLock()
	foundRow, foundCol := -1, -1
	for row := 0; row < size.Rows && foundRow == -1; row++ {
		for col := range size.Cols {
			if row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
				mg.currentPage[row][col] != nil &&
				mg.currentPage[row][col].Title() == previousTitle {
				foundRow, foundCol = row, col
				break
			}
		}
	}
	mg.mu.RUnlock()

	if foundRow != -1 {
		mg.setFocus(foundRow, foundCol)
	}
}

// HandleClick handles clicks in the main chart grid.
func (mg *MetricsGrid) HandleClick(row, col int) {
	// Unfocus if clicking the already-focused chart.
	if mg.focus.Type == FocusMainChart &&
		row == mg.focus.Row && col == mg.focus.Col {
		mg.clearFocus()
		return
	}

	size := mg.effectiveGridSize()

	// Check validity under read lock.
	mg.mu.RLock()
	valid := row >= 0 && row < size.Rows &&
		col >= 0 && col < size.Cols &&
		row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
		mg.currentPage[row][col] != nil
	mg.mu.RUnlock()

	if !valid {
		return
	}

	mg.clearFocus()
	mg.setFocus(row, col)
}

// setFocus sets focus to a main grid chart.
func (mg *MetricsGrid) setFocus(row, col int) {
	mg.mu.Lock()
	defer mg.mu.Unlock()

	if row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
		mg.currentPage[row][col] != nil {
		chart := mg.currentPage[row][col]
		mg.focus.Type = FocusMainChart
		mg.focus.Row = row
		mg.focus.Col = col
		mg.focus.Title = chart.Title()
		chart.SetFocused(true)
	}
}

// clearFocus clears focus only from main charts (locks internally).
func (mg *MetricsGrid) clearFocus() {
	mg.mu.Lock()
	defer mg.mu.Unlock()

	if mg.focus.Type == FocusMainChart {
		if mg.focus.Row >= 0 && mg.focus.Col >= 0 &&
			mg.focus.Row < len(mg.currentPage) &&
			mg.focus.Col < len(mg.currentPage[mg.focus.Row]) &&
			mg.currentPage[mg.focus.Row][mg.focus.Col] != nil {
			mg.currentPage[mg.focus.Row][mg.focus.Col].SetFocused(false)
		}
		mg.focus.Type = FocusNone
		mg.focus.Row = -1
		mg.focus.Col = -1
		mg.focus.Title = ""
	}
}

// HandleWheel performs zoom handling on a main-grid chart at (row, col).
func (mg *MetricsGrid) HandleWheel(
	adjustedX, row, col int,
	dims GridDims,
	wheelUp bool,
) {
	size := mg.effectiveGridSize()

	// Inspect under read lock.
	mg.mu.RLock()
	if row < 0 || row >= size.Rows || col < 0 || col >= size.Cols ||
		row >= len(mg.currentPage) || col >= len(mg.currentPage[row]) ||
		mg.currentPage[row][col] == nil {
		mg.mu.RUnlock()
		return
	}
	chart := mg.currentPage[row][col]

	chartStartX := col * dims.CellWWithPadding
	graphStartX := chartStartX + 1
	if chart.YStep() > 0 {
		graphStartX += chart.Origin().X + 1
	}
	relativeMouseX := adjustedX - graphStartX
	needFocus := mg.focus.Type != FocusMainChart ||
		mg.focus.Row != row || mg.focus.Col != col
	mg.mu.RUnlock()

	if relativeMouseX < 0 || relativeMouseX >= chart.GraphWidth() {
		return
	}

	// Focus the chart when zooming (if not already focused).
	if needFocus {
		mg.clearFocus()
		mg.setFocus(row, col)
	}

	direction := "out"
	if wheelUp {
		direction = "in"
	}
	chart.HandleZoom(direction, relativeMouseX)
	chart.DrawIfNeeded()
}
