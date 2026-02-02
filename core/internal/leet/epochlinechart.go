package leet

import (
	"fmt"
	"hash/fnv"
	"math"
	"slices"
	"sort"
	"strings"
	"sync/atomic"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/canvas/runes"
	"github.com/NimbleMarkets/ntcharts/linechart"
	"github.com/charmbracelet/lipgloss"
	lru "github.com/hashicorp/golang-lru"
)

const (
	defaultZoomFactor        = 0.10
	minZoomRange             = 5.0
	tailAnchorMouseThreshold = 0.95
	defaultMaxX              = 20
	defaultMaxY              = 1

	// Minimal canvas size for parked charts.
	parkedCanvasSize = 1

	initDataSliceCap = 256
)

var cache, _ = lru.New(128)

func mapStringToIndex(s string, sliceLen int) int {
	if sliceLen <= 0 {
		return 0
	}
	if sum, ok := cache.Get(s); ok {
		return int(sum.(uint32) % uint32(sliceLen))
	}

	h := fnv.New32a()
	_, _ = h.Write([]byte(s))
	sum := h.Sum32()

	cache.Add(s, sum)
	return int(sum % uint32(sliceLen))
}

// Series stores the raw samples in arrival order.
//
// Series is not safe for concurrent use. Callers must synchronize access
// externally (e.g., via the owning EpochLineChart or grid-level locks).
type Series struct {
	// X and Y hold the raw data points. X is typically `_step` (monotonic,
	// non-decreasing), enabling efficient binary search during rendering.
	MetricData

	// style is the foreground style used to render the series line/dots.
	// Stored atomically because Draw may run concurrently with style updates.
	style atomic.Value // stores lipgloss.Style

	// Precomputed bounds for O(1) chart-level aggregation.
	// Updated incrementally by updateBounds.
	xMin, xMax float64
	yMin, yMax float64
}

func NewSeries(name string, palette []lipgloss.AdaptiveColor) *Series {
	md := MetricData{
		X: make([]float64, 0, initDataSliceCap),
		Y: make([]float64, 0, initDataSliceCap),
	}

	s := Series{
		MetricData: md,
		xMin:       math.Inf(1),
		xMax:       math.Inf(-1),
		yMin:       math.Inf(1),
		yMax:       math.Inf(-1),
	}

	if len(palette) == 0 {
		palette = GraphColors(DefaultColorScheme)
	}
	// Stable mapping for consistent colors across sessions.
	i := mapStringToIndex(name, len(palette))
	graphStyle := lipgloss.NewStyle().Foreground(palette[i])
	s.style.Store(graphStyle)

	return &s
}

// updateBounds extends the series bounds with the given data batch.
func (s *Series) updateBounds(xs, ys []float64) {
	if len(xs) == 0 || len(ys) == 0 {
		return
	}

	xMin, xMax := slices.Min(xs), slices.Max(xs)
	yMin, yMax := slices.Min(ys), slices.Max(ys)

	s.xMin = min(s.xMin, xMin)
	s.xMax = max(s.xMax, xMax)
	s.yMin = min(s.yMin, yMin)
	s.yMax = max(s.yMax, yMax)
}

// Bounds returns the series' precomputed bounds.
func (s *Series) Bounds() (xMin, xMax, yMin, yMax float64) {
	return s.xMin, s.xMax, s.yMin, s.yMax
}

// EpochLineChart is a line chart for epoch/step-based ML training data.
//
// It supports multiple series rendered with opaque compositing (painter's
// algorithm), where the last series in draw order appears on top.
//
// EpochLineChart is generally NOT safe for concurrent use.
// Draw may be called concurrently with style updates (SetGraphStyle, SetPalette)
// because styles use atomic.Value. External synchronization (e.g., grid-level
// mutex) is required for all other concurrent access patterns.
type EpochLineChart struct {
	// Model is the embedded ntcharts line chart backend providing canvas,
	// axes, coordinate transforms, and range management.
	linechart.Model

	// data maps series keys to their data.
	data map[string]*Series

	// order defines the draw order: series are rendered in slice order,
	// so the last element appears visually on top.
	order []string

	// palette provides colors for new series added to this chart.
	palette []lipgloss.AdaptiveColor

	// focused indicates whether this chart has input focus in the grid.
	focused bool

	// title is the metric name shown in the chart header.
	title string

	// dirty marks the chart as needing a redraw on the next DrawIfNeeded call.
	dirty bool

	// isZoomed is set after user adjusts the X view via HandleZoom.
	// When true, updateRanges preserves the user's X view instead of auto-fitting.
	isZoomed bool

	// userViewMinX/userViewMaxX preserve the user's zoom selection across
	// data updates when isZoomed is true.
	userViewMinX, userViewMaxX float64

	// xMin/xMax are the observed X bounds across all series.
	// Used for axis domain and zoom clamping.
	xMin, xMax float64

	// yMin/yMax are the observed Y bounds across all series.
	// Used to compute padded Y axis ranges.
	yMin, yMax float64

	// inspection holds crosshair overlay state for data inspection mode.
	inspection ChartInspection
}

