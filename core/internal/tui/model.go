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
	sidebar      *Sidebar
	runOverview  RunOverview
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
		sidebar:      NewSidebar(),
	}

	// Initialize the grid structure
	for row := range GridRows {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	// Set initial sidebar content
	m.sidebar.SetRunOverview(RunOverview{
		RunPath:     runPath,
		Config:      make(map[string]interface{}),
		Summary:     make(map[string]interface{}),
		Environment: make(map[string]string),
	})

	return m
}

// Init implements tea.Model
func (m *Model) Init() tea.Cmd {
	return tea.Batch(
		tea.SetWindowTitle("wandb moni"),
		InitializeReader(m.runPath),
	)
}

// Update implements tea.Model
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	updatedSidebar, sidebarCmd := m.sidebar.Update(msg)
	m.sidebar = updatedSidebar
	if sidebarCmd != nil {
		cmds = append(cmds, sidebarCmd)
	}

	switch msg := msg.(type) {
	case InitMsg:
		m.reader = msg.Reader
		cmds = append(cmds, ReadNextHistoryRecord(m.reader))

	case HistoryMsg:
		newModel, cmd := m.handleHistoryMsg(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
		return newModel, tea.Batch(cmds...)

	case TickMsg:
		if !m.fileComplete && m.reader != nil {
			cmds = append(cmds, ReadNextHistoryRecord(m.reader))
		}

	case ConfigMsg:
		m.runOverview.Config = msg.Config
		m.sidebar.SetRunOverview(m.runOverview)

	case SummaryMsg:
		m.runOverview.Summary = msg.Summary
		m.sidebar.SetRunOverview(m.runOverview)

	case SystemInfoMsg:
		m.runOverview.Environment = msg.Environment
		m.sidebar.SetRunOverview(m.runOverview)

	case FileCompleteMsg:
		m.fileComplete = true

	case ErrorMsg:
		fmt.Fprintf(os.Stderr, "Error reading file: %v\n", msg.Err)
		m.fileComplete = true

	case tea.MouseMsg:
		// Don't handle mouse events during pgup/pgdown
		newModel, cmd := m.handleMouseMsg(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
		return newModel, tea.Batch(cmds...)

	case tea.KeyMsg:
		newModel, cmd := m.handleKeyMsg(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
		return newModel, tea.Batch(cmds...)

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.sidebar.UpdateDimensions(msg.Width)
		m.updateChartSizes()

	case SidebarAnimationMsg:
		// Continue animation if needed
		if m.sidebar.IsAnimating() {
			// Update chart sizes during animation for smooth resizing
			m.updateChartSizes()
			cmds = append(cmds, m.sidebar.animationCmd())
		}
	}

	return m, tea.Batch(cmds...)
}

// View implements tea.Model
func (m *Model) View() string {
	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	// Calculate available space for charts
	availableWidth := m.width - m.sidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	// Render main content
	gridView := m.renderGrid(dims)

	// Render sidebar
	sidebarView := m.sidebar.View(m.height - StatusBarHeight)

	// Combine sidebar and main content (without status bar)
	var mainView string
	if m.sidebar.Width() > 0 {
		mainView = lipgloss.JoinHorizontal(
			lipgloss.Top,
			sidebarView,
			gridView,
		)
	} else {
		mainView = gridView
	}

	// Render status bar that spans the full width
	statusBar := m.renderStatusBar()

	// Combine main view and status bar
	return lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
}

// handleHistoryMsg processes new history data
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	m.step = msg.Step

	// Create charts for new metrics if needed
	for metricName, value := range msg.Metrics {
		chart, exists := m.chartsByName[metricName]
		if !exists {
			availableWidth := m.width - m.sidebar.Width()
			dims := CalculateChartDimensions(availableWidth, m.height)
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

	// Check if mouse is in sidebar area
	if msg.X < m.sidebar.Width() {
		// Let sidebar handle its own scrolling
		return m, nil
	}

	// Adjust mouse X position for sidebar offset
	adjustedX := msg.X - m.sidebar.Width()
	availableWidth := m.width - m.sidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	// Find which chart the mouse is over
	row := msg.Y / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols && m.charts[row][col] != nil {
		chart := m.charts[row][col]

		// Calculate mouse position relative to the chart's graph area
		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1 // border
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}

		relativeMouseX := adjustedX - graphStartX

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
	// Check for ctrl+b for sidebar toggle
	if msg.Type == tea.KeyCtrlB {
		m.sidebar.Toggle()
		m.updateChartSizes()
		return m, m.sidebar.animationCmd()
	}

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
	statusText := fmt.Sprintf("Step: %d • ctrl+b: sidebar • r: reset • q: quit • PgUp/PgDn: navigate", m.step)
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

// updateChartSizes updates all chart sizes when window is resized or sidebar toggled
func (m *Model) updateChartSizes() {
	availableWidth := m.width - m.sidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	// Update all charts sizes
	for _, chart := range m.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.Draw()
	}

	// Reload current page
	m.loadCurrentPage()
}
