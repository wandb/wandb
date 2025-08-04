package leet

import (
	"fmt"

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
	availableHeight := windowHeight - StatusBarHeight
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

// loadCurrentPage loads the charts for the current page into the grid
func (m *Model) loadCurrentPage() {
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
	// Update sidebar dimensions
	m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
	m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())

	// Calculate available width
	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
	availableHeight := m.height - StatusBarHeight - 1
	dims := CalculateChartDimensions(availableWidth, availableHeight)

	// Resize all charts
	for _, chart := range m.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.dirty = true
	}

	m.loadCurrentPage()
	m.drawVisibleCharts()
}

// renderGrid creates the chart grid view
func (m *Model) renderGrid(dims ChartDimensions) string {
	// Build header
	header := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("230")).
		MarginLeft(1).
		MarginTop(1).
		Render("Metrics")

	// Add navigation info
	navInfo := ""
	if m.totalPages > 0 && len(m.allCharts) > 0 {
		startIdx := m.currentPage*ChartsPerPage + 1
		endIdx := startIdx + ChartsPerPage - 1
		totalMetrics := len(m.allCharts)
		if endIdx > totalMetrics {
			endIdx = totalMetrics
		}
		navInfo = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			MarginTop(1).
			Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, totalMetrics))
	}

	headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)

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

	// Combine header and grid
	return lipgloss.JoinVertical(lipgloss.Left, headerLine, gridContent)
}

// renderGridCell renders a single grid cell
func (m *Model) renderGridCell(row, col int, dims ChartDimensions) string {
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
