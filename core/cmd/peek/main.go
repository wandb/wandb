package main

import (
	"fmt"
	"math"
	"math/rand"
	"os"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/linechart"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
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

// Extended plot titles - now we have more than 15
var plotTitles = []string{
	// Page 1 (original 15)
	"loss", "accuracy", "f1_score", "precision", "recall",
	"layer_1_weights", "layer_2_bias", "attention_weights", "gradient_norm", "learning_rate",
	"layer_23_att_block_w1", "layer_23_att_block_w2", "layer_24_ffn", "output_logits", "validation_loss",
	// Page 2
	"layer_1_gradients", "layer_2_gradients", "layer_3_weights", "layer_3_bias", "layer_3_gradients",
	"embedding_weights", "embedding_gradients", "optimizer_momentum", "optimizer_variance", "weight_decay",
	"attention_entropy", "token_perplexity", "batch_loss_variance", "gradient_clipping", "effective_lr",
	// Page 3
	"layer_4_weights", "layer_4_bias", "layer_5_weights", "layer_5_bias", "layer_6_weights",
	"positional_encoding", "dropout_rate", "activation_mean", "activation_std", "dead_neurons",
	"gradient_flow", "parameter_norm", "update_ratio", "convergence_rate", "training_speed",
}

// Different Y ranges for different metrics
var plotRanges = map[string][2]float64{
	"loss":             {0, 5},
	"accuracy":         {0, 1},
	"f1_score":         {0, 1},
	"precision":        {0, 1},
	"recall":           {0, 1},
	"learning_rate":    {0, 0.01},
	"gradient_norm":    {0, 10},
	"validation_loss":  {0, 5},
	"effective_lr":     {0, 0.01},
	"dropout_rate":     {0, 1},
	"weight_decay":     {0, 0.1},
	"convergence_rate": {0, 1},
	"training_speed":   {0, 100},
}

// EpochLineChart is a custom line chart for epoch-based data
type EpochLineChart struct {
	linechart.Model
	data       []float64
	graphStyle lipgloss.Style
	maxEpochs  int
	focused    bool
	zoomLevel  float64
	title      string
}

// NewEpochLineChart creates a new epoch-based line chart
func NewEpochLineChart(width, height int, minY, maxY float64, colorIndex int, title string) *EpochLineChart {
	graphStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color(graphColors[colorIndex%len(graphColors)]))

	// Start with X range of 0-20 epochs
	chart := &EpochLineChart{
		Model: linechart.New(width, height, 0, 20, minY, maxY,
			linechart.WithXYSteps(4, 2),
			linechart.WithAutoXRange(), // Auto-expand X range as needed
		),
		data:       make([]float64, 0),
		graphStyle: graphStyle,
		maxEpochs:  20,
		focused:    false,
		zoomLevel:  1.0,
		title:      title,
	}

	// Set axis and label styles manually
	chart.Model.AxisStyle = axisStyle
	chart.Model.LabelStyle = labelStyle

	return chart
}

// AddDataPoint adds a new data point for the next epoch
func (c *EpochLineChart) AddDataPoint(value float64) {
	c.data = append(c.data, value)
	epoch := len(c.data)

	// Auto-expand X range if needed
	if epoch > int(c.MaxX()) {
		newMax := float64(epoch + 10) // Expand by 10 epochs at a time
		c.SetXRange(0, newMax)
		c.SetViewXRange(0, newMax)
		c.maxEpochs = int(newMax)
	}
}

// Reset clears all data
func (c *EpochLineChart) Reset() {
	c.data = make([]float64, 0)
	c.SetXRange(0, 20)
	c.SetViewXRange(0, 20)
	c.maxEpochs = 20
	c.zoomLevel = 1.0
}

