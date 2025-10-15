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
	chartMu sync.RWMutex

	allCharts      []*EpochLineChart
	chartsByName   map[string]*EpochLineChart
	currentPage    [][]*EpochLineChart
	filteredCharts []*EpochLineChart

	config *ConfigManager

	width, height int

	navigator GridNavigator

	focusState *FocusState

	filterMode   bool
	filterInput  string
	activeFilter string

	logger *observability.CoreLogger
}

func NewMetricsGrid(
	config *ConfigManager,
	focusState *FocusState,
	logger *observability.CoreLogger,
) *MetricsGrid {
	gridRows, gridCols := config.MetricsGrid()

	mg := &MetricsGrid{
		config:         config,
		allCharts:      make([]*EpochLineChart, 0),
		chartsByName:   make(map[string]*EpochLineChart),
		filteredCharts: make([]*EpochLineChart, 0),
		currentPage:    make([][]*EpochLineChart, gridRows),
		focusState:     focusState,
		logger:         logger,
	}
	for r := range gridRows {
		mg.currentPage[r] = make([]*EpochLineChart, gridCols)
	}
	return mg
}

// ChartDimensions represents chart dimensions for the given window size.
type ChartDimensions struct {
	ChartWidth, ChartHeight                       int
	ChartWidthWithPadding, ChartHeightWithPadding int
}

// CalculateChartDimensions computes chart dimensions.
func (mg *MetricsGrid) CalculateChartDimensions(windowWidth, windowHeight int) ChartDimensions {
	gridRows, gridCols := mg.config.MetricsGrid()
	spec := GridSpec{
		Rows:        gridRows,
		Cols:        gridCols,
		MinCellW:    MinChartWidth,
		MinCellH:    MinChartHeight,
		HeaderLines: ChartHeaderHeight,
	}

	size := EffectiveGridSize(windowWidth, windowHeight, spec)
	d := ComputeGridDims(windowWidth, windowHeight, spec, size)

	return ChartDimensions{
		ChartWidth:             d.CellW,
		ChartHeight:            d.CellH,
		ChartWidthWithPadding:  d.CellWWithPadding,
		ChartHeightWithPadding: d.CellHWithPadding,
	}
}

// effectiveGridSize returns the grid size that can fit in the current viewport.
func (mg *MetricsGrid) effectiveGridSize() GridSize {
	gridRows, gridCols := mg.config.MetricsGrid()
	spec := GridSpec{
		Rows:        gridRows,
		Cols:        gridCols,
		MinCellW:    MinChartWidth,
		MinCellH:    MinChartHeight,
		HeaderLines: ChartHeaderHeight,
	}
	return EffectiveGridSize(mg.width, mg.height, spec)
}

// sortChartsNoLock sorts charts alphabetically and reassigns colors.
// Caller must hold the lock.
func (mg *MetricsGrid) sortChartsNoLock() {
	sort.Slice(mg.allCharts, func(i, j int) bool {
		return mg.allCharts[i].Title() < mg.allCharts[j].Title()
	})

	graphColors := GetGraphColors()

	mg.chartsByName = make(map[string]*EpochLineChart)
	for i, chart := range mg.allCharts {
		mg.chartsByName[chart.Title()] = chart
		chart.graphStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color(graphColors[i%len(graphColors)]))
	}

	if mg.filteredCharts == nil || (len(mg.filteredCharts) == 0 && mg.activeFilter == "") {
		mg.filteredCharts = append(make([]*EpochLineChart, 0, len(mg.allCharts)), mg.allCharts...)
	}
}

// loadCurrentPage loads the charts for the current page into the grid.
func (mg *MetricsGrid) loadCurrentPage() {
	mg.chartMu.Lock()
	defer mg.chartMu.Unlock()
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
	chartsToShow := mg.filteredCharts
	if len(chartsToShow) == 0 && mg.activeFilter == "" {
		chartsToShow = mg.allCharts
	}

	startIdx, endIdx := mg.navigator.GetPageBounds(len(chartsToShow), ItemsPerPage(size))

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
	mg.chartMu.Lock()
	for _, chart := range mg.allCharts {
		if chart != nil {
			chart.Resize(dims.ChartWidth, dims.ChartHeight)
			chart.dirty = true
		}
	}
	mg.chartMu.Unlock()

	size := mg.effectiveGridSize()
	mg.chartMu.RLock()
	chartCount := len(mg.filteredCharts)
	if chartCount == 0 && mg.activeFilter == "" {
		chartCount = len(mg.allCharts)
	}
	mg.chartMu.RUnlock()
	mg.navigator.UpdateTotalPages(chartCount, ItemsPerPage(size))

	mg.loadCurrentPage()
	mg.drawVisible()
}