func NewEpochLineChart(title string) *EpochLineChart {
	chart := &EpochLineChart{
		Model: linechart.New(parkedCanvasSize, parkedCanvasSize, 0, defaultMaxX, 0, defaultMaxY,
			linechart.WithXYSteps(4, 5), // The default number of ticks when drawing axis values.
			linechart.WithAutoXRange(),
		),
		data:    make(map[string]*Series),
		title:   title,
		palette: GraphColors(DefaultColorScheme),
		xMin:    math.Inf(1),
		xMax:    math.Inf(-1),
		yMin:    math.Inf(1),
		yMax:    math.Inf(-1),
	}
	chart.AxisStyle = axisStyle
	chart.LabelStyle = labelStyle

	chart.XLabelFormatter = func(_ int, v float64) string {
		return FormatXAxisTick(v, chart.maxXLabelWidth())
	}
	chart.YLabelFormatter = func(_ int, v float64) string {
		return UnitScalar.Format(v)
	}

	return chart
}

// topSeries returns the topmost series (last in draw order), or nil if empty.
// The topmost series is used for inspection snapping and data point queries.
func (c *EpochLineChart) topSeries() *Series {
	if len(c.order) == 0 {
		return nil
	}
	return c.data[c.order[len(c.order)-1]]
}

// maxXLabelWidth computes maximum X axis label width based on available space.
func (c *EpochLineChart) maxXLabelWidth() int {
	w := c.GraphWidth()
	if w <= 0 {
		return 0
	}

	// Approx spacing between ticks. With XSteps=N there are typically N intervals.
	per := w / c.XStep()
	if per > 1 {
		per-- // leave one column slack so labels collide less often
	}
	if per < 1 {
		return 1
	}
	return per
}

// SetPalette updates the color palette for new series.
// Existing series retain their current colors.
func (c *EpochLineChart) SetPalette(colors []lipgloss.AdaptiveColor) {
	if len(colors) == 0 {
		colors = GraphColors(DefaultColorScheme)
	}
	c.palette = colors
}

// AddData appends (x, y) points to the named series, creating it if needed.
//
// X values should be appended in non-decreasing order for efficient rendering.
// Empty data is a no-op.
func (c *EpochLineChart) AddData(key string, data MetricData) {
	s, ok := c.data[key]
	if !ok {
		s = NewSeries(key, c.palette)
		c.data[key] = s
		c.order = append(c.order, key)
	}

	if len(data.X) == 0 || len(data.Y) == 0 {
		return
	}

	// Amortized linear growth. Do not use slices.Concat as it causes
	// O(n^2) allocations that blow up memory footprint.
	s.X = append(s.X, data.X...)
	s.Y = append(s.Y, data.Y...)

	// Update series-level bounds and extend chart-level bounds.
	s.updateBounds(data.X, data.Y)
	sxMin, sxMax, syMin, syMax := s.Bounds()
	c.xMin = min(c.xMin, sxMin)
	c.xMax = max(c.xMax, sxMax)
	c.yMin = min(c.yMin, syMin)
	c.yMax = max(c.yMax, syMax)

	c.updateRanges()
	c.dirty = true
}

