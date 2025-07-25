package main

import (
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/linechart"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	gridRows      = 3
	gridCols      = 5
	chartsPerPage = gridRows * gridCols
)

var graphColors = []string{"4", "10", "5", "6", "3", "2", "13", "14", "11", "9", "12", "1", "7", "8", "15"}

var axisStyle = lipgloss.NewStyle().
	Foreground(lipgloss.Color("240")) // gray

var labelStyle = lipgloss.NewStyle().
	Foreground(lipgloss.Color("245")) // light gray

var borderStyle = lipgloss.NewStyle().
	BorderStyle(lipgloss.RoundedBorder()).
	BorderForeground(lipgloss.Color("238")) // dark gray

var titleStyle = lipgloss.NewStyle().
	Foreground(lipgloss.Color("250")). // light gray
	Bold(true)

// EpochLineChart is a custom line chart for epoch-based data
type EpochLineChart struct {
	linechart.Model
	data       []float64
	graphStyle lipgloss.Style
	maxSteps   int
	focused    bool
	zoomLevel  float64
	title      string
	minValue   float64
	maxValue   float64
}

// NewEpochLineChart creates a new epoch-based line chart
func NewEpochLineChart(width, height int, colorIndex int, title string) *EpochLineChart {
	graphStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color(graphColors[colorIndex%len(graphColors)]))

	// Start with X range of 0-20 steps and Y range will be auto-adjusted
	chart := &EpochLineChart{
		Model: linechart.New(width, height, 0, 20, 0, 1,
			linechart.WithXYSteps(4, 2),
			linechart.WithAutoXRange(),
		),
		data:       make([]float64, 0),
		graphStyle: graphStyle,
		maxSteps:   20,
		focused:    false,
		zoomLevel:  1.0,
		title:      title,
		minValue:   math.Inf(1),
		maxValue:   math.Inf(-1),
	}

	// Set axis and label styles manually
	chart.Model.AxisStyle = axisStyle
	chart.Model.LabelStyle = labelStyle

	return chart
}

// AddDataPoint adds a new data point for the next step
func (c *EpochLineChart) AddDataPoint(value float64) {
	c.data = append(c.data, value)
	step := len(c.data)

	// Update min/max values
	if value < c.minValue {
		c.minValue = value
	}
	if value > c.maxValue {
		c.maxValue = value
	}

	// Auto-adjust Y range with some padding
	padding := (c.maxValue - c.minValue) * 0.1
	if padding == 0 {
		padding = 0.1
	}
	c.SetYRange(c.minValue-padding, c.maxValue+padding)
	c.SetViewYRange(c.minValue-padding, c.maxValue+padding)

	// Auto-expand X range if needed
	if step > int(c.MaxX()) {
		newMax := float64(step + 10) // Expand by 10 steps at a time
		c.SetXRange(0, newMax)
		c.SetViewXRange(0, newMax)
		c.maxSteps = int(newMax)
	}
}

// Reset clears all data
func (c *EpochLineChart) Reset() {
	c.data = make([]float64, 0)
	c.SetXRange(0, 20)
	c.SetViewXRange(0, 20)
	c.maxSteps = 20
	c.zoomLevel = 1.0
	c.minValue = math.Inf(1)
	c.maxValue = math.Inf(-1)
	c.SetYRange(0, 1)
	c.SetViewYRange(0, 1)
}

// HandleZoom processes zoom events with mouse position
func (c *EpochLineChart) HandleZoom(direction string, mouseX int) {
	// Zoom factor
	zoomFactor := 0.1

	// Get current view range
	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin

	// Calculate the step position under the mouse
	// mouseX is relative to the chart's graph area
	mouseProportion := float64(mouseX) / float64(c.GraphWidth())
	stepUnderMouse := viewMin + mouseProportion*viewRange

	// Calculate new range based on zoom direction
	var newRange float64
	if direction == "in" {
		c.zoomLevel *= (1 - zoomFactor)
		newRange = viewRange * (1 - zoomFactor)
	} else {
		c.zoomLevel *= (1 + zoomFactor)
		newRange = viewRange * (1 + zoomFactor)
	}

	// Ensure minimum and maximum zoom levels
	if newRange < 5 {
		newRange = 5
	}
	if newRange > float64(c.maxSteps) {
		newRange = float64(c.maxSteps)
	}

	// Calculate new min and max, keeping the step under the mouse at the same position
	newMin := stepUnderMouse - newRange*mouseProportion
	newMax := stepUnderMouse + newRange*(1-mouseProportion)

	// Ensure we don't go below 0
	if newMin < 0 {
		newMin = 0
		newMax = newRange
	}

	// Ensure we don't go beyond max steps
	if newMax > float64(c.maxSteps) {
		newMax = float64(c.maxSteps)
		newMin = newMax - newRange
		if newMin < 0 {
			newMin = 0
		}
	}

	// Update view range
	c.SetViewXRange(newMin, newMax)
}

