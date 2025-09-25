package leet

import (
	"fmt"
	"sort"
	"sync"

	"github.com/charmbracelet/lipgloss"
)

// metrics holds state for the main run metrics charts (not system metrics).
type metrics struct {
	// Protects all chart collections and derived state below.
	chartMu sync.RWMutex

	// All charts keyed and arranged for display.
	allCharts []*EpochLineChart
	// chartsByName maps metric name to its chart.
	chartsByName map[string]*EpochLineChart
	// charts contains the current page of charts arranged in a 2D grid.
	charts [][]*EpochLineChart

	// Charts filter state.
	filterMode     bool              // Whether we're currently typing a filter
	filterInput    string            // The current filter being typed
	activeFilter   string            // The confirmed filter in use
	filteredCharts []*EpochLineChart // Filtered subset of charts

	// Paging for the main grid.
	currentPage int
	totalPages  int

	// Chart focus state.
	focusState   FocusState
	focusedTitle string // For status bar display
	focusedRow   int
	focusedCol   int
}

func newMetrics(config *ConfigManager) *metrics {
	gridRows, gridCols := config.GetMetricsGrid()

	mg := &metrics{
		allCharts:      make([]*EpochLineChart, 0),
		chartsByName:   make(map[string]*EpochLineChart),
		filteredCharts: make([]*EpochLineChart, 0),
		charts:         make([][]*EpochLineChart, gridRows),
		focusState:     FocusState{Type: FocusNone},
		focusedTitle:   "",
		focusedRow:     -1,
		focusedCol:     -1,
	}
	for r := range gridRows {
		mg.charts[r] = make([]*EpochLineChart, gridCols)
	}
	return mg
}

// ChartDimensions represents chart dimensions for the given window size.
type ChartDimensions struct {
	ChartWidth             int
	ChartHeight            int
	ChartWidthWithPadding  int
	ChartHeightWithPadding int
}

// CalculateChartDimensions computes the chart dimensions based on window size
func CalculateChartDimensions(windowWidth, windowHeight int) ChartDimensions {
	// Read current layout from config (no global vars).
	cfg := GetConfig()
	gridRows, gridCols := cfg.GetMetricsGrid()
	// TODO: should this be in getmetricsgrid?
	if gridRows <= 0 {
		gridRows = 1
	}
	if gridCols <= 0 {
		gridCols = 1
	}

	// windowHeight here should already have StatusBarHeight subtracted by the caller
	// Reserve space for header (1 line + 1 margin top)
	headerHeight := 2
	availableHeight := windowHeight - headerHeight
	chartHeightWithPadding := availableHeight / gridRows
	chartWidthWithPadding := windowWidth / gridCols

	borderChars := 2
	titleLines := 1

	chartWidth := chartWidthWithPadding - borderChars
	chartHeight := chartHeightWithPadding - borderChars - titleLines

	// Ensure minimum size
	if chartHeight < MinChartHeight {
		chartHeight = MinChartHeight
	}
	if chartWidth < MinChartWidth {
		chartWidth = MinChartWidth
	}

	return ChartDimensions{
		ChartWidth:             chartWidth,
		ChartHeight:            chartHeight,
		ChartWidthWithPadding:  chartWidthWithPadding,
		ChartHeightWithPadding: chartHeightWithPadding,
	}
}

// sortChartsNoLock sorts charts without acquiring the mutex (caller must hold the lock)
func (m *metrics) sortChartsNoLock() {
	sort.Slice(m.allCharts, func(i, j int) bool {
		return m.allCharts[i].Title() < m.allCharts[j].Title()
	})

	// Get colors from current color scheme
	graphColors := GetGraphColors()

	// Rebuild chartsByName map and reassign colors based on sorted order
	m.chartsByName = make(map[string]*EpochLineChart)
	for i, chart := range m.allCharts {
		m.chartsByName[chart.Title()] = chart
		// Update chart color based on new position
		chart.graphStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color(graphColors[i%len(graphColors)]))
	}

	// Initialize filtered charts if not already done
	if m.filteredCharts == nil || (len(m.filteredCharts) == 0 && m.activeFilter == "") {
		m.filteredCharts = m.allCharts
	}
}

// loadCurrentPage loads the charts for the current page into the grid
func (m *Model) loadCurrentPage() {
	m.chartMu.Lock()
	defer m.chartMu.Unlock()

	m.loadCurrentPageNoLock()
}

// loadCurrentPageNoLock loads the current page without acquiring the mutex
func (m *Model) loadCurrentPageNoLock() {
	gridRows, gridCols := m.config.GetMetricsGrid()
	chartsPerPage := gridRows * gridCols

	m.charts = make([][]*EpochLineChart, gridRows)
	for row := 0; row < gridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, gridCols)
	}

	// Use filtered charts if filter is active, otherwise use all charts
	chartsToShow := m.filteredCharts
	if len(chartsToShow) == 0 && m.activeFilter == "" {
		chartsToShow = m.allCharts
	}

	startIdx := m.currentPage * chartsPerPage
	endIdx := startIdx + chartsPerPage
	if endIdx > len(chartsToShow) {
		endIdx = len(chartsToShow)
	}

	idx := startIdx
	for row := 0; row < gridRows && idx < endIdx; row++ {
		for col := 0; col < gridCols && idx < endIdx; col++ {
			m.charts[row][col] = chartsToShow[idx]
			idx++
		}
	}
}

