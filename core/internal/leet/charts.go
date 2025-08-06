//go:build !wandb_core

package leet

import (
	"fmt"
	"sort"

	"github.com/charmbracelet/lipgloss"
)

// ChartDimensions calculates chart dimensions for the given window size
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

// sortCharts sorts all charts alphabetically by title and reassigns colors
func (m *Model) sortCharts() {
	m.chartMu.Lock()
	defer m.chartMu.Unlock()

	m.sortChartsNoLock()
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

	startIdx := m.currentPage * ChartsPerPage
	endIdx := startIdx + ChartsPerPage
	if endIdx > len(m.allCharts) {
		endIdx = len(m.allCharts)
	}

	idx := startIdx
	for row := 0; row < GridRows && idx < endIdx; row++ {
		for col := 0; col < GridCols && idx < endIdx; col++ {
			m.charts[row][col] = m.allCharts[idx]
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
	header := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("230")).
		Render("Metrics")

	// Add navigation info with mutex protection for chart count
	navInfo := ""
	m.chartMu.RLock()
	chartCount := len(m.allCharts)
	m.chartMu.RUnlock()

	if m.totalPages > 0 && chartCount > 0 {
		startIdx := m.currentPage*ChartsPerPage + 1
		endIdx := startIdx + ChartsPerPage - 1
		if endIdx > chartCount {
			endIdx = chartCount
		}
		navInfo = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
	}

	// Combine header and nav info horizontally
	headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)

	// Create header container with consistent padding
	headerContainer := lipgloss.NewStyle().
		MarginLeft(1).
		MarginTop(1).
		MarginBottom(0).
		Render(headerLine)

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
	gridContainer := lipgloss.NewStyle().
		MarginLeft(1).
		MarginRight(1).
		Render(gridContent)

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
		if row == m.focusedRow && col == m.focusedCol {
			boxStyle = focusedBorderStyle
		}

		boxContent := lipgloss.JoinVertical(
			lipgloss.Left,
			titleStyle.Render(chart.Title()),
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
