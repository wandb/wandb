package leet

import (
	"fmt"
	"sort"
	"sync"

	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

// MetricsGrid manages the main run metrics charts (not system metrics).
type MetricsGrid struct {
	// Lock guards chart slices/maps and filter state.
	mu sync.RWMutex

	// Configuration and logging.
	config *ConfigManager
	logger *observability.CoreLogger

	// Layout and navigation.
	width, height int           // content area
	nav           GridNavigator // pagination state for the grid

	// Charts state.
	all         []*EpochLineChart          // all charts, sorted by Title()
	byTitle     map[string]*EpochLineChart // Title() -> chart
	currentPage [][]*EpochLineChart        // charts visible on the current page grid
	filtered    []*EpochLineChart          // subset of all matching activeQuery (may be nil)

	// Chart focus management.
	focus *Focus

	// Filter state.
	filter FilterState
}

func NewMetricsGrid(
	config *ConfigManager,
	focus *Focus,
	logger *observability.CoreLogger,
) *MetricsGrid {
	gridRows, gridCols := config.MetricsGrid()

	mg := &MetricsGrid{
		config:      config,
		all:         make([]*EpochLineChart, 0),
		byTitle:     make(map[string]*EpochLineChart),
		filtered:    make([]*EpochLineChart, 0),
		currentPage: make([][]*EpochLineChart, gridRows),
		focus:       focus,
		logger:      logger,
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
//
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
	// Add points, creating charts with current dims if new.
	for name, val := range metrics {
		chart, ok := mg.byTitle[name]
		if !ok {
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
		mg.sortChartsNoLock()
		// Always reapply so filtered mirrors all when filter is empty.
		mg.applyFilterNoLock(mg.filter.applied)
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

// sortChartsNoLock sorts charts alphabetically and reassigns colors.
//
// Caller must hold the lock.
func (mg *MetricsGrid) sortChartsNoLock() {
	sort.Slice(mg.all, func(i, j int) bool {
		return mg.all[i].Title() < mg.all[j].Title()
	})

	graphColors := GraphColors()

	mg.byTitle = make(map[string]*EpochLineChart)
	for i, chart := range mg.all {
		mg.byTitle[chart.Title()] = chart
		chart.graphStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color(graphColors[i%len(graphColors)]))
	}

	if mg.filtered == nil || (len(mg.filtered) == 0 && mg.filter.applied == "") {
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

	// Use filtered charts if filter is active.
	chartsToShow := mg.filtered
	if len(chartsToShow) == 0 && mg.filter.applied == "" {
		chartsToShow = mg.all
	}

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
	defer func() {
		if r := recover(); r != nil && mg.logger != nil {
			mg.logger.Error(fmt.Sprintf("panic in MetricsGrid.UpdateDimensions: %v", r))
		}
	}()

	mg.width, mg.height = contentWidth, contentHeight

	dims := mg.CalculateChartDimensions(contentWidth, contentHeight)

	// Resize all charts
	mg.mu.Lock()
	for _, chart := range mg.all {
		if chart != nil {
			chart.Resize(dims.CellW, dims.CellH)
			chart.dirty = true
		}
	}
	mg.mu.Unlock()

	size := mg.effectiveGridSize()
	mg.mu.RLock()
	chartCount := len(mg.filtered)
	if chartCount == 0 && mg.filter.applied == "" {
		chartCount = len(mg.all)
	}
	mg.mu.RUnlock()
	mg.nav.UpdateTotalPages(chartCount, ItemsPerPage(size))

	mg.loadCurrentPage()
	mg.drawVisible()
}

// RenderGrid creates the chart grid view.
func (mg *MetricsGrid) RenderGrid(dims GridDims) string {
	header := headerStyle.Render("Metrics")

	// Add navigation info
	navInfo := ""
	mg.mu.RLock()
	chartCount := len(mg.filtered)
	if chartCount == 0 && mg.filter.applied == "" {
		chartCount = len(mg.all)
	}
	totalCount := len(mg.all)
	mg.mu.RUnlock()

	size := mg.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)
	totalPages := mg.nav.TotalPages()

	if totalPages > 0 && chartCount > 0 {
		startIdx, endIdx := mg.nav.PageBounds(chartCount, itemsPerPage)
		startIdx++ // Display as 1-indexed

		if mg.filter.applied != "" {
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

	// Render grid
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

	return lipgloss.JoinVertical(lipgloss.Left, headerContainer, gridContainer)
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
func (mg *MetricsGrid) drawVisible() {
	size := mg.effectiveGridSize()

	for row := 0; row < size.Rows; row++ {
		for col := 0; col < size.Cols; col++ {
			if row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
				mg.currentPage[row][col] != nil {
				chart := mg.currentPage[row][col]
				chart.dirty = true
				chart.Draw()
				chart.dirty = false
			}
		}
	}
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
		for col := 0; col < size.Cols; col++ {
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

// handleClick handles clicks in the main chart grid.
func (mg *MetricsGrid) HandleClick(row, col int) {
	// Check if clicking on already focused chart (to unfocus)
	if mg.focus.Type == FocusMainChart &&
		row == mg.focus.Row && col == mg.focus.Col {
		mg.clearFocus()
		return
	}

	size := mg.effectiveGridSize()

	mg.mu.RLock()
	defer mg.mu.RUnlock()

	if row >= 0 && row < size.Rows &&
		col >= 0 && col < size.Cols &&
		row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
		mg.currentPage[row][col] != nil {
		mg.clearFocus()
		mg.setFocus(row, col)
	}
}

// setFocus sets focus to a main grid chart.
func (mg *MetricsGrid) setFocus(row, col int) {
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

// clearFocus clears focus only from main charts.
func (mg *MetricsGrid) clearFocus() {
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

	mg.mu.RLock()
	defer mg.mu.RUnlock()

	if row >= 0 && row < size.Rows &&
		col >= 0 && col < size.Cols &&
		row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
		mg.currentPage[row][col] != nil {
		chart := mg.currentPage[row][col]

		chartStartX := col * dims.CellWWithPadding
		graphStartX := chartStartX + 1
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}
		relativeMouseX := adjustedX - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			// Focus the chart when zooming (if not already focused).
			if mg.focus.Type != FocusMainChart ||
				mg.focus.Row != row || mg.focus.Col != col {
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
	}
}