// updateChartSizes updates all chart sizes when window is resized or sidebar toggled
func (m *Model) updateChartSizes() {
	defer func() {
		if r := recover(); r != nil {
			m.logger.Error(fmt.Sprintf("panic in updateChartSizes: %v", r))
		}
	}()

	// Get current sidebar widths
	leftWidth := m.sidebar.Width()
	rightWidth := m.rightSidebar.Width()

	// Validate widths
	if leftWidth < 0 {
		leftWidth = 0
	}
	if rightWidth < 0 {
		rightWidth = 0
	}

	// Calculate available width (subtract 2 for left/right margins of the grid container)
	availableWidth := m.width - leftWidth - rightWidth - 2

	// Ensure minimum width
	_, gridCols := m.config.GetMetricsGrid()
	if availableWidth < MinChartWidth*gridCols {
		availableWidth = MinChartWidth * gridCols
	}

	availableHeight := m.height - StatusBarHeight
	dims := CalculateChartDimensions(availableWidth, availableHeight)

	// Resize all charts with mutex protection
	m.chartMu.Lock()
	for _, chart := range m.allCharts {
		if chart != nil {
			chart.Resize(dims.ChartWidth, dims.ChartHeight)
			chart.dirty = true
		}
	}
	m.chartMu.Unlock()

	m.loadCurrentPage()
	// Force redraw of visible charts after resize
	m.drawVisibleCharts()
}

// renderGrid creates the chart grid view
func (m *Model) renderGrid(dims ChartDimensions) string {
	// Build header with consistent padding
	header := headerStyle.Render("Metrics")

	// Add navigation info with mutex protection for chart count
	navInfo := ""
	m.chartMu.RLock()
	chartCount := len(m.filteredCharts)
	if chartCount == 0 && m.activeFilter == "" {
		chartCount = len(m.allCharts)
	}
	totalCount := len(m.allCharts)
	m.chartMu.RUnlock()

	gridRows, gridCols := m.config.GetMetricsGrid()
	chartsPerPage := gridRows * gridCols

	if m.totalPages > 0 && chartCount > 0 {
		startIdx := m.currentPage*chartsPerPage + 1
		endIdx := startIdx + chartsPerPage - 1
		if endIdx > chartCount {
			endIdx = chartCount
		}

		// Show filter info if active
		if m.activeFilter != "" {
			navInfo = navInfoStyle.
				Render(fmt.Sprintf(" [%d-%d of %d filtered from %d total]",
					startIdx, endIdx, chartCount, totalCount))
		} else {
			navInfo = navInfoStyle.
				Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
		}
	}

	// Combine header and nav info horizontally
	headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)

	// Create header container with consistent padding
	headerContainer := headerContainerStyle.Render(headerLine)

	// Render grid
	var rows []string
	for row := 0; row < gridRows; row++ {
		var cols []string
		for col := 0; col < gridCols; col++ {
			cellContent := m.renderGridCell(row, col, dims)
			cols = append(cols, cellContent)
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}
	gridContent := lipgloss.JoinVertical(lipgloss.Left, rows...)

	// Create grid container with consistent padding (removed bottom margin)
	gridContainer := gridContainerStyle.Render(gridContent)

	// Combine header container and grid container
	return lipgloss.JoinVertical(lipgloss.Left, headerContainer, gridContainer)
}

// renderGridCell renders a single grid cell
func (m *Model) renderGridCell(row, col int, dims ChartDimensions) string {
	// Use RLock for reading charts
	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		chart := m.charts[row][col]
		chartView := chart.View()

		boxStyle := borderStyle
		// Highlight if focused
		if row == m.focusedRow && col == m.focusedCol {
			boxStyle = focusedBorderStyle
		}

		// Calculate available width for title (account for padding inside box)
		// Box has 1 char padding on each side, so -2
		availableTitleWidth := max(dims.ChartWidthWithPadding-4, 10)

		// Truncate the title if needed
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

// navigatePage changes the current page
func (m *Model) navigatePage(direction int) {
	if m.totalPages <= 1 {
		return
	}
	m.clearAllFocus() // Clear focus when changing pages
	m.currentPage += direction
	if m.currentPage < 0 {
		m.currentPage = m.totalPages - 1
	} else if m.currentPage >= m.totalPages {
		m.currentPage = 0
	}
	m.loadCurrentPage()
	m.drawVisibleCharts()
}

// rebuildGrids rebuilds the chart grids with new dimensions.
func (m *Model) rebuildGrids() {
	gridRows, gridCols := m.config.GetMetricsGrid()

	m.charts = make([][]*EpochLineChart, gridRows)
	for row := 0; row < gridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, gridCols)
	}

	// Recalculate total pages
	chartsPerPage := gridRows * gridCols

	m.chartMu.RLock()
	chartCount := len(m.allCharts)
	m.chartMu.RUnlock()

	m.totalPages = (chartCount + chartsPerPage - 1) / chartsPerPage

	// Ensure current page is valid
	if m.currentPage >= m.totalPages && m.totalPages > 0 {
		m.currentPage = m.totalPages - 1
	}

	// Rebuild system metrics grid if sidebar is initialized
	if m.rightSidebar != nil && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.RebuildGrid()
	}

	// Clear focus state when resizing
	m.clearAllFocus()
}
