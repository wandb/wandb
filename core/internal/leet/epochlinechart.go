package leet

import (
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/linechart"
	"github.com/charmbracelet/lipgloss"
)

// EpochLineChart is a custom line chart for epoch-based data.
type EpochLineChart struct {
	linechart.Model

	// xData/yData hold the original samples as (x, y). X is typically _step.
	xData        []float64
	yData        []float64
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

	// Track observed data X range to clamp zoom to real data, not rounded domain.
	xMinData float64
	xMaxData float64
}

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
		xData:      make([]float64, 0, 1000),
		yData:      make([]float64, 0, 1000),
		graphStyle: graphStyle,
		maxSteps:   20,
		focused:    false,
		title:      title,
		minValue:   math.Inf(1),
		maxValue:   math.Inf(-1),
		dirty:      false,
		isZoomed:   false,
		xMinData:   math.Inf(1),
		xMaxData:   math.Inf(-1),
	}

	chart.AxisStyle = axisStyle
	chart.LabelStyle = labelStyle

	return chart
}

// formatYLabel formats Y-axis labels
func formatYLabel(index int, f float64) string {
	// Use the enhanced FormatYLabel function from systemmetrics.go
	// For regular metrics, we don't have units, so pass empty string
	return FormatYLabel(f, "")
}

// AddPoint adds a new (x,y) data point (x is commonly _step).
func (c *EpochLineChart) AddPoint(x, y float64) {
	c.xData = append(c.xData, x)
	c.yData = append(c.yData, y)

	if y < c.minValue {
		c.minValue = y
	}
	if y > c.maxValue {
		c.maxValue = y
	}
	if x < c.xMinData {
		c.xMinData = x
	}
	if x > c.xMaxData {
		c.xMaxData = x
	}

	c.updateRanges()
	c.dirty = true
}

