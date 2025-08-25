//go:build !wandb_core

package leet

import (
	"math"
	"strings"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/linechart"
	"github.com/charmbracelet/lipgloss"
)

// EpochLineChart is a custom line chart for epoch-based data
type EpochLineChart struct {
	linechart.Model
	data         []float64
	graphStyle   lipgloss.Style
	maxSteps     int
	focused      bool
	title        string
	minValue     float64
	maxValue     float64
	dirty        bool
	isZoomed     bool    // Track if user has zoomed
	userViewMinX float64 // Preserve user's zoom settings
	userViewMaxX float64
}

// NewEpochLineChart creates a new epoch-based line chart
func NewEpochLineChart(width, height int, colorIndex int, title string) *EpochLineChart {
	// Get colors from current color scheme
	graphColors := GetGraphColors()

	// Temporarily use a default style - it will be updated during sorting
	graphStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color(graphColors[0]))

	chart := &EpochLineChart{
		Model: linechart.New(width, height, 0, 20, 0, 1,
			linechart.WithXYSteps(4, 5),
			linechart.WithAutoXRange(),
			linechart.WithYLabelFormatter(formatYLabel),
		),
		data:       make([]float64, 0, 1000),
		graphStyle: graphStyle,
		maxSteps:   20,
		focused:    false,
		title:      title,
		minValue:   math.Inf(1),
		maxValue:   math.Inf(-1),
		dirty:      false,
		isZoomed:   false,
	}

	chart.Model.AxisStyle = axisStyle
	chart.Model.LabelStyle = labelStyle

	return chart
}

// formatYLabel formats Y-axis labels
func formatYLabel(index int, f float64) string {
	// Use the enhanced FormatYLabel function from systemmetrics.go
	// For regular metrics, we don't have units, so pass empty string
	return FormatYLabel(f, "")
}

// SetDataBulk sets all data points at once for optimal performance
func (c *EpochLineChart) SetDataBulk(values []float64) {
	c.data = make([]float64, len(values))
	copy(c.data, values)

	// Calculate min/max in one pass
	c.minValue = math.Inf(1)
	c.maxValue = math.Inf(-1)

	for _, v := range values {
		if v < c.minValue {
			c.minValue = v
		}
		if v > c.maxValue {
			c.maxValue = v
		}
	}

	c.updateRanges()
	c.dirty = true
}

// AddDataPoint adds a new data point for live updates
func (c *EpochLineChart) AddDataPoint(value float64) {
	c.data = append(c.data, value)

	if value < c.minValue {
		c.minValue = value
	}
	if value > c.maxValue {
		c.maxValue = value
	}

	c.updateRanges()
	c.dirty = true
}

// updateRanges updates the chart ranges based on current data
func (c *EpochLineChart) updateRanges() {
	if len(c.data) == 0 {
		return
	}

	step := len(c.data)

	// Calculate Y range with padding
	valueRange := c.maxValue - c.minValue
	padding := c.calculatePadding(valueRange)

	newMinY := c.minValue - padding
	newMaxY := c.maxValue + padding

	// Don't go negative for non-negative data
	if c.minValue >= 0 && newMinY < 0 {
		newMinY = 0
	}

	// Update Y ranges
	c.SetYRange(newMinY, newMaxY)
	c.SetViewYRange(newMinY, newMaxY)

	// Auto-expand X range if needed
	if step > int(c.MaxX()) {
		newMax := float64(((step + 9) / 10) * 10) // Round up to nearest 10
		c.SetXRange(0, newMax)
		c.maxSteps = int(newMax)

		// Only update view if not zoomed
		if !c.isZoomed {
			c.SetViewXRange(0, newMax)
		}
	}

	c.Model.SetXYRange(c.MinX(), c.MaxX(), newMinY, newMaxY)
}

// calculatePadding determines appropriate padding for the Y axis
func (c *EpochLineChart) calculatePadding(valueRange float64) float64 {
	if valueRange == 0 {
		absValue := math.Abs(c.maxValue)
		switch {
		case absValue < 0.001:
			return 0.0001
		case absValue < 0.1:
			return absValue * 0.1
		default:
			return 0.1
		}
	}

	padding := valueRange * 0.1
	if padding < 1e-6 {
		padding = 1e-6
	}
	return padding
}

// Reset clears all data
func (c *EpochLineChart) Reset() {
	c.data = make([]float64, 0, 1000)
	c.SetXRange(0, 20)
	c.SetViewXRange(0, 20)
	c.maxSteps = 20
	c.minValue = math.Inf(1)
	c.maxValue = math.Inf(-1)
	c.SetYRange(0, 1)
	c.SetViewYRange(0, 1)
	c.dirty = true
	c.isZoomed = false
}

// HandleZoom processes zoom events with mouse position
func (c *EpochLineChart) HandleZoom(direction string, mouseX int) {
	const zoomFactor = 0.1

	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin

	// Calculate the step position under the mouse
	mouseProportion := float64(mouseX) / float64(c.GraphWidth())
	stepUnderMouse := viewMin + mouseProportion*viewRange

	// Calculate new range
	var newRange float64
	if direction == "in" {
		newRange = viewRange * (1 - zoomFactor)
	} else {
		newRange = viewRange * (1 + zoomFactor)
	}

	// Clamp zoom levels
	if newRange < 5 {
		newRange = 5
	}
	if newRange > float64(c.maxSteps) {
		newRange = float64(c.maxSteps)
	}

	// Calculate new bounds keeping mouse position stable
	newMin := stepUnderMouse - newRange*mouseProportion
	newMax := stepUnderMouse + newRange*(1-mouseProportion)

	// Clamp to valid range
	if newMin < 0 {
		newMin = 0
		newMax = newRange
	}
	if newMax > float64(c.maxSteps) {
		newMax = float64(c.maxSteps)
		newMin = newMax - newRange
		if newMin < 0 {
			newMin = 0
		}
	}

	c.SetViewXRange(newMin, newMax)
	c.userViewMinX = newMin
	c.userViewMaxX = newMax
	c.isZoomed = true
	c.dirty = true
}