// updateRanges recomputes axis ranges from current bounds.
func (c *EpochLineChart) updateRanges() {
	if c.SeriesCount() == 0 {
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

	// X domain: round up to a "nice" value for axis display.
	dataXMin := c.xMin
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

	c.SetYRange(newYMin, newYMax)
	c.SetViewYRange(newYMin, newYMax)

	// Always ensure X range covers the nice domain; only alter view if not zoomed.
	c.SetXRange(dataXMin, niceMax)
	if !c.isZoomed {
		viewMin := c.xMin
		if !isFinite(viewMin) {
			viewMin = 0
		}
		c.SetViewXRange(viewMin, niceMax)
	}

	c.SetXYRange(c.MinX(), c.MaxX(), newYMin, newYMax)

	// Keep inspection overlay consistent if the view/domain changed.
	if c.inspection.Active {
		c.refreshInspectionAfterViewChange()
	}
}

// calculatePadding determines appropriate padding for the Y axis.
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

	mouseProportion := float64(mouseX) / float64(c.GraphWidth())
	mouseProportion = max(0, min(1, mouseProportion))
	stepUnderMouse := viewMin + mouseProportion*viewRange

	var newRange float64
	if direction == "in" {
		newRange = viewRange * (1 - defaultZoomFactor)
	} else {
		newRange = viewRange * (1 + defaultZoomFactor)
	}

	newRange = max(minZoomRange, min(newRange, c.MaxX()-c.MinX()))

	newMin := stepUnderMouse - newRange*mouseProportion
	newMax := stepUnderMouse + newRange*(1-mouseProportion)

	// Tail anchor: when zooming in at far right, keep the data tail visible.
	if direction == "in" && mouseProportion >= tailAnchorMouseThreshold && isFinite(c.xMax) {
		rightPad := c.pixelEpsX(newRange) * 2
		if newMax < c.xMax-rightPad {
			shift := (c.xMax + rightPad) - newMax
			newMin += shift
			newMax += shift
		}
	}

	// Clamp to domain.
	domMin, domMax := c.MinX(), c.MaxX()
	if newMin < domMin {
		newMin = domMin
		newMax = min(newMin+newRange, domMax)
	}
	if newMax > domMax {
		newMax = domMax
		newMin = max(newMax-newRange, domMin)
	}

	c.SetViewXRange(newMin, newMax)
	c.userViewMinX = newMin
	c.userViewMaxX = newMax
	c.isZoomed = true
	c.dirty = true
}

// Draw renders all series using Braille patterns.
func (c *EpochLineChart) Draw() {
	c.Clear()
	c.DrawXYAxisAndLabel()

	if c.GraphWidth() <= 0 || c.GraphHeight() <= 0 {
		c.dirty = false
		return
	}

	startX := 0
	if c.YStep() > 0 {
		startX = c.Origin().X + 1
	}

	for _, key := range c.order {
		c.drawSeries(c.data[key], startX)
	}

	c.drawInspectionOverlay(startX)
	c.dirty = false
}

// drawSeries renders a single series onto the canvas.
func (c *EpochLineChart) drawSeries(s *Series, startX int) {
	if len(s.X) == 0 {
		return
	}

	// Binary search for visible window.
	lb := sort.Search(len(s.X), func(i int) bool { return s.X[i] >= c.ViewMinX() })
	eps := c.pixelEpsX(c.ViewMaxX() - c.ViewMinX())
	ub := sort.Search(len(s.X), func(i int) bool { return s.X[i] > c.ViewMaxX()+eps })

	if ub <= lb {
		return
	}

	bGrid := graph.NewBrailleGrid(
		c.GraphWidth(),
		c.GraphHeight(),
		0, float64(c.GraphWidth()),
		0, float64(c.GraphHeight()),
	)

	xScale := float64(c.GraphWidth()) / (c.ViewMaxX() - c.ViewMinX())
	yScale := float64(c.GraphHeight()) / (c.ViewMaxY() - c.ViewMinY())

	// Convert visible data points to canvas coordinates.
	points := make([]canvas.Float64Point, 0, ub-lb)
	for i := lb; i < ub; i++ {
		x := (s.X[i] - c.ViewMinX()) * xScale
		y := (s.Y[i] - c.ViewMinY()) * yScale

		if x >= 0 && x <= float64(c.GraphWidth()) && y >= 0 && y <= float64(c.GraphHeight()) {
			points = append(points, canvas.Float64Point{X: x, Y: y})
		}
	}

	if len(points) == 1 {
		bGrid.Set(bGrid.GridPoint(points[0]))
	} else {
		for i := range len(points) - 1 {
			gp1 := bGrid.GridPoint(points[i])
			gp2 := bGrid.GridPoint(points[i+1])
			drawLine(bGrid, gp1, gp2)
		}
	}

	patterns := bGrid.BraillePatterns()
	style := s.style.Load().(lipgloss.Style)

	drawBraillePatternsOccluded(&c.Canvas, canvas.Point{X: startX, Y: 0}, patterns, &style)
}