// renderGrid creates the chart grid view.
func (mg *MetricsGrid) renderGrid(dims ChartDimensions) string {
	header := headerStyle.Render("Metrics")

	// Add navigation info
	navInfo := ""
	mg.chartMu.RLock()
	chartCount := len(mg.filteredCharts)
	if chartCount == 0 && mg.activeFilter == "" {
		chartCount = len(mg.allCharts)
	}
	totalCount := len(mg.allCharts)
	mg.chartMu.RUnlock()

	size := mg.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)
	totalPages := mg.navigator.TotalPages()

	if totalPages > 0 && chartCount > 0 {
		startIdx, endIdx := mg.navigator.GetPageBounds(chartCount, itemsPerPage)
		startIdx++ // Display as 1-indexed

		if mg.activeFilter != "" {
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
	for row := 0; row < size.Rows; row++ {
		var cols []string
		for col := 0; col < size.Cols; col++ {
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
	usedHeight := size.Rows * dims.ChartHeightWithPadding
	extra := availableHeight - usedHeight
	if extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		gridContainer = lipgloss.JoinVertical(lipgloss.Left, gridContainer, filler)
	}

	return lipgloss.JoinVertical(lipgloss.Left, headerContainer, gridContainer)
}

// renderGridCell renders a single grid cell.
func (mg *MetricsGrid) renderGridCell(row, col int, dims ChartDimensions) string {
	mg.chartMu.RLock()
	defer mg.chartMu.RUnlock()

	if row < len(mg.currentPage) && col < len(mg.currentPage[row]) && mg.currentPage[row][col] != nil {
		chart := mg.currentPage[row][col]
		chartView := chart.View()

		boxStyle := borderStyle
		if mg.focusState.Type == FocusMainChart &&
			row == mg.focusState.Row && col == mg.focusState.Col {
			boxStyle = focusedBorderStyle
		}

		availableTitleWidth := max(dims.ChartWidthWithPadding-4, 10)
		displayTitle := TruncateTitle(chart.Title(), availableTitleWidth)

		boxContent := lipgloss.JoinVertical(
			lipgloss.Left,
			titleStyle.Render(displayTitle),
			chartView,
		)

		box := boxStyle.Render(boxContent)

		return lipgloss.Place(
			dims.ChartWidthWithPadding,
			dims.ChartHeightWithPadding,
			lipgloss.Left,
			lipgloss.Top,
			box,
		)
	}

	return lipgloss.NewStyle().
		Width(dims.ChartWidthWithPadding).
		Height(dims.ChartHeightWithPadding).
		Render("")
}

// Navigate changes the current page.
func (mg *MetricsGrid) Navigate(direction int) {
	if !mg.navigator.Navigate(direction) {
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

// handleClick handles clicks in the main chart grid.
func (mg *MetricsGrid) handleClick(row, col int) {
	// Check if clicking on already focused chart (to unfocus)
	if mg.focusState.Type == FocusMainChart &&
		row == mg.focusState.Row && col == mg.focusState.Col {
		mg.clearFocus()
		return
	}

	size := mg.effectiveGridSize()

	mg.chartMu.RLock()
	defer mg.chartMu.RUnlock()

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
		mg.focusState.Type = FocusMainChart
		mg.focusState.Row = row
		mg.focusState.Col = col
		mg.focusState.Title = chart.Title()
		chart.SetFocused(true)
	}
}

// clearFocus clears focus only from main charts.
func (mg *MetricsGrid) clearFocus() {
	if mg.focusState.Type == FocusMainChart {
		if mg.focusState.Row >= 0 && mg.focusState.Col >= 0 &&
			mg.focusState.Row < len(mg.currentPage) &&
			mg.focusState.Col < len(mg.currentPage[mg.focusState.Row]) &&
			mg.currentPage[mg.focusState.Row][mg.focusState.Col] != nil {
			mg.currentPage[mg.focusState.Row][mg.focusState.Col].SetFocused(false)
		}
		mg.focusState.Type = FocusNone
		mg.focusState.Row = -1
		mg.focusState.Col = -1
		mg.focusState.Title = ""
	}
}

// HandleWheel performs zoom handling on a main-grid chart at (row, col).
func (mg *MetricsGrid) HandleWheel(
	adjustedX, row, col int,
	dims ChartDimensions,
	wheelUp bool,
) {
	size := mg.effectiveGridSize()

	mg.chartMu.RLock()
	defer mg.chartMu.RUnlock()

	if row >= 0 && row < size.Rows &&
		col >= 0 && col < size.Cols &&
		row < len(mg.currentPage) && col < len(mg.currentPage[row]) &&
		mg.currentPage[row][col] != nil {
		chart := mg.currentPage[row][col]

		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}
		relativeMouseX := adjustedX - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			// Focus the chart when zooming (if not already focused)
			if mg.focusState.Type != FocusMainChart ||
				mg.focusState.Row != row || mg.focusState.Col != col {
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
