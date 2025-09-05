package leet

import (
	"fmt"
	"sort"

	"github.com/charmbracelet/lipgloss"
)

// ChartDimensions represents chart dimensions for the given window size.
type ChartDimensions struct {
	ChartWidth             int
	ChartHeight            int
	ChartWidthWithPadding  int
	ChartHeightWithPadding int
}

// CalculateChartDimensions computes the chart dimensions based on window size
func CalculateChartDimensions(windowWidth, windowHeight int) ChartDimensions {
	// windowHeight here should already have StatusBarHeight subtracted by the caller
	// Reserve space for header (1 line + 1 margin top)
	headerHeight := 2
	availableHeight := windowHeight - headerHeight
	chartHeightWithPadding := availableHeight / GridRows
	chartWidthWithPadding := windowWidth / GridCols

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
func (m *Model) sortChartsNoLock() {
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
	m.charts = make([][]*EpochLineChart, GridRows)
	for row := 0; row < GridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	// Use filtered charts if filter is active, otherwise use all charts
	chartsToShow := m.filteredCharts
	if len(chartsToShow) == 0 && m.activeFilter == "" {
		chartsToShow = m.allCharts
	}

	startIdx := m.currentPage * ChartsPerPage
	endIdx := startIdx + ChartsPerPage
	if endIdx > len(chartsToShow) {
		endIdx = len(chartsToShow)
	}

	idx := startIdx
	for row := 0; row < GridRows && idx < endIdx; row++ {
		for col := 0; col < GridCols && idx < endIdx; col++ {
			m.charts[row][col] = chartsToShow[idx]
			idx++
		}
	}
}

// updateChartSizes updates all chart sizes when window is resized or sidebar toggled
func (m *Model) updateChartSizes() {
	// Prevent concurrent updates
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
	if availableWidth < MinChartWidth*GridCols {
		availableWidth = MinChartWidth * GridCols
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

	if m.totalPages > 0 && chartCount > 0 {
		startIdx := m.currentPage*ChartsPerPage + 1
		endIdx := startIdx + ChartsPerPage - 1
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
	for row := 0; row < GridRows; row++ {
		var cols []string
		for col := 0; col < GridCols; col++ {
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
		displayTitle := truncateTitle(chart.Title(), availableTitleWidth)

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