// updateRanges updates the chart ranges based on current data
func (c *EpochLineChart) updateRanges() {
	if len(c.yData) == 0 {
		return
	}

	// Y range with padding.
	valueRange := c.maxValue - c.minValue
	padding := c.calculatePadding(valueRange)

	newMinY := c.minValue - padding
	newMaxY := c.maxValue + padding

	// Don't go negative for non-negative data
	if c.minValue >= 0 && newMinY < 0 {
		newMinY = 0
	}

	// X domain.
	// Round up the observed max X to a "nice" domain for axis display.
	dataMaxX := c.xMaxData
	if !isFinite(dataMaxX) {
		dataMaxX = 0
	}
	niceMax := dataMaxX
	if niceMax < 20 {
		// Keep a decent default domain early in a run
		niceMax = 20
	} else {
		// Round to nearest 10 like before
		niceMax = float64(((int(math.Ceil(niceMax)) + 9) / 10) * 10)
	}
	c.maxSteps = int(math.Ceil(niceMax)) // keep this for status/labels

	// Update axis ranges
	c.SetYRange(newMinY, newMaxY)
	c.SetViewYRange(newMinY, newMaxY)

	// Always ensure X range covers the nice domain; only alter view if not zoomed.
	c.SetXRange(0, niceMax)
	if !c.isZoomed {
		viewMin := c.xMinData
		if !isFinite(viewMin) {
			viewMin = 0
		}
		c.SetViewXRange(viewMin, niceMax)
	}

	c.SetXYRange(c.MinX(), c.MaxX(), newMinY, newMaxY)
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

// HandleZoom processes zoom events with mouse position
func (c *EpochLineChart) HandleZoom(direction string, mouseX int) {
	const zoomFactor = 0.1
	const minRange = 5.0

	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin
	if viewRange <= 0 {
		return
	}

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
	if newRange < minRange {
		newRange = minRange
	}
	// Don't allow ranges larger than the domain
	if newRange > c.MaxX()-c.MinX() {
		newRange = c.MaxX() - c.MinX()
	}

	// Calculate new bounds keeping mouse position stable
	newMin := stepUnderMouse - newRange*mouseProportion
	newMax := stepUnderMouse + newRange*(1-mouseProportion)

	// Only apply tail nudge when zooming in AND mouse is at the far right
	if direction == "in" && mouseProportion >= 0.95 && isFinite(c.xMaxData) {
		// Check if we're losing the tail
		rightPad := c.pixelEpsX(newRange) * 2 // Small padding for the last data point
		if newMax < c.xMaxData-rightPad {
			// Adjust to include the tail
			shift := (c.xMaxData + rightPad) - newMax
			newMin += shift
			newMax += shift
		}
	}

	// Final clamp to domain [MinX .. MaxX]
	domMin, domMax := c.MinX(), c.MaxX()
	if newMin < domMin {
		newMin = domMin
		newMax = newMin + newRange
		if newMax > domMax {
			newMax = domMax
		}
	}
	if newMax > domMax {
		newMax = domMax
		newMin = newMax - newRange
		if newMin < domMin {
			newMin = domMin
		}
	}

	c.SetViewXRange(newMin, newMax)
	c.userViewMinX = newMin
	c.userViewMaxX = newMax
	c.isZoomed = true
	c.dirty = true
}

// Draw renders the line chart using Braille patterns
//
//gocyclo:ignore
func (c *EpochLineChart) Draw() {
	c.Clear()
	c.DrawXYAxisAndLabel()

	c.Clear()
	c.DrawXYAxisAndLabel()

	// Nothing to draw?
	if len(c.xData) == 0 || len(c.yData) == 0 {
		c.dirty = false
		return
	}

	// Compute visible data indices via binary search on X.
	lb := sort.Search(len(c.xData), func(i int) bool { return c.xData[i] >= c.ViewMinX() })
	// Add a tiny epsilon so a point exactly at viewMax isn't dropped by rounding.
	eps := c.pixelEpsX(c.ViewMaxX() - c.ViewMinX())
	ub := sort.Search(len(c.xData), func(i int) bool { return c.xData[i] > c.ViewMaxX()+eps }) // exclusive
	if ub-lb <= 0 {
		c.dirty = false
		return
	}

	// Build a grid for drawing
	bGrid := graph.NewBrailleGrid(
		c.GraphWidth(),
		c.GraphHeight(),
		0, float64(c.GraphWidth()),
		0, float64(c.GraphHeight()),
	)

	// Scale factors
	xScale := float64(c.GraphWidth()) / (c.ViewMaxX() - c.ViewMinX())
	yScale := float64(c.GraphHeight()) / (c.ViewMaxY() - c.ViewMinY())

	// If only one visible point, draw a dot.
	if ub-lb == 1 {
		x := (c.xData[lb] - c.ViewMinX()) * xScale
		y := (c.yData[lb] - c.ViewMinY()) * yScale
		if x >= 0 && x <= float64(c.GraphWidth()) && y >= 0 && y <= float64(c.GraphHeight()) {
			point := canvas.Float64Point{X: x, Y: y}
			gp := bGrid.GridPoint(point)
			bGrid.Set(gp)

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
		c.dirty = false
		return
	}

	// Convert visible data points to canvas coordinates
	points := make([]canvas.Float64Point, 0, ub-lb)
	for i := lb; i < ub; i++ {
		x := (c.xData[i] - c.ViewMinX()) * xScale
		y := (c.yData[i] - c.ViewMinY()) * yScale

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

// pixelEpsX returns ~1 horizontal pixel in X units for the current graph.
func (c *EpochLineChart) pixelEpsX(xRange float64) float64 {
	if c.GraphWidth() <= 0 || xRange <= 0 {
		return 0
	}
	return xRange / float64(c.GraphWidth())
}

// drawLine draws a line using Bresenham's algorithm.
//
// See https://en.wikipedia.org/wiki/Bresenham%27s_line_algorithm.
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

func isFinite(f float64) bool {
	return !math.IsNaN(f) && !math.IsInf(f, 0)
}

// TruncateTitle truncates a title to fit within maxWidth, adding ellipsis if needed
func TruncateTitle(title string, maxWidth int) string {
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

// FormatYLabel formats Y-axis labels with appropriate units and precision.
//
//gocyclo:ignore
func FormatYLabel(value float64, unit string) string {
	// Handle zero specially
	if value == 0 {
		return "0"
	}

	// For percentages, simple format
	if unit == "%" {
		if value >= 100 {
			return formatFloat(value, 0) + "%"
		}
		if value >= 10 {
			return formatFloat(value, 1) + "%"
		}
		return formatFloat(value, 2) + "%"
	}

	// For temperature - ensure proper ordering by padding
	if unit == "°C" {
		if value >= 100 {
			return formatFloat(value, 0) + "°C"
		}
		return formatFloat(value, 1) + "°C"
	}

	// For power (W)
	if unit == "W" {
		if value >= 1000 {
			return formatFloat(value/1000, 1) + "kW"
		}
		if value >= 100 {
			return formatFloat(value, 0) + "W"
		}
		return formatFloat(value, 1) + "W"
	}

	// For frequency (MHz) - ensure proper ordering
	if unit == "MHz" {
		if value >= 1000 {
			return formatFloat(value/1000, 2) + "GHz"
		}
		if value >= 100 {
			return formatFloat(value, 0) + "MHz"
		}
		return formatFloat(value, 1) + "MHz"
	}

	// For bytes (network metrics are cumulative bytes)
	if unit == "B" {
		return formatBytes(value, false)
	}

	// For memory/data in MB (disk I/O cumulative)
	if unit == "MB" {
		if value >= 1024*1024 {
			return formatFloat(value/(1024*1024), 1) + "TB"
		}
		if value >= 1024 {
			return formatFloat(value/1024, 1) + "GB"
		}
		return formatFloat(value, 0) + "MB"
	}

	// For memory/data in GB
	if unit == "GB" {
		if value >= 1024 {
			return formatFloat(value/1024, 1) + "TB"
		}
		return formatFloat(value, 1) + "GB"
	}

	// For rates (MB/s, GB/s) - these are actual rates
	if strings.HasSuffix(unit, "/s") {
		baseUnit := strings.TrimSuffix(unit, "/s")
		return formatRate(value, baseUnit)
	}

	// Default: just show the number with appropriate precision
	if value >= 1000000 {
		return formatFloat(value/1000000, 1) + "M"
	}
	if value >= 1000 {
		return formatFloat(value/1000, 1) + "k"
	}
	if value < 0.01 {
		return formatFloat(value*1000, 1) + "m"
	}
	if value < 1 {
		return formatFloat(value, 2)
	}
	if value < 10 {
		return formatFloat(value, 1) + ""
	}
	return formatFloat(value, 0)
}

// formatFloat formats a float with specified decimal places
func formatFloat(value float64, decimals int) string {
	formatted := strconv.FormatFloat(value, 'f', decimals, 64)

	// Only trim zeros after decimal point, not before it
	if decimals > 0 && strings.Contains(formatted, ".") {
		// Remove trailing zeros after decimal point
		formatted = strings.TrimRight(formatted, "0")
		// Remove trailing decimal point if no fractional part remains
		formatted = strings.TrimRight(formatted, ".")
	}

	if formatted == "" {
		formatted = "0"
	}

	return formatted
}

// formatBytes formats byte values with binary prefixes.
func formatBytes(bytes float64, isGB bool) string {
	// If input is already in GB, convert to bytes
	if isGB {
		bytes = bytes * 1024 * 1024 * 1024
	}

	units := []string{"B", "KiB", "MiB", "GiB", "TiB"}
	unitIndex := 0
	value := bytes

	for unitIndex < len(units)-1 && value >= 1024 {
		value /= 1024
		unitIndex++
	}

	if unitIndex == 0 {
		return formatFloat(value, 0) + units[unitIndex]
	}
	return formatFloat(value, 1) + units[unitIndex]
}

// formatRate formats rate values (MB/s, GB/s).
func formatRate(value float64, baseUnit string) string {
	// Convert to bytes if needed
	switch baseUnit {
	case "MB":
		value = value * 1024 * 1024
	case "GB":
		value = value * 1024 * 1024 * 1024
	}

	// Now format with decimal prefixes
	if value >= 1e9 {
		return formatFloat(value/1e9, 1) + "GB/s"
	}
	if value >= 1e6 {
		return formatFloat(value/1e6, 1) + "MB/s"
	}
	if value >= 1e3 {
		return formatFloat(value/1e3, 1) + "KB/s"
	}
	return formatFloat(value, 0) + "B/s"
}
