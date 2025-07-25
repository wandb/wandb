package tui

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Model represents the main application state
type Model struct {
	allCharts    []*EpochLineChart
	chartsByName map[string]*EpochLineChart
	charts       [][]*EpochLineChart // Current page of charts arranged in grid
	width        int
	height       int
	step         int
	focusedRow   int
	focusedCol   int
	currentPage  int
	totalPages   int
	fileComplete bool
	runPath      string
	reader       *WandbReader
}

// NewModel creates a new model instance
func NewModel(runPath string) *Model {
	m := &Model{
		allCharts:    make([]*EpochLineChart, 0),
		chartsByName: make(map[string]*EpochLineChart),
		charts:       make([][]*EpochLineChart, GridRows),
		step:         0,
		focusedRow:   -1,
		focusedCol:   -1,
		currentPage:  0,
		totalPages:   0,
		fileComplete: false,
		runPath:      runPath,
	}

	// Initialize the grid structure
	for row := 0; row < GridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	return m
}

// Init implements tea.Model
func (m *Model) Init() tea.Cmd {
	return InitializeReader(m.runPath)
}

// Update implements tea.Model
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case InitMsg:
		m.reader = msg.Reader
		return m, ReadNextHistoryRecord(m.reader)

	case HistoryMsg:
		return m.handleHistoryMsg(msg)

	case TickMsg:
		if !m.fileComplete && m.reader != nil {
			return m, ReadNextHistoryRecord(m.reader)
		}
		return m, nil

	case FileCompleteMsg:
		m.fileComplete = true
		return m, nil

	case ErrorMsg:
		fmt.Fprintf(os.Stderr, "Error reading file: %v\n", msg.Err)
		m.fileComplete = true
		return m, nil

	case tea.MouseMsg:
		return m.handleMouseMsg(msg)

	case tea.KeyMsg:
		return m.handleKeyMsg(msg)

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.updateChartSizes()
	}

	return m, nil
}

// View implements tea.Model
func (m *Model) View() string {
	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	dims := CalculateChartDimensions(m.width, m.height)
	gridView := m.renderGrid(dims)
	statusBar := m.renderStatusBar()

	return lipgloss.JoinVertical(lipgloss.Left, gridView, statusBar)
}

// handleHistoryMsg processes new history data
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	m.step = msg.Step

	// Create charts for new metrics if needed
	for metricName, value := range msg.Metrics {
		chart, exists := m.chartsByName[metricName]
		if !exists {
			dims := CalculateChartDimensions(m.width, m.height)
			colorIndex := len(m.allCharts)
			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, colorIndex, metricName)

			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart

			// Update total pages
			m.totalPages = (len(m.allCharts) + ChartsPerPage - 1) / ChartsPerPage
		}

		// Add data point to the chart
		chart.AddDataPoint(value)
		chart.Draw()
	}

	// Reload current page to show new charts if needed
	m.loadCurrentPage()

	return m, TickCmd()
}

// handleMouseMsg processes mouse events
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	dims := CalculateChartDimensions(m.width, m.height)

	// Find which chart the mouse is over
	row := msg.Y / dims.ChartHeightWithPadding
	col := msg.X / dims.ChartWidthWithPadding

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols && m.charts[row][col] != nil {
		chart := m.charts[row][col]

		// Calculate mouse position relative to the chart's graph area
		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1 // border
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}

		relativeMouseX := msg.X - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			// Focus on the chart under mouse
			m.clearFocus()
			m.focusedRow = row
			m.focusedCol = col
			chart.SetFocused(true)

			// Apply zoom
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				chart.HandleZoom("in", relativeMouseX)
			case tea.MouseButtonWheelDown:
				chart.HandleZoom("out", relativeMouseX)
			}
			chart.Draw()
		}
	}

	return m, nil
}

// handleKeyMsg processes keyboard events
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	switch msg.String() {
	case "q", "ctrl+c":
		if m.reader != nil {
			m.reader.Close()
		}
		return m, tea.Quit

	case "r":
		m.resetCharts()

	case "pgup":
		m.navigatePage(-1)

	case "pgdown":
		m.navigatePage(1)
	}

	return m, nil
}

