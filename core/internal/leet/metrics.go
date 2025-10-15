package leet

import (
	"fmt"
	"sort"
	"sync"

	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

// metrics holds state for the main run metrics charts (not system metrics).
type metrics struct {
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

func NewMetrics(config *ConfigManager, focusState *FocusState, logger *observability.CoreLogger) *metrics {
	gridRows, gridCols := config.MetricsGrid()

	mg := &metrics{
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
func (m *metrics) CalculateChartDimensions(windowWidth, windowHeight int) ChartDimensions {
	gridRows, gridCols := m.config.MetricsGrid()
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
func (m *metrics) effectiveGridSize() GridSize {
	gridRows, gridCols := m.config.MetricsGrid()
	spec := GridSpec{
		Rows:        gridRows,
		Cols:        gridCols,
		MinCellW:    MinChartWidth,
		MinCellH:    MinChartHeight,
		HeaderLines: ChartHeaderHeight,
	}
	return EffectiveGridSize(m.width, m.height, spec)
}

// sortChartsNoLock sorts charts alphabetically and reassigns colors.
// Caller must hold the lock.
func (m *metrics) sortChartsNoLock() {
	sort.Slice(m.allCharts, func(i, j int) bool {
		return m.allCharts[i].Title() < m.allCharts[j].Title()
	})

	graphColors := GetGraphColors()

	m.chartsByName = make(map[string]*EpochLineChart)
	for i, chart := range m.allCharts {
		m.chartsByName[chart.Title()] = chart
		chart.graphStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color(graphColors[i%len(graphColors)]))
	}

	if m.filteredCharts == nil || (len(m.filteredCharts) == 0 && m.activeFilter == "") {
		m.filteredCharts = append(make([]*EpochLineChart, 0, len(m.allCharts)), m.allCharts...)
	}
}

// loadCurrentPage loads the charts for the current page into the grid.
func (m *metrics) loadCurrentPage() {
	m.chartMu.Lock()
	defer m.chartMu.Unlock()
	m.loadCurrentPageNoLock()
}

// loadCurrentPageNoLock loads the current page without acquiring the mutex.
func (m *metrics) loadCurrentPageNoLock() {
	size := m.effectiveGridSize()

	// Rebuild grid structure
	m.currentPage = make([][]*EpochLineChart, size.Rows)
	for row := 0; row < size.Rows; row++ {
		m.currentPage[row] = make([]*EpochLineChart, size.Cols)
	}

	// Use filtered charts if filter is active.
	chartsToShow := m.filteredCharts
	if len(chartsToShow) == 0 && m.activeFilter == "" {
		chartsToShow = m.allCharts
	}

	startIdx, endIdx := m.navigator.GetPageBounds(len(chartsToShow), ItemsPerPage(size))

	idx := startIdx
	for row := 0; row < size.Rows && idx < endIdx; row++ {
		for col := 0; col < size.Cols && idx < endIdx; col++ {
			m.currentPage[row][col] = chartsToShow[idx]
			idx++
		}
	}
}

// UpdateDimensions updates chart sizes based on content viewport.
func (m *metrics) UpdateDimensions(contentWidth, contentHeight int) {
	defer func() {
		if r := recover(); r != nil && m.logger != nil {
			m.logger.Error(fmt.Sprintf("panic in metrics.UpdateDimensions: %v", r))
		}
	}()

	m.width, m.height = contentWidth, contentHeight

	dims := m.CalculateChartDimensions(contentWidth, contentHeight)

	// Resize all charts
	m.chartMu.Lock()
	for _, chart := range m.allCharts {
		if chart != nil {
			chart.Resize(dims.ChartWidth, dims.ChartHeight)
			chart.dirty = true
		}
	}
	m.chartMu.Unlock()

	size := m.effectiveGridSize()
	m.chartMu.RLock()
	chartCount := len(m.filteredCharts)
	if chartCount == 0 && m.activeFilter == "" {
		chartCount = len(m.allCharts)
	}
	m.chartMu.RUnlock()
	m.navigator.UpdateTotalPages(chartCount, ItemsPerPage(size))

	m.loadCurrentPage()
	m.drawVisible()
}

// renderGrid creates the chart grid view.
func (m *metrics) renderGrid(dims ChartDimensions) string {
	header := headerStyle.Render("Metrics")

	// Add navigation info
	navInfo := ""
	m.chartMu.RLock()
	chartCount := len(m.filteredCharts)
	if chartCount == 0 && m.activeFilter == "" {
		chartCount = len(m.allCharts)
	}
	totalCount := len(m.allCharts)
	m.chartMu.RUnlock()

	size := m.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)
	totalPages := m.navigator.TotalPages()

	if totalPages > 0 && chartCount > 0 {
		startIdx, endIdx := m.navigator.GetPageBounds(chartCount, itemsPerPage)
		startIdx++ // Display as 1-indexed

		if m.activeFilter != "" {
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
			cellContent := m.renderGridCell(row, col, dims)
			cols = append(cols, cellContent)
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}
	gridContent := lipgloss.JoinVertical(lipgloss.Left, rows...)
	gridContainer := gridContainerStyle.Render(gridContent)

	// Add vertical filler to use all available height.
	availableHeight := max(m.height-ChartHeaderHeight, 0)
	usedHeight := size.Rows * dims.ChartHeightWithPadding
	extra := availableHeight - usedHeight
	if extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		gridContainer = lipgloss.JoinVertical(lipgloss.Left, gridContainer, filler)
	}

	return lipgloss.JoinVertical(lipgloss.Left, headerContainer, gridContainer)
}

// renderGridCell renders a single grid cell.
func (m *metrics) renderGridCell(row, col int, dims ChartDimensions) string {
	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row < len(m.currentPage) && col < len(m.currentPage[row]) && m.currentPage[row][col] != nil {
		chart := m.currentPage[row][col]
		chartView := chart.View()

		boxStyle := borderStyle
		if m.focusState.Type == FocusMainChart &&
			row == m.focusState.Row && col == m.focusState.Col {
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
func (m *metrics) Navigate(direction int) {
	if !m.navigator.Navigate(direction) {
		return
	}

	m.clearFocus()
	m.loadCurrentPage()
	m.drawVisible()
}

// drawVisible draws charts that are currently visible.
func (m *metrics) drawVisible() {
	size := m.effectiveGridSize()

	for row := 0; row < size.Rows; row++ {
		for col := 0; col < size.Cols; col++ {
			if row < len(m.currentPage) && col < len(m.currentPage[row]) &&
				m.currentPage[row][col] != nil {
				chart := m.currentPage[row][col]
				chart.dirty = true
				chart.Draw()
				chart.dirty = false
			}
		}
	}
}

// handleClick handles clicks in the main chart grid.
func (m *metrics) handleClick(row, col int) {
	// Check if clicking on already focused chart (to unfocus)
	if m.focusState.Type == FocusMainChart &&
		row == m.focusState.Row && col == m.focusState.Col {
		m.clearFocus()
		return
	}

	size := m.effectiveGridSize()

	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row >= 0 && row < size.Rows &&
		col >= 0 && col < size.Cols &&
		row < len(m.currentPage) && col < len(m.currentPage[row]) &&
		m.currentPage[row][col] != nil {
		m.clearFocus()
		m.setFocus(row, col)
	}
}

// setFocus sets focus to a main grid chart.
func (m *metrics) setFocus(row, col int) {
	if row < len(m.currentPage) && col < len(m.currentPage[row]) &&
		m.currentPage[row][col] != nil {
		chart := m.currentPage[row][col]
		m.focusState.Type = FocusMainChart
		m.focusState.Row = row
		m.focusState.Col = col
		m.focusState.Title = chart.Title()
		chart.SetFocused(true)
	}
}

// clearFocus clears focus only from main charts.
func (m *metrics) clearFocus() {
	if m.focusState.Type == FocusMainChart {
		if m.focusState.Row >= 0 && m.focusState.Col >= 0 &&
			m.focusState.Row < len(m.currentPage) &&
			m.focusState.Col < len(m.currentPage[m.focusState.Row]) &&
			m.currentPage[m.focusState.Row][m.focusState.Col] != nil {
			m.currentPage[m.focusState.Row][m.focusState.Col].SetFocused(false)
		}
		m.focusState.Type = FocusNone
		m.focusState.Row = -1
		m.focusState.Col = -1
		m.focusState.Title = ""
	}
}

// HandleWheel performs zoom handling on a main-grid chart at (row, col).
func (m *metrics) HandleWheel(
	adjustedX, row, col int,
	dims ChartDimensions,
	wheelUp bool,
) {
	size := m.effectiveGridSize()

	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row >= 0 && row < size.Rows &&
		col >= 0 && col < size.Cols &&
		row < len(m.currentPage) && col < len(m.currentPage[row]) &&
		m.currentPage[row][col] != nil {
		chart := m.currentPage[row][col]

		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}
		relativeMouseX := adjustedX - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			// Focus the chart when zooming (if not already focused)
			if m.focusState.Type != FocusMainChart ||
				m.focusState.Row != row || m.focusState.Col != col {
				m.clearFocus()
				m.setFocus(row, col)
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