// Draw renders the line chart using Braille patterns
func (c *EpochLineChart) Draw() {
	c.Clear()
	c.DrawXYAxisAndLabel()

	if len(c.data) < 2 {
		return
	}

	// Create braille grid for high-resolution drawing
	bGrid := graph.NewBrailleGrid(
		c.GraphWidth(),
		c.GraphHeight(),
		0, float64(c.GraphWidth()),
		0, float64(c.GraphHeight()),
	)

	// Calculate scale factors based on view range
	xScale := float64(c.GraphWidth()) / (c.ViewMaxX() - c.ViewMinX())
	yScale := float64(c.GraphHeight()) / (c.ViewMaxY() - c.ViewMinY())

	// Convert data points to braille grid coordinates
	points := make([]canvas.Float64Point, 0, len(c.data))
	for i, value := range c.data {
		// Only include points within the view range
		stepX := float64(i)
		if stepX >= c.ViewMinX() && stepX <= c.ViewMaxX() {
			x := (stepX - c.ViewMinX()) * xScale
			y := (value - c.ViewMinY()) * yScale

			// Clamp to graph bounds
			if x >= 0 && x <= float64(c.GraphWidth()) && y >= 0 && y <= float64(c.GraphHeight()) {
				points = append(points, canvas.Float64Point{X: x, Y: y})
			}
		}
	}

	if len(points) < 2 {
		return
	}

	// Draw lines between consecutive points
	for i := 0; i < len(points)-1; i++ {
		p1 := points[i]
		p2 := points[i+1]

		// Get braille grid points
		gp1 := bGrid.GridPoint(p1)
		gp2 := bGrid.GridPoint(p2)

		// Get all points between p1 and p2 for smooth line
		linePoints := graph.GetLinePoints(gp1, gp2)

		// Set all points in the braille grid
		for _, p := range linePoints {
			bGrid.Set(p)
		}
	}

	// Get braille patterns and draw them
	startX := 0
	if c.YStep() > 0 {
		startX = c.Origin().X + 1
	}

	patterns := bGrid.BraillePatterns()
	graph.DrawBraillePatterns(&c.Canvas,
		canvas.Point{X: startX, Y: 0},
		patterns,
		c.graphStyle)
}

// Messages
type historyMsg struct {
	metrics map[string]float64
	step    int
}

type tickMsg time.Time

type fileCompleteMsg struct{}

type errorMsg struct{ err error }

type initMsg struct {
	reader *wandbReader
}

func (e errorMsg) Error() string { return e.err.Error() }

// Model
type model struct {
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
	reader       *wandbReader
}

// wandbReader handles reading from the wandb file
type wandbReader struct {
	store    *stream.Store
	exitSeen bool
}

// newWandbReader creates a new wandb file reader
func newWandbReader(runPath string) (*wandbReader, error) {
	store := stream.NewStore(runPath)
	err := store.Open(os.O_RDONLY)
	if err != nil {
		return nil, err
	}
	return &wandbReader{
		store:    store,
		exitSeen: false,
	}, nil
}

// readNext reads the next history record from the file
func (r *wandbReader) readNext() (map[string]float64, int, error) {
	for {
		record, err := r.store.Read()
		if err == io.EOF && r.exitSeen {
			return nil, 0, io.EOF
		}
		if err != nil {
			return nil, 0, err
		}

		switch rec := record.RecordType.(type) {
		case *spb.Record_History:
			// Extract metrics from history record
			metrics := make(map[string]float64)
			step := 0

			for _, item := range rec.History.Item {
				key := strings.Join(item.NestedKey, ".")

				// Skip internal wandb fields except _step
				if strings.HasPrefix(key, "_") {
					if key == "_step" {
						// Parse step value
						if val, err := strconv.Atoi(strings.Trim(item.ValueJson, "\"")); err == nil {
							step = val
						}
					}
					continue
				}

				// Parse numeric values
				valueStr := strings.Trim(item.ValueJson, "\"")
				if value, err := strconv.ParseFloat(valueStr, 64); err == nil {
					metrics[key] = value
				}
			}

			if len(metrics) > 0 {
				return metrics, step, nil
			}

		case *spb.Record_Exit:
			r.exitSeen = true
		}
	}
}

// Commands
func initializeReader(runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := newWandbReader(runPath)
		if err != nil {
			return errorMsg{err}
		}
		return initMsg{reader: reader}
	}
}

func readNextHistoryRecord(reader *wandbReader) tea.Cmd {
	return func() tea.Msg {
		metrics, step, err := reader.readNext()
		if err == io.EOF {
			return fileCompleteMsg{}
		}
		if err != nil {
			return errorMsg{err}
		}
		return historyMsg{metrics: metrics, step: step}
	}
}

