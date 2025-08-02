package leet

import (
	"fmt"
	"math"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/linechart"
	"github.com/charmbracelet/lipgloss"
)

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
			linechart.WithXYSteps(4, 5), // More Y steps for better granularity
			linechart.WithAutoXRange(),
			linechart.WithYLabelFormatter(func(index int, f float64) string {
				// Custom formatter to handle decimal places properly
				if f == 0 {
					return "0"
				}
				// For very small numbers, use scientific notation
				if math.Abs(f) < 0.001 {
					return fmt.Sprintf("%.1e", f)
				}
				// For small numbers, show more decimal places
				if math.Abs(f) < 0.1 {
					return fmt.Sprintf("%.4f", f)
				}
				// For numbers less than 10, show 2 decimal places
				if math.Abs(f) < 10 {
					return fmt.Sprintf("%.2f", f)
				}
				// For larger numbers, show 1 decimal place
				return fmt.Sprintf("%.1f", f)
			}),
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
	valueRange := c.maxValue - c.minValue

	// Handle different scales of data appropriately
	var padding float64
	if valueRange == 0 {
		// All values are the same
		absValue := math.Abs(c.maxValue)
		switch {
		case absValue < 0.001:
			padding = 0.0001 // Very small values
		case absValue < 0.1:
			padding = absValue * 0.1 // Small values
		default:
			padding = 0.1
		}
	} else {
		padding = valueRange * 0.1
		// Ensure minimum padding for very small ranges
		if padding < 1e-6 {
			padding = 1e-6
		}
	}

	newMinY := c.minValue - padding
	newMaxY := c.maxValue + padding

	// For very small values, ensure we don't go negative if all values are positive
	if c.minValue >= 0 && newMinY < 0 {
		newMinY = 0
	}

	// Set both the data range and view range
	c.SetYRange(newMinY, newMaxY)
	c.SetViewYRange(newMinY, newMaxY)

	// Force the chart to recalculate by calling SetXYRange
	c.Model.SetXYRange(c.MinX(), c.MaxX(), newMinY, newMaxY)

	// Auto-expand X range if needed
	if step > int(c.MaxX()) {
		newMax := float64(step + 10) // Expand by 10 steps at a time
		c.SetXRange(0, newMax)
		c.SetViewXRange(0, newMax)
		c.maxSteps = int(newMax)

		// Update the full range including Y to ensure consistency
		c.Model.SetXYRange(0, newMax, newMinY, newMaxY)
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
	// Don't set a fixed Y range - let it be determined by data
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

// Title returns the chart title
func (c *EpochLineChart) Title() string {
	return c.title
}

// IsFocused returns whether the chart is focused
func (c *EpochLineChart) IsFocused() bool {
	return c.focused
}

// SetFocused sets the focused state
func (c *EpochLineChart) SetFocused(focused bool) {
	c.focused = focused
}