// drawBraillePatternsOccluded draws braille runes with opaque compositing.
//
// Unlike ntcharts' graph.DrawBraillePatterns which merges patterns, this
// replaces existing cells entirely. This prevents color "spilling" when
// multiple series overlap.
func drawBraillePatternsOccluded(m *canvas.Model, p canvas.Point, b [][]rune, s *lipgloss.Style) {
	for y, row := range b {
		for x, r := range row {
			if r != runes.BrailleBlockOffset {
				drawBrailleRune(m, p.Add(canvas.Point{X: x, Y: y}), r, s)
			}
		}
	}
}

// drawBrailleRune draws a single braille rune, replacing any existing content.
func drawBrailleRune(m *canvas.Model, p canvas.Point, r rune, s *lipgloss.Style) {
	if r == runes.Null || !runes.IsBraillePattern(r) {
		return
	}
	m.SetCell(p, canvas.NewCellWithStyle(r, *s))
}

// drawInspectionOverlay renders the data inspection legend.
func (c *EpochLineChart) drawInspectionOverlay(graphStartX int) {
	if !c.inspection.Active || c.GraphWidth() <= 0 || c.GraphHeight() <= 0 {
		return
	}

	// Hairline X in canvas coordinates.
	canvasX := graphStartX + c.inspection.MouseX

	// Vertical hairline.
	for y := 0; y < c.GraphHeight(); y++ {
		c.Canvas.SetCell(
			canvas.Point{X: canvasX, Y: y},
			canvas.NewCellWithStyle(boxLightVertical, inspectionLineStyle),
		)
	}

	// We anchor inspection at a single data X and show values for all series at that X.
	anchorX := c.inspection.DataX
	if !isFinite(anchorX) || len(c.order) == 0 {
		return
	}

	type legendEntry struct {
		labelRunes []rune
		blockRunes []rune
		blockStyle lipgloss.Style
	}

	blockRunes := []rune("▬▬")
	entries := make([]legendEntry, 0, len(c.order))
	maxLabelWidth := 0

	// Build entries in render order: topmost series first (last in c.order).
	for i := len(c.order) - 1; i >= 0; i-- {
		key := c.order[i]
		s, ok := c.data[key]
		if !ok || len(s.X) == 0 {
			continue
		}

		idx := nearestIndexForX(s.X, anchorX)
		if idx < 0 || idx >= len(s.Y) {
			continue
		}

		yVal := s.Y[idx]
		label := fmt.Sprintf("%v: %v", s.X[idx], formatSigFigs(yVal, 4))
		labelRunes := []rune(label)
		if lw := len(labelRunes); lw > maxLabelWidth {
			maxLabelWidth = lw
		}

		seriesStyle := s.style.Load().(lipgloss.Style)
		blockStyle := seriesStyle.Inherit(inspectionLegendStyle)

		entries = append(entries, legendEntry{
			labelRunes: labelRunes,
			blockRunes: blockRunes,
			blockStyle: blockStyle,
		})
	}

	if len(entries) == 0 {
		return
	}

	// Don't draw more legend rows than we have vertical space for.
	if len(entries) > c.GraphHeight() {
		entries = entries[:c.GraphHeight()]
	}

	totalLegendWidth := len(blockRunes) + 1 + maxLabelWidth // blocks + space + label
	rightBound := graphStartX + c.GraphWidth()

	// Prefer placing the legend to the right of the hairline if it fits.
	legendX := canvasX + 1
	if legendX+totalLegendWidth >= rightBound {
		legendX = canvasX - 1 - totalLegendWidth
	}
	if legendX < graphStartX {
		legendX = graphStartX
	}

	// Vertically center the block of legend rows within the graph.
	legendHeight := len(entries)
	legendYStart := max(c.GraphHeight()/2-legendHeight/2, 0)
	if legendYStart+legendHeight > c.GraphHeight() {
		legendYStart = max(c.GraphHeight()-legendHeight, 0)
	}

	// Render each legend row: colored block(s) + space + "X: Y".
	for i := range len(entries) {
		entry := entries[i] // avoids copying 600 bytes on each iteration
		y := legendYStart + i
		x := legendX

		// Colored block (tied to series color).
		for _, r := range entry.blockRunes {
			c.Canvas.SetCell(
				canvas.Point{X: x, Y: y},
				canvas.NewCellWithStyle(r, entry.blockStyle),
			)
			x++
		}

		c.Canvas.SetCell(
			canvas.Point{X: x, Y: y},
			canvas.NewCellWithStyle(' ', inspectionLegendStyle),
		)
		x++

		for _, ch := range entry.labelRunes {
			c.Canvas.SetCell(
				canvas.Point{X: x, Y: y},
				canvas.NewCellWithStyle(ch, inspectionLegendStyle),
			)
			x++
		}
	}
}