func tickCmd() tea.Cmd {
	return tea.Tick(100*time.Millisecond, func(t time.Time) tea.Msg {
		return tickMsg(t)
	})
}

// Init initializes the model
func (m model) Init() tea.Cmd {
	// Initialize the reader
	return initializeReader(m.runPath)
}

// Update handles messages
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case initMsg:
		// Store the reader and start reading
		m.reader = msg.reader
		return m, readNextHistoryRecord(m.reader)

	case historyMsg:
		// Process new history data
		m.step = msg.step

		// Create charts for new metrics if needed
		for metricName, value := range msg.metrics {
			if _, exists := m.chartsByName[metricName]; !exists {
				// Create new chart with proper dimensions
				chartWidth := 20
				chartHeight := 8
				if m.width > 0 && m.height > 0 {
					// Match the layout calculations from View()
					statusBarHeight := 1
					availableHeight := m.height - statusBarHeight
					chartHeightWithPadding := availableHeight / gridRows
					chartWidthWithPadding := m.width / gridCols

					// Account for borders, title, and padding
					borderChars := 2
					titleLines := 1
					padding := 1

					chartWidth = chartWidthWithPadding - borderChars - padding
					chartHeight = chartHeightWithPadding - borderChars - titleLines - padding

					// Ensure minimum size
					if chartHeight < 5 {
						chartHeight = 5
					}
					if chartWidth < 20 {
						chartWidth = 20
					}
				}

				colorIndex := len(m.allCharts)
				chart := NewEpochLineChart(chartWidth, chartHeight, colorIndex, metricName)

				m.allCharts = append(m.allCharts, chart)
				m.chartsByName[metricName] = chart

				// Update total pages
				m.totalPages = (len(m.allCharts) + chartsPerPage - 1) / chartsPerPage
			}

			// Add data point to the chart
			m.chartsByName[metricName].AddDataPoint(value)
			m.chartsByName[metricName].Draw()
		}

		// Reload current page to show new charts if needed
		m.loadCurrentPage()

		// Wait for tick before reading next record (to simulate real-time)
		return m, tickCmd()

	case tickMsg:
		// After tick, read the next record
		if !m.fileComplete && m.reader != nil {
			return m, readNextHistoryRecord(m.reader)
		}
		return m, nil

	case fileCompleteMsg:
		m.fileComplete = true
		return m, nil

	case errorMsg:
		// Handle error - for now just mark as complete
		fmt.Fprintf(os.Stderr, "Error reading file: %v\n", msg.err)
		m.fileComplete = true
		return m, nil

	case tea.MouseMsg:
		// Handle mouse wheel for zooming
		if tea.MouseEvent(msg).IsWheel() {
			availableHeight := m.height - 1 // -1 for status bar
			chartHeightWithBorder := availableHeight / gridRows
			chartWidthWithBorder := m.width / gridCols

			// Find which chart the mouse is over
			row := msg.Y / chartHeightWithBorder
			col := msg.X / chartWidthWithBorder

			if row >= 0 && row < gridRows && col >= 0 && col < gridCols && m.charts[row][col] != nil {
				chart := m.charts[row][col]

				// Calculate mouse position relative to the chart's graph area
				chartStartX := col * chartWidthWithBorder
				graphStartX := chartStartX + 1 // border
				if chart.YStep() > 0 {
					graphStartX += chart.Origin().X + 1
				}

				relativeMouseX := msg.X - graphStartX

				if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
					// Focus on the chart under mouse
					if m.focusedRow >= 0 && m.focusedCol >= 0 && m.charts[m.focusedRow][m.focusedCol] != nil {
						m.charts[m.focusedRow][m.focusedCol].focused = false
					}
					m.focusedRow = row
					m.focusedCol = col
					chart.focused = true

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
		}

	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "r":
			// Reset all charts and step counter
			m.step = 0
			for _, chart := range m.allCharts {
				chart.Reset()
			}
			m.loadCurrentPage()
		case "pgup":
			if m.currentPage > 0 {
				m.currentPage--
			} else {
				m.currentPage = m.totalPages - 1
			}
			m.focusedRow = -1
			m.focusedCol = -1
			m.loadCurrentPage()
		case "pgdown":
			if m.currentPage < m.totalPages-1 {
				m.currentPage++
			} else {
				m.currentPage = 0
			}
			m.focusedRow = -1
			m.focusedCol = -1
			m.loadCurrentPage()
		}

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.updateChartSizes()
	}

	return m, nil
}