// HandleZoom processes zoom events with mouse position
func (c *EpochLineChart) HandleZoom(direction string, mouseX int) {
	// Zoom factor
	zoomFactor := 0.1

	// Get current view range
	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin

	// Calculate the epoch position under the mouse
	// mouseX is relative to the chart's graph area
	mouseProportion := float64(mouseX) / float64(c.GraphWidth())
	epochUnderMouse := viewMin + mouseProportion*viewRange

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
	if newRange > float64(c.maxEpochs) {
		newRange = float64(c.maxEpochs)
	}

	// Calculate new min and max, keeping the epoch under the mouse at the same position
	newMin := epochUnderMouse - newRange*mouseProportion
	newMax := epochUnderMouse + newRange*(1-mouseProportion)

	// Ensure we don't go below 0
	if newMin < 0 {
		newMin = 0
		newMax = newRange
	}

	// Ensure we don't go beyond max epochs
	if newMax > float64(c.maxEpochs) {
		newMax = float64(c.maxEpochs)
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
	// Each character cell can hold 2x4 dots, giving us much higher resolution
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
		epochX := float64(i)
		if epochX >= c.ViewMinX() && epochX <= c.ViewMaxX() {
			x := (epochX - c.ViewMinX()) * xScale
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

type model struct {
	allCharts   []*EpochLineChart   // All charts
	charts      [][]*EpochLineChart // Current page of charts arranged in grid
	width       int
	height      int
	epoch       int
	focusedRow  int
	focusedCol  int
	currentPage int
	totalPages  int
}

func (m model) Init() tea.Cmd {
	// Initialize all charts
	for _, chart := range m.allCharts {
		chart.DrawXYAxisAndLabel()
	}
	m.loadCurrentPage()
	return nil
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

//gocyclo:ignore
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		// Handle mouse wheel for zooming
		if tea.MouseEvent(msg).IsWheel() {
			// Calculate chart dimensions
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

				// Get the actual graph start position (accounting for border and Y-axis)
				graphStartX := chartStartX + 1 // border
				if chart.YStep() > 0 {
					graphStartX += chart.Origin().X + 1
				}

				// Calculate relative mouse X position within the graph area
				relativeMouseX := msg.X - graphStartX

				// Ensure mouse is within graph bounds
				if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
					// Focus on the chart under mouse
					if m.focusedRow >= 0 && m.focusedCol >= 0 && m.charts[m.focusedRow][m.focusedCol] != nil {
						m.charts[m.focusedRow][m.focusedCol].focused = false
					}
					m.focusedRow = row
					m.focusedCol = col
					chart.focused = true

					// Apply zoom centered on mouse position
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
			// Reset all charts and epoch counter
			m.epoch = 0
			for _, chart := range m.allCharts {
				chart.Reset()
			}
			m.loadCurrentPage()
		case " ":
			// Simulate training step - add new data point for current epoch
			m.epoch++
			for _, chart := range m.allCharts {
				// Generate realistic training data
				value := generateTrainingValue(chart.title, m.epoch, chart.MinY(), chart.MaxY())
				chart.AddDataPoint(value)
			}
			// Redraw only visible charts
			for row := 0; row < gridRows; row++ {
				for col := 0; col < gridCols; col++ {
					if m.charts[row][col] != nil {
						m.charts[row][col].Draw()
					}
				}
			}
		case "pgup":
			// Previous page with wrap-around
			if m.currentPage > 0 {
				m.currentPage--
			} else {
				m.currentPage = m.totalPages - 1 // Wrap to last page
			}
			m.focusedRow = -1
			m.focusedCol = -1
			m.loadCurrentPage()
		case "pgdown":
			// Next page with wrap-around
			if m.currentPage < m.totalPages-1 {
				m.currentPage++
			} else {
				m.currentPage = 0 // Wrap to first page
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

// generateTrainingValue simulates realistic training metrics
func generateTrainingValue(metric string, epoch int, minY, maxY float64) float64 {
	switch metric {
	case "loss", "validation_loss", "batch_loss_variance":
		// Loss typically decreases over time with some noise
		base := 3.0 * math.Exp(-float64(epoch)*0.02)
		noise := (rand.Float64() - 0.5) * 0.2
		return math.Max(minY, math.Min(maxY, base+noise))

	case "accuracy", "f1_score", "precision", "recall", "convergence_rate":
		// Accuracy metrics typically increase and plateau
		base := 1.0 - 0.8*math.Exp(-float64(epoch)*0.05)
		noise := (rand.Float64() - 0.5) * 0.05
		return math.Max(0, math.Min(1, base+noise))

	case "learning_rate", "effective_lr":
		// Learning rate might decay over time
		base := 0.001 * math.Pow(0.99, float64(epoch))
		return math.Max(minY, base)

	case "gradient_norm", "gradient_flow", "parameter_norm":
		// Gradient norm varies but generally decreases
		base := 5.0 * math.Exp(-float64(epoch)*0.01)
		noise := rand.Float64() * 2.0
		return math.Max(minY, math.Min(maxY, base+noise))

	case "dropout_rate":
		// Dropout might be constant or scheduled
		return 0.5

	case "training_speed":
		// Training speed in samples/sec, might vary
		base := 50.0
		noise := (rand.Float64() - 0.5) * 20.0
		return math.Max(10, base+noise)

	default:
		// For layer weights and other metrics, just random walk
		rangeSize := maxY - minY
		return minY + rand.Float64()*rangeSize
	}
}

func (m *model) updateChartSizes() {
	// Calculate chart dimensions
	borderWidth := 2  // left and right border
	borderHeight := 3 // top and bottom border + title line

	availableHeight := m.height - 1 // -1 for status bar
	chartHeightWithBorder := availableHeight / gridRows
	chartHeight := chartHeightWithBorder - borderHeight

	chartWidthWithBorder := m.width / gridCols
	chartWidth := chartWidthWithBorder - borderWidth

	// Ensure minimum size
	if chartHeight < 5 {
		chartHeight = 5
	}
	if chartWidth < 15 {
		chartWidth = 15
	}

	// Update all charts sizes
	for _, chart := range m.allCharts {
		chart.Resize(chartWidth, chartHeight)
	}

	// Redraw visible charts
	for row := range gridRows {
		for col := range gridCols {
			if m.charts[row][col] != nil {
				m.charts[row][col].Draw()
			}
		}
	}
}

func (m model) View() string {
	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	// Build the grid
	var rows []string
	for row := range gridRows {
		var cols []string
		for col := range gridCols {
			if m.charts[row][col] != nil {
				chart := m.charts[row][col]
				chartView := chart.View()

				// Highlight focused chart
				boxStyle := borderStyle
				if row == m.focusedRow && col == m.focusedCol {
					boxStyle = borderStyle.BorderForeground(lipgloss.Color("4")) // Blue border for focused
				}

				// Create a box with title and chart
				boxContent := lipgloss.JoinVertical(
					lipgloss.Left,
					titleStyle.Render(chart.title),
					chartView,
				)

				// Apply border style
				box := boxStyle.Render(boxContent)
				cols = append(cols, box)
			} else {
				// Empty cell
				cols = append(cols, "")
			}
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
		rows = append(rows, rowView)
	}

	gridView := lipgloss.JoinVertical(lipgloss.Left, rows...)

	// Create the status bar with epoch counter and page info
	leftStatus := fmt.Sprintf("Epoch: %d • Space: train • r: reset • q: quit • PgUp/PgDn: navigate", m.epoch)
	pageInfo := fmt.Sprintf("Page %d/%d", m.currentPage+1, m.totalPages)

	// Calculate padding between left and right sections
	statusPadding := m.width - lipgloss.Width(leftStatus) - lipgloss.Width(pageInfo) - 4 // -4 for padding
	if statusPadding < 0 {
		statusPadding = 0
	}

	// Style for page info section (different blue)
	pageInfoStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}).
		Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#0C8599"}). // Teal blue
		Padding(0, 1)

	statusBar := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
		Background(lipgloss.AdaptiveColor{Light: "#45B7D1", Dark: "#1864AB"}).
		Width(m.width).
		Render(
			lipgloss.NewStyle().Padding(0, 1).Render(leftStatus) +
				lipgloss.NewStyle().Width(statusPadding).Render("") +
				pageInfoStyle.Render(pageInfo),
		)

	// Calculate padding to fill the screen
	var chartsHeight int
	if len(m.charts) > 0 && len(m.charts[0]) > 0 && m.charts[0][0] != nil {
		chartsHeight = m.charts[0][0].Model.Height() + 3 // +3 for borders and title
	} else {
		chartsHeight = 11 // default
	}
	usedHeight := len(rows) * chartsHeight
	paddingHeight := m.height - usedHeight - 1 // -1 for status bar
	if paddingHeight < 0 {
		paddingHeight = 0
	}

	// Combine everything
	return lipgloss.JoinVertical(
		lipgloss.Left,
		gridView,
		lipgloss.NewStyle().Height(paddingHeight).Render(""),
		statusBar,
	)
}

func main() {
	// Calculate total pages
	totalCharts := len(plotTitles)
	totalPages := (totalCharts + chartsPerPage - 1) / chartsPerPage

	// Initialize the model with all charts
	m := model{
		allCharts:   make([]*EpochLineChart, totalCharts),
		charts:      make([][]*EpochLineChart, gridRows),
		epoch:       0,
		focusedRow:  -1,
		focusedCol:  -1,
		currentPage: 0,
		totalPages:  totalPages,
	}

	// Create all charts
	for i, title := range plotTitles {
		// Use specific ranges for known metrics, default range for others
		minY, maxY := -50.0, 100.0
		if ranges, ok := plotRanges[title]; ok {
			minY, maxY = ranges[0], ranges[1]
		}

		// Create chart with appropriate color
		m.allCharts[i] = NewEpochLineChart(20, 8, minY, maxY, i, title)
	}

	// Initialize the grid structure
	for row := 0; row < gridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, gridCols)
	}

	// Load the first page
	m.loadCurrentPage()

	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		fmt.Printf("Error: %v", err)
		os.Exit(1)
	}
}