// findNearestDataPoint returns the data point nearest to mouseX in the topmost series.
func (c *EpochLineChart) findNearestDataPoint(mouseX int) (dataX, dataY float64, idx int, ok bool) {
	s := c.topSeries()
	if s == nil || len(s.X) == 0 || c.GraphWidth() <= 0 {
		return 0, 0, -1, false
	}

	xRange := c.ViewMaxX() - c.ViewMinX()
	if xRange <= 0 {
		return 0, 0, -1, false
	}

	targetX := c.ViewMinX() + (float64(mouseX)/float64(c.GraphWidth()))*xRange
	bestIdx := nearestIndexForX(s.X, targetX)
	if bestIdx < 0 {
		return 0, 0, -1, false
	}

	return s.X[bestIdx], s.Y[bestIdx], bestIdx, true
}

// pixelEpsX returns approximately 1 horizontal pixel in X data units.
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

// DrawIfNeeded draws only if the chart is marked dirty.
func (c *EpochLineChart) DrawIfNeeded() {
	if c.dirty {
		c.Draw()
	}
}

// Title returns the chart title.
func (c *EpochLineChart) Title() string {
	return c.title
}

// SetFocused sets the chart's focus state.
func (c *EpochLineChart) SetFocused(focused bool) {
	c.focused = focused
}

// Resize updates the chart's canvas dimensions.
func (c *EpochLineChart) Resize(width, height int) {
	if c.Width() == width && c.Height() == height {
		return
	}
	c.Model.Resize(width, height)
	c.updateRanges()
	c.dirty = true
}

// Park minimizes canvas memory for off-screen charts.
func (c *EpochLineChart) Park() {
	c.Resize(parkedCanvasSize, parkedCanvasSize)
}

func isFinite(f float64) bool {
	return !math.IsNaN(f) && !math.IsInf(f, 0)
}

// TruncateTitle truncates a title to fit maxWidth, adding ellipsis if needed.
func TruncateTitle(title string, maxWidth int) string {
	if lipgloss.Width(title) <= maxWidth {
		return title
	}
	if maxWidth <= 3 {
		return "..."
	}

	availableWidth := maxWidth - 3

	// Try to break at a separator for cleaner truncation
	separators := []string{"/", "_", ".", "-", ":"}

	bestTruncateAt := 0
	for i := range title {
		if lipgloss.Width(title[:i]) > availableWidth {
			break
		}
		bestTruncateAt = i
	}

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

	if bestTruncateAt <= 0 {
		bestTruncateAt = 1
	}
	if bestTruncateAt > len(title) {
		bestTruncateAt = len(title)
	}

	return title[:bestTruncateAt] + "..."
}

// SetGraphStyle sets the style for the topmost series.
func (c *EpochLineChart) SetGraphStyle(s *lipgloss.Style) {
	if top := c.topSeries(); top != nil {
		top.style.Store(*s)
	}
}

// SeriesCount returns the number of series in the chart.
func (c *EpochLineChart) SeriesCount() int {
	return len(c.data)
}

// RemoveSeries removes a series by key and recomputes bounds.
func (c *EpochLineChart) RemoveSeries(key string) {
	if _, ok := c.data[key]; !ok {
		return
	}
	delete(c.data, key)

	for i, k := range c.order {
		if k == key {
			c.order = slices.Delete(c.order, i, i+1)
			break
		}
	}

	c.recomputeBounds()
	c.updateRanges()
	c.dirty = true
}

// recomputeBounds aggregates bounds from all series.
// O(n) in number of series, not data points.
func (c *EpochLineChart) recomputeBounds() {
	c.xMin = math.Inf(1)
	c.xMax = math.Inf(-1)
	c.yMin = math.Inf(1)
	c.yMax = math.Inf(-1)

	for _, s := range c.data {
		if len(s.X) == 0 || len(s.Y) == 0 {
			continue
		}
		xMin, xMax, yMin, yMax := s.Bounds()
		c.xMin = min(c.xMin, xMin)
		c.xMax = max(c.xMax, xMax)
		c.yMin = min(c.yMin, yMin)
		c.yMax = max(c.yMax, yMax)
	}
}