// View renders the UI
func (m model) View() string {
	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	// Calculate dimensions
	statusBarHeight := 1
	availableHeight := m.height - statusBarHeight

	// Calculate per-chart dimensions
	chartHeightWithPadding := availableHeight / gridRows
	chartWidthWithPadding := m.width / gridCols

	// Build the grid
	var rows []string
	for row := 0; row < gridRows; row++ {
		var cols []string
		for col := 0; col < gridCols; col++ {
			if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
				chart := m.charts[row][col]
				chartView := chart.View()

				// Highlight focused chart
				boxStyle := borderStyle
				if row == m.focusedRow && col == m.focusedCol {
					boxStyle = borderStyle.BorderForeground(lipgloss.Color("4"))
				}

				// Create a box with title and chart
				boxContent := lipgloss.JoinVertical(
					lipgloss.Left,
					titleStyle.Render(chart.title),
					chartView,
				)

				// Apply border style
				box := boxStyle.Render(boxContent)

				// Center the box in its cell
				cellContent := lipgloss.Place(
					chartWidthWithPadding,
					chartHeightWithPadding,
					lipgloss.Left,
					lipgloss.Top,
					box,
				)

				cols = append(cols, cellContent)
			} else {
				// Empty cell
				emptyBox := lipgloss.NewStyle().
					Width(chartWidthWithPadding).
					Height(chartHeightWithPadding).
					Render("")
				cols = append(cols, emptyBox)
			}
		}
		// Join columns
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}

	// Join rows
	gridView := lipgloss.JoinVertical(lipgloss.Left, rows...)

	// Create status bar
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

	// Style for page info section
	pageInfoStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}).
		Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#0C8599"}).
		Padding(0, 1)

	statusBar := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
		Background(lipgloss.AdaptiveColor{Light: "#45B7D1", Dark: "#1864AB"}).
		Width(m.width).
		Render(
			lipgloss.NewStyle().Padding(0, 1).Render(statusText) +
				lipgloss.NewStyle().Width(statusPadding).Render("") +
				pageInfoStyle.Render(pageInfo),
		)

	// Combine everything
	return lipgloss.JoinVertical(
		lipgloss.Left,
		gridView,
		statusBar,
	)
}

// loadCurrentPage loads the charts for the current page into the grid
func (m *model) loadCurrentPage() {
	// Clear current charts grid
	m.charts = make([][]*EpochLineChart, gridRows)
	for row := 0; row < gridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, gridCols)
	}

	// Calculate start and end indices for current page
	startIdx := m.currentPage * chartsPerPage
	endIdx := startIdx + chartsPerPage
	if endIdx > len(m.allCharts) {
		endIdx = len(m.allCharts)
	}

	// Fill the grid with charts from the current page
	idx := startIdx
	for row := 0; row < gridRows && idx < endIdx; row++ {
		for col := 0; col < gridCols && idx < endIdx; col++ {
			m.charts[row][col] = m.allCharts[idx]
			// Redraw the chart to show any existing data
			m.charts[row][col].Draw()
			idx++
		}
	}
}

func (m *model) updateChartSizes() {
	// Calculate dimensions to match View() layout
	statusBarHeight := 1
	availableHeight := m.height - statusBarHeight

	// Calculate per-chart dimensions including space for borders
	chartHeightWithPadding := availableHeight / gridRows
	chartWidthWithPadding := m.width / gridCols

	// We need to leave room for:
	// - Border characters (2 horizontal, 2 vertical)
	// - Title (1 line)
	// - Some padding to prevent overlap
	borderChars := 2
	titleLines := 1
	padding := 1

	// Calculate actual chart dimensions
	chartWidth := chartWidthWithPadding - borderChars - padding
	chartHeight := chartHeightWithPadding - borderChars - titleLines - padding

	// Ensure minimum size
	if chartHeight < 5 {
		chartHeight = 5
	}
	if chartWidth < 20 {
		chartWidth = 20
	}

	// Update all charts sizes
	for _, chart := range m.allCharts {
		chart.Resize(chartWidth, chartHeight)
		chart.Draw()
	}

	// Reload current page
	m.loadCurrentPage()
}

func main() {
	flag.Parse()

	if flag.NArg() != 1 {
		fmt.Fprintf(os.Stderr, "Usage: %s <path-to-wandb-file>\n", os.Args[0])
		os.Exit(1)
	}

	runPath := flag.Arg(0)

	// Initialize the model
	m := model{
		allCharts:    make([]*EpochLineChart, 0),
		chartsByName: make(map[string]*EpochLineChart),
		charts:       make([][]*EpochLineChart, gridRows),
		step:         0,
		focusedRow:   -1,
		focusedCol:   -1,
		currentPage:  0,
		totalPages:   0,
		fileComplete: false,
		runPath:      runPath,
	}

	// Initialize the grid structure
	for row := 0; row < gridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, gridCols)
	}

	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		fmt.Printf("Error: %v", err)
		os.Exit(1)
	}
}