// Draw renders the line chart using Braille patterns
func (c *EpochLineChart) Draw() {
	c.Clear()
	c.DrawXYAxisAndLabel()

	if len(c.data) < 2 {
		c.dirty = false
		return
	}

	// Calculate visible range
	viewMinX := int(c.ViewMinX())
	viewMaxX := int(c.ViewMaxX() + 1)

	if viewMinX < 0 {
		viewMinX = 0
	}
	if viewMaxX > len(c.data) {
		viewMaxX = len(c.data)
	}

	if viewMaxX <= viewMinX || viewMaxX-viewMinX < 2 {
		c.dirty = false
		return
	}

	// Create braille grid
	bGrid := graph.NewBrailleGrid(
		c.GraphWidth(),
		c.GraphHeight(),
		0, float64(c.GraphWidth()),
		0, float64(c.GraphHeight()),
	)

	// Calculate scale factors
	xScale := float64(c.GraphWidth()) / (c.ViewMaxX() - c.ViewMinX())
	yScale := float64(c.GraphHeight()) / (c.ViewMaxY() - c.ViewMinY())

	// Convert visible data points to canvas coordinates
	points := make([]canvas.Float64Point, 0, viewMaxX-viewMinX)
	for i := viewMinX; i < viewMaxX; i++ {
		x := (float64(i) - c.ViewMinX()) * xScale
		y := (c.data[i] - c.ViewMinY()) * yScale

		if x >= 0 && x <= float64(c.GraphWidth()) && y >= 0 && y <= float64(c.GraphHeight()) {
			points = append(points, canvas.Float64Point{X: x, Y: y})
		}
	}

	if len(points) < 2 {
		c.dirty = false
		return
	}

	// Draw lines between consecutive points
	for i := 0; i < len(points)-1; i++ {
		gp1 := bGrid.GridPoint(points[i])
		gp2 := bGrid.GridPoint(points[i+1])
		drawLine(bGrid, gp1, gp2)
	}

	// Render braille patterns
	startX := 0
	if c.YStep() > 0 {
		startX = c.Origin().X + 1
	}

	patterns := bGrid.BraillePatterns()
	graph.DrawBraillePatterns(&c.Canvas,
		canvas.Point{X: startX, Y: 0},
		patterns,
		c.graphStyle)

	c.dirty = false
}

// drawLine draws a line using Bresenham's algorithm
func drawLine(bGrid *graph.BrailleGrid, p1, p2 canvas.Point) {
	dx := abs(p2.X - p1.X)
	dy := abs(p2.Y - p1.Y)

	sx := 1
	if p1.X > p2.X {
		sx = -1
	}

	sy := 1
	if p1.Y > p2.Y {
		sy = -1
	}

	err := dx - dy
	x, y := p1.X, p1.Y

	for {
		bGrid.Set(canvas.Point{X: x, Y: y})

		if x == p2.X && y == p2.Y {
			break
		}

		e2 := 2 * err
		if e2 > -dy {
			err -= dy
			x += sx
		}
		if e2 < dx {
			err += dx
			y += sy
		}
	}
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

// DrawIfNeeded only draws if the chart is marked as dirty
func (c *EpochLineChart) DrawIfNeeded() {
	if c.dirty {
		c.Draw()
	}
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

// Resize updates the chart dimensions
func (c *EpochLineChart) Resize(width, height int) {
	// Check if dimensions actually changed
	if c.Width() != width || c.Height() != height {
		c.Model.Resize(width, height)
		c.dirty = true
		// Force recalculation of ranges after resize
		c.updateRanges()
	}
}

// truncateTitle truncates a title to fit within maxWidth, adding ellipsis if needed
func truncateTitle(title string, maxWidth int) string {
	if lipgloss.Width(title) <= maxWidth {
		return title
	}

	// Account for ellipsis width (3 chars)
	if maxWidth <= 3 {
		// Not enough space even for ellipsis
		return "..."
	}

	availableWidth := maxWidth - 3

	// Try to break at a separator for cleaner truncation
	separators := []string{"/", "_", ".", "-", ":"}

	// Find the best truncation point
	bestTruncateAt := 0
	for i := range title {
		if lipgloss.Width(title[:i]) > availableWidth {
			break
		}
		bestTruncateAt = i
	}

	// If we have a reasonable amount of text, look for a separator
	if bestTruncateAt > availableWidth/2 {
		// Look for a separator near the truncation point for cleaner break
		for _, sep := range separators {
			if idx := strings.LastIndex(title[:bestTruncateAt], sep); idx > bestTruncateAt*2/3 {
				// Found a good separator position
				bestTruncateAt = idx + len(sep)
				break
			}
		}
	}

	// Safety check
	if bestTruncateAt <= 0 {
		bestTruncateAt = 1
	}
	if bestTruncateAt > len(title) {
		bestTruncateAt = len(title)
	}

	return title[:bestTruncateAt] + "..."
}
