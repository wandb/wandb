package leet

import (
	"math"
	"slices"
	"sort"
	"strings"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/linechart"
	"github.com/charmbracelet/lipgloss"
)

const (
	defaultZoomFactor        = 0.10
	minZoomRange             = 5.0
	tailAnchorMouseThreshold = 0.95
	defaultMaxX              = 20
	defaultMaxY              = 1
)

// EpochLineChart is a custom line chart for epoch-based data.
type EpochLineChart struct {
	// Embedded ntcharts line chart backend (canvas, axes, ranges).
	linechart.Model

	// xData/yData are the raw samples appended in arrival order.
	//
	// X is currently `_step` (monotonic, non‑decreasing), which is used by Draw
	// to efficiently binary‑search the visible window.
	xData, yData []float64

	// graphStyle is the foreground style used to render the series line/dots.
	graphStyle lipgloss.Style

	// focused indicates whether this chart is focused in the grid.
	focused bool

	// title is the metric name shown in the chart header and used for sorting and lookups.
	title string

	// dirty marks the chart as needing a redraw.
	dirty bool

	// isZoomed is set after the user adjusts the X view via HandleZoom.
	//
	// When true, updateRanges will not auto‑reset the X view.
	isZoomed bool

	// userViewMinX/userViewMaxX hold the last user‑selected X view range so
	// intent can be preserved across updates.
	userViewMinX, userViewMaxX float64

	// xMin/xMax track the observed X bounds of the data.
	//
	// Used to set the axis domain and to clamp/anchor zooming near the tail.
	xMin, xMax float64

	// yMin/yMax are the observed Y bounds used to compute padded Y axes.
	yMin, yMax float64
}

func NewEpochLineChart(width, height int, title string) *EpochLineChart {
	graphColors := GraphColors()

	// Temporarily use a default style - it will be updated during sorting.
	graphStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color(graphColors[0]))

	chart := &EpochLineChart{
		Model: linechart.New(width, height, 0, defaultMaxX, 0, defaultMaxY,
			linechart.WithXYSteps(4, 5),
			linechart.WithAutoXRange(),
			linechart.WithYLabelFormatter(func(i int, v float64) string {
				return FormatYLabel(v, "")
			}),
		),
		xData:      make([]float64, 0, 1000),
		yData:      make([]float64, 0, 1000),
		graphStyle: graphStyle,
		title:      title,
		xMin:       math.Inf(1),
		xMax:       math.Inf(-1),
		yMin:       math.Inf(1),
		yMax:       math.Inf(-1),
	}

	chart.AxisStyle = axisStyle
	chart.LabelStyle = labelStyle

	return chart
}

// AddData adds a set of new (x, y) data points (x is commonly _step).
//
// X values should be appended in non-decreasing order for efficient rendering.
func (c *EpochLineChart) AddData(data MetricData) {
	c.xData = slices.Concat(c.xData, data.X)
	c.yData = slices.Concat(c.yData, data.Y)

	xMin, xMax := slices.Min(data.X), slices.Max(data.X)
	yMin, yMax := slices.Min(data.Y), slices.Max(data.Y)

	c.yMin = math.Min(c.yMin, yMin)
	c.yMax = math.Max(c.yMax, yMax)
	c.xMin = math.Min(c.xMin, xMin)
	c.xMax = math.Max(c.xMax, xMax)

	c.updateRanges()
	c.dirty = true
}

// updateRanges updates the chart ranges based on current data.
func (c *EpochLineChart) updateRanges() {
	if len(c.yData) == 0 {
		return
	}

	// Y range with padding.
	valueRange := c.yMax - c.yMin
	padding := c.calculatePadding(valueRange)

	newYMin := c.yMin - padding
	newYMax := c.yMax + padding

	// Don't go negative for non-negative data.
	if c.yMin >= 0 && newYMin < 0 {
		newYMin = 0
	}

	// X domain.
	// Round up the observed max X to a "nice" domain for axis display.
	dataXMax := c.xMax
	if !isFinite(dataXMax) {
		dataXMax = 0
	}
	niceMax := dataXMax
	if niceMax < defaultMaxX {
		// Keep a decent default domain early in a run.
		niceMax = defaultMaxX
	} else {
		// Round to nearest 10.
		niceMax = float64(((int(math.Ceil(niceMax)) + 9) / 10) * 10)
	}

	// Update axis ranges
	c.SetYRange(newYMin, newYMax)
	c.SetViewYRange(newYMin, newYMax)

	// Always ensure X range covers the nice domain; only alter view if not zoomed.
	c.SetXRange(0, niceMax)
	if !c.isZoomed {
		viewMin := c.xMin
		if !isFinite(viewMin) {
			viewMin = 0
		}
		c.SetViewXRange(viewMin, niceMax)
	}

	c.SetXYRange(c.MinX(), c.MaxX(), newYMin, newYMax)
}