// clearFocus removes focus from all charts
func (m *Model) clearFocus() {
	if m.focusedRow >= 0 && m.focusedCol >= 0 && m.charts[m.focusedRow][m.focusedCol] != nil {
		m.charts[m.focusedRow][m.focusedCol].SetFocused(false)
	}
}

// resetCharts resets all charts and step counter
func (m *Model) resetCharts() {
	m.step = 0
	for _, chart := range m.allCharts {
		chart.Reset()
	}
	m.loadCurrentPage()
}

// navigatePage changes the current page
func (m *Model) navigatePage(direction int) {
	if direction < 0 {
		// Page up
		if m.currentPage > 0 {
			m.currentPage--
		} else {
			m.currentPage = m.totalPages - 1
		}
	} else {
		// Page down
		if m.currentPage < m.totalPages-1 {
			m.currentPage++
		} else {
			m.currentPage = 0
		}
	}

	m.focusedRow = -1
	m.focusedCol = -1
	m.loadCurrentPage()
}

// renderGrid creates the chart grid view
func (m *Model) renderGrid(dims ChartDimensions) string {
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
	return lipgloss.JoinVertical(lipgloss.Left, rows...)
}

// renderGridCell renders a single grid cell
func (m *Model) renderGridCell(row, col int, dims ChartDimensions) string {
	if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		chart := m.charts[row][col]
		chartView := chart.View()

		// Highlight focused chart
		boxStyle := borderStyle
		if row == m.focusedRow && col == m.focusedCol {
			boxStyle = focusedBorderStyle
		}

		// Create a box with title and chart
		boxContent := lipgloss.JoinVertical(
			lipgloss.Left,
			titleStyle.Render(chart.Title()),
			chartView,
		)

		// Apply border style
		box := boxStyle.Render(boxContent)

		// Center the box in its cell
		return lipgloss.Place(
			dims.ChartWidthWithPadding,
			dims.ChartHeightWithPadding,
			lipgloss.Left,
			lipgloss.Top,
			box,
		)
	}

	// Empty cell
	return lipgloss.NewStyle().
		Width(dims.ChartWidthWithPadding).
		Height(dims.ChartHeightWithPadding).
		Render("")
}

// renderStatusBar creates the status bar
func (m *Model) renderStatusBar() string {
	statusText := fmt.Sprintf("Step: %d • r: reset • q: quit • PgUp/PgDn: navigate", m.step)
	if !m.fileComplete {
		statusText += " • [Reading file...]"
	}

	pageInfo := ""
	if m.totalPages > 0 {
		pageInfo = fmt.Sprintf("Page %d/%d", m.currentPage+1, m.totalPages)
	}

	// Calculate padding between left and right sections
	statusPadding := m.width - lipgloss.Width(statusText) - lipgloss.Width(pageInfo) - 4
	if statusPadding < 0 {
		statusPadding = 0
	}

	return statusBarStyle.Width(m.width).Render(
		lipgloss.NewStyle().Padding(0, 1).Render(statusText) +
			lipgloss.NewStyle().Width(statusPadding).Render("") +
			pageInfoStyle.Render(pageInfo),
	)
}

// loadCurrentPage loads the charts for the current page into the grid
func (m *Model) loadCurrentPage() {
	// Clear current charts grid
	m.charts = make([][]*EpochLineChart, GridRows)
	for row := 0; row < GridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	// Calculate start and end indices for current page
	startIdx := m.currentPage * ChartsPerPage
	endIdx := startIdx + ChartsPerPage
	if endIdx > len(m.allCharts) {
		endIdx = len(m.allCharts)
	}

	// Fill the grid with charts from the current page
	idx := startIdx
	for row := 0; row < GridRows && idx < endIdx; row++ {
		for col := 0; col < GridCols && idx < endIdx; col++ {
			m.charts[row][col] = m.allCharts[idx]
			// Redraw the chart to show any existing data
			m.charts[row][col].Draw()
			idx++
		}
	}
}

// updateChartSizes updates all chart sizes when window is resized
func (m *Model) updateChartSizes() {
	dims := CalculateChartDimensions(m.width, m.height)

	// Update all charts sizes
	for _, chart := range m.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.Draw()
	}

	// Reload current page
	m.loadCurrentPage()
}
