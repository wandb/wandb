package observer

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
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

// handleHistoryMsg processes new history data
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	m.step = msg.Step
	m.logger.Debug(fmt.Sprintf("model: handling history message for step %d with %d metrics", msg.Step, len(msg.Metrics)))

	for metricName, value := range msg.Metrics {
		chart, exists := m.chartsByName[metricName]
		if !exists {
			// First chart creation - exit loading state
			if m.isLoading {
				m.isLoading = false
				m.logger.Debug("model: exiting loading state - first chart created")
			}

			availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
			dims := CalculateChartDimensions(availableWidth, m.height)
			colorIndex := len(m.allCharts)
			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, colorIndex, metricName)

			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart

			m.totalPages = (len(m.allCharts) + ChartsPerPage - 1) / ChartsPerPage
			m.logger.Debug(fmt.Sprintf("model: created new chart for metric: %s", metricName))
		}
		chart.AddDataPoint(value)
		chart.Draw()
	}

	m.loadCurrentPage()
	m.updateChartSizes()
	return m, nil
}

// loadCurrentPage loads the charts for the current page into the grid.
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
			if m.charts[row][col] != nil {
				m.charts[row][col].Draw()
			}
			idx++
		}
	}
}

// updateChartSizes updates all chart sizes when window is resized or sidebar toggled.
func (m *Model) updateChartSizes() {
	// First update sidebar dimensions so they know about each other
	m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
	m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())

	// Then calculate available width with updated sidebar widths
	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
	availableHeight := m.height - StatusBarHeight - 1 // -1 for the metrics header
	dims := CalculateChartDimensions(availableWidth, availableHeight)

	for _, chart := range m.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.Draw()
	}

	m.loadCurrentPage()
}

// navigatePage changes the current page.
func (m *Model) navigatePage(direction int) {
	if m.totalPages <= 1 {
		return
	}
	m.clearFocus()
	if direction < 0 {
		m.currentPage--
		if m.currentPage < 0 {
			m.currentPage = m.totalPages - 1
		}
	} else {
		m.currentPage++
		if m.currentPage >= m.totalPages {
			m.currentPage = 0
		}
	}
	m.loadCurrentPage()
}

// clearFocus removes focus from all charts.
func (m *Model) clearFocus() {
	if m.focusedRow >= 0 && m.focusedCol >= 0 && m.charts[m.focusedRow][m.focusedCol] != nil {
		m.charts[m.focusedRow][m.focusedCol].SetFocused(false)
	}
}

// renderGrid creates the chart grid view.
func (m *Model) renderGrid(dims ChartDimensions) string {
	// Always build header with navigation info (now always visible when not loading)
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
	for row := range GridRows {
		var cols []string
		for col := range GridCols {
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