// calculatePadding determines appropriate padding for the Y axis
func (c *EpochLineChart) calculatePadding(valueRange float64) float64 {
	if valueRange == 0 {
		absValue := math.Abs(c.yMax)
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

// HandleZoom processes zoom events with the mouse X position in pixels.
func (c *EpochLineChart) HandleZoom(direction string, mouseX int) {
	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin
	if viewRange <= 0 {
		return
	}

	// Calculate the step position under the mouse
	mouseProportion := float64(mouseX) / float64(c.GraphWidth())
	// Clamp to [0, 1].
	if mouseProportion < 0 {
		mouseProportion = 0
	} else if mouseProportion > 1 {
		mouseProportion = 1
	}
	stepUnderMouse := viewMin + mouseProportion*viewRange

	// Calculate new range
	var newRange float64
	if direction == "in" {
		newRange = viewRange * (1 - defaultZoomFactor)
	} else {
		newRange = viewRange * (1 + defaultZoomFactor)
	}

	// Clamp zoom levels
	if newRange < minZoomRange {
		newRange = minZoomRange
	}
	// Don't allow ranges larger than the domain
	if newRange > c.MaxX()-c.MinX() {
		newRange = c.MaxX() - c.MinX()
	}

	// Calculate new bounds keeping mouse position stable
	newMin := stepUnderMouse - newRange*mouseProportion
	newMax := stepUnderMouse + newRange*(1-mouseProportion)

	// Only apply tail nudge when zooming in AND mouse is at the far right
	if direction == "in" && mouseProportion >= tailAnchorMouseThreshold && isFinite(c.xMax) {
		// Check if we're losing the tail
		rightPad := c.pixelEpsX(newRange) * 2 // Small padding for the last data point
		if newMax < c.xMax-rightPad {
			// Adjust to include the tail
			shift := (c.xMax + rightPad) - newMax
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

// Draw renders the line chart using Braille patterns.
func (c *EpochLineChart) Draw() {
	c.Clear()
	c.DrawXYAxisAndLabel()

	// Nothing to draw?
	if c.GraphWidth() <= 0 || c.GraphHeight() <= 0 {
		c.dirty = false
		return
	}
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

	// Convert visible data points to canvas coordinates.
	points := make([]canvas.Float64Point, 0, ub-lb)
	for i := lb; i < ub; i++ {
		x := (c.xData[i] - c.ViewMinX()) * xScale
		y := (c.yData[i] - c.ViewMinY()) * yScale

		if x >= 0 && x <= float64(c.GraphWidth()) && y >= 0 && y <= float64(c.GraphHeight()) {
			points = append(points, canvas.Float64Point{X: x, Y: y})
		}
	}

	// Draw single point or lines between consecutive points.
	if len(points) == 1 {
		gp := bGrid.GridPoint(points[0])
		bGrid.Set(gp)
	} else {
		for i := 0; i < len(points)-1; i++ {
			gp1 := bGrid.GridPoint(points[i])
			gp2 := bGrid.GridPoint(points[i+1])
			drawLine(bGrid, gp1, gp2)
		}
	}

	// Render braille patterns.
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
	dx := int(math.Abs(float64(p2.X - p1.X)))
	dy := int(math.Abs(float64(p2.Y - p1.Y)))

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

// DrawIfNeeded only draws if the chart is marked as dirty.
func (c *EpochLineChart) DrawIfNeeded() {
	if c.dirty {
		c.Draw()
	}
}

// Title returns the chart title.
func (c *EpochLineChart) Title() string {
	return c.title
}

// SetFocused sets the focused state.
func (c *EpochLineChart) SetFocused(focused bool) {
	c.focused = focused
}

// Resize updates the chart dimensions.
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

// TruncateTitle truncates a title to fit within maxWidth, adding ellipsis if needed.
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

	// Find the best truncation point.
	bestTruncateAt := 0
	for i := range title {
		if lipgloss.Width(title[:i]) > availableWidth {
			break
		}
		bestTruncateAt = i
	}

	// If we have a reasonable amount of text, look for a separator.
	if bestTruncateAt > availableWidth/2 {
		// Look for a separator near the truncation point for cleaner break
		for _, sep := range separators {
			if idx := strings.LastIndex(title[:bestTruncateAt], sep); idx > bestTruncateAt*2/3 {
				// Found a good separator position.
				bestTruncateAt = idx + len(sep)
				break
			}
		}
	}

	// Safety checks.
	if bestTruncateAt <= 0 {
		bestTruncateAt = 1
	}
	if bestTruncateAt > len(title) {
		bestTruncateAt = len(title)
	}

	return title[:bestTruncateAt] + "..."
}