// ChartInspection holds crosshair overlay state.
type ChartInspection struct {
	// Active indicates whether inspection mode is on.
	Active bool
	// MouseX is the vertical crosshair position in graph-local pixels.
	MouseX int
	// DataX, DataY are coordinates of the nearest data sample.
	DataX, DataY float64
}

// nearestIndexForX returns the index closest to targetX in a sorted slice.
// Returns -1 if xs is empty.
func nearestIndexForX(xs []float64, targetX float64) int {
	if len(xs) == 0 {
		return -1
	}
	j := sort.SearchFloat64s(xs, targetX)

	bestIdx := -1
	bestDist := math.Inf(1)
	for _, i := range []int{j - 1, j, j + 1} {
		if i < 0 || i >= len(xs) {
			continue
		}
		if d := math.Abs(xs[i] - targetX); d < bestDist {
			bestDist, bestIdx = d, i
		}
	}
	return bestIdx
}

// snapInspectionToDataX snaps the crosshair to the nearest sample.
func (c *EpochLineChart) snapInspectionToDataX(targetX float64) {
	s := c.topSeries()
	if s == nil || !c.inspection.Active || c.GraphWidth() <= 0 || len(s.X) == 0 {
		return
	}

	xRange := c.ViewMaxX() - c.ViewMinX()
	if xRange <= 0 {
		return
	}

	idx := nearestIndexForX(s.X, targetX)
	if idx < 0 {
		return
	}

	c.inspection.DataX = s.X[idx]
	c.inspection.DataY = s.Y[idx]

	// Pixel snap to the exact dataX under current view.
	mouseXFrac := (c.inspection.DataX - c.ViewMinX()) / xRange
	mouseX := int(math.Round(mouseXFrac * float64(c.GraphWidth())))
	c.inspection.MouseX = max(0, min(c.GraphWidth()-1, mouseX))
	c.dirty = true
}

// InspectAtDataX activates inspection at the sample nearest to targetX.
func (c *EpochLineChart) InspectAtDataX(targetX float64) {
	s := c.topSeries()
	if s == nil || len(s.X) == 0 || c.GraphWidth() <= 0 {
		return
	}
	c.inspection.Active = true
	c.snapInspectionToDataX(targetX)
}

// refreshInspectionAfterViewChange keeps the crosshair on the same DataX
// after view/domain changes.
func (c *EpochLineChart) refreshInspectionAfterViewChange() {
	if !c.inspection.Active {
		return
	}
	c.snapInspectionToDataX(c.inspection.DataX)
}

// StartInspection begins inspection at the given mouse X position.
func (c *EpochLineChart) StartInspection(mouseX int) {
	s := c.topSeries()
	if s == nil || len(s.X) == 0 || c.GraphWidth() <= 0 {
		return
	}
	c.inspection.Active = true
	c.UpdateInspection(mouseX)
}

// UpdateInspection moves the crosshair to a new mouse X position.
func (c *EpochLineChart) UpdateInspection(mouseX int) {
	if !c.inspection.Active || c.GraphWidth() <= 0 {
		return
	}
	// Clamp to the drawable graph area.
	c.inspection.MouseX = max(0, min(c.GraphWidth()-1, mouseX))

	if dataX, _, _, ok := c.findNearestDataPoint(mouseX); ok {
		c.snapInspectionToDataX(dataX)
	}
	c.dirty = true
}

// EndInspection exits inspection mode.
func (c *EpochLineChart) EndInspection() {
	c.inspection = ChartInspection{}
	c.dirty = true
}

// IsInspecting reports whether inspection is active.
func (c *EpochLineChart) IsInspecting() bool {
	return c.inspection.Active
}

// InspectionData returns the inspected point's coordinates.
func (c *EpochLineChart) InspectionData() (x, y float64, active bool) {
	return c.inspection.DataX, c.inspection.DataY, c.inspection.Active
}

// PromoteSeriesToTop moves a series to the end of draw order (visually on top).
func (c *EpochLineChart) PromoteSeriesToTop(key string) {
	if key == "" || len(c.order) == 0 {
		return
	}

	idx := slices.Index(c.order, key)
	if idx == -1 || idx == len(c.order)-1 {
		return
	}

	c.order = slices.Delete(c.order, idx, idx+1)
	c.order = append(c.order, key)
	c.dirty = true
}

// DrawOrder returns the series keys in their current draw order.
// Series are rendered in this order; the last appears on top.
func (c *EpochLineChart) DrawOrder() []string {
	return slices.Clone(c.order)
}
