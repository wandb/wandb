// ntcharts - Copyright (c) 2024 Neomantra Corp.

// Package linechart implements a canvas that displays
// (X,Y) Cartesian coordinates as a line chart.
package linechart

import (
	"fmt"
	"math"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/canvas/runes"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	zone "github.com/lrstanley/bubblezone"
)

var defaultStyle = lipgloss.NewStyle()

// LabelFormatter converts a float64 into text
// for displaying the X and Y axis labels
// given an index of label and numeric value
// Index increments from minimum value to maximum values.
type LabelFormatter func(int, float64) string

// DefaultLabelFormatter returns a LabelFormatter
// that convert float64 to integers
func DefaultLabelFormatter() LabelFormatter {
	return func(i int, v float64) string {
		return fmt.Sprintf("%.0f", v)
	}
}

// Model contains state of a linechart with an embedded canvas.Model
type Model struct {
	UpdateHandler   UpdateHandler
	Canvas          canvas.Model
	Style           lipgloss.Style // style applied when drawing runes
	AxisStyle       lipgloss.Style // style applied when drawing X and Y axes
	LabelStyle      lipgloss.Style // style applied when drawing X and Y number value
	XLabelFormatter LabelFormatter // convert to X number values display string
	YLabelFormatter LabelFormatter // convert to Y number values display string
	xStep           int            // number of steps when displaying X axis values
	yStep           int            // number of steps when displaying Y axis values
	focus           bool

	// the expected min and max values
	minX float64
	maxX float64
	minY float64
	maxY float64

	// current min and max axes values to display
	viewMinX float64
	viewMaxX float64
	viewMinY float64
	viewMaxY float64

	// whether to automatically set expected values
	// when a value appears beyond the existing bounds
	AutoMinX bool
	AutoMaxX bool
	AutoMinY bool
	AutoMaxY bool

	origin      canvas.Point // start of X and Y axes lines on canvas for graphing area
	graphWidth  int          // width of graphing area - excludes X axis and labels
	graphHeight int          // height of graphing area - excludes Y axis and labels

	zoneManager *zone.Manager // provides mouse functionality
	zoneID      string
}

// New returns a linechart Model initialized with given width, height,
// expected data value ranges and various options.
// Width and height includes area used for chart labeling.
// If xStep is 0, then will not draw X axis or values below X axis.
// If yStep is 0, then will not draw Y axis or values left of Y axis.
func New(w, h int, minX, maxX, minY, maxY float64, opts ...Option) Model {
	m := Model{
		UpdateHandler:   XYAxesUpdateHandler(1, 1),
		Canvas:          canvas.New(w, h),
		Style:           defaultStyle,
		AxisStyle:       defaultStyle,
		LabelStyle:      defaultStyle,
		XLabelFormatter: DefaultLabelFormatter(),
		YLabelFormatter: DefaultLabelFormatter(),
		yStep:           2,
		xStep:           2,
		minX:            minX,
		maxX:            maxX,
		minY:            minY,
		maxY:            maxY,
		viewMinX:        minX,
		viewMaxX:        maxX,
		viewMinY:        minY,
		viewMaxY:        maxY,
	}
	for _, opt := range opts {
		opt(&m)
	}
	m.UpdateGraphSizes()
	return m
}

// getGraphSizeAndOrigin calculates and returns the linechart origin and graph width and height
func getGraphSizeAndOrigin(w, h int, minY, maxY float64, xStep, yStep int, yFmter LabelFormatter) (canvas.Point, int, int) {
	// graph width and height exclude area used by axes
	// origin point is canvas coordinates of where axes are drawn
	origin := canvas.Point{X: 0, Y: h - 1}
	gWidth := w
	gHeight := h
	if xStep > 0 {
		// use last 2 rows of canvas to plot X axis and tick values
		origin.Y -= 1
		gHeight -= 2
	}
	if yStep > 0 {
		// find out how many spaces left of the Y axis
		// to reserve for axis tick value by checking the string length
		// of all values to be displayed
		var lastVal string
		valueLen := 0
		rangeSz := maxY - minY // range of possible expected values
		increment := rangeSz / float64(gHeight)
		for i := 0; i <= gHeight; {
			v := minY + (increment * float64(i)) // value to set left of Y axis
			s := yFmter(i, v)
			if lastVal != s {
				if len(s) > valueLen {
					valueLen = len(s)
				}
				lastVal = s
			}
			i += yStep
		}
		origin.X += valueLen
		gWidth -= (valueLen + 1) // ignore Y axis and tick values
	}
	return origin, gWidth, gHeight
}

// UpdateGraphSizes updates the Model origin, graph width and graph height.
// This method is should be called whenever the X and Y axes values have changed,
// for example when X and Y ranges have been adjusted by AutoAdjustRange().
func (m *Model) UpdateGraphSizes() {
	origin, gWidth, gHeight := getGraphSizeAndOrigin(
		m.Canvas.Width(),
		m.Canvas.Height(),
		m.viewMinY,
		m.viewMaxY,
		m.xStep,
		m.yStep,
		m.YLabelFormatter,
	)
	m.origin = origin
	m.graphWidth = gWidth
	m.graphHeight = gHeight
}

// Width returns linechart width.
func (m *Model) Width() int {
	return m.Canvas.Width()
}

// Height returns linechart height.
func (m *Model) Height() int {
	return m.Canvas.Height()
}

// GraphWidth returns linechart graphing area width.
func (m *Model) GraphWidth() int {
	return m.graphWidth
}

// GraphHeight returns linechart graphing area height.
func (m *Model) GraphHeight() int {
	return m.graphHeight
}

// MinX returns linechart expected minimum X value.
func (m *Model) MinX() float64 {
	return m.minX
}

// MaxX returns linechart expected maximum X value.
func (m *Model) MaxX() float64 {
	return m.maxX
}

// MinY returns linechart expected minimum Y value.
func (m *Model) MinY() float64 {
	return m.minY
}

// MaxY returns linechart expected maximum Y value.
func (m *Model) MaxY() float64 {
	return m.maxY
}

// ViewMinX returns linechart displayed minimum X value.
func (m *Model) ViewMinX() float64 {
	return m.viewMinX
}

// ViewMaxX returns linechart displayed maximum X value.
func (m *Model) ViewMaxX() float64 {
	return m.viewMaxX
}

// ViewMinY returns linechart displayed minimum Y value.
func (m *Model) ViewMinY() float64 {
	return m.viewMinY
}

// ViewMaxY returns linechart displayed maximum Y value.
func (m *Model) ViewMaxY() float64 {
	return m.viewMaxY
}

// XStep returns number of steps when displaying Y axis values.
func (m *Model) XStep() int {
	return m.xStep
}

// XStep returns number of steps when displaying Y axis values.
func (m *Model) YStep() int {
	return m.yStep
}

// Origin returns a canvas Point with the coordinates
// of the linechart graph (X,Y) origin.
func (m *Model) Origin() canvas.Point {
	return m.origin
}

// Clear will reset linechart canvas including axes and labels.
func (m *Model) Clear() {
	m.Canvas.Clear()
}

// SetXStep updates the number of steps when displaying X axis values.
func (m *Model) SetXStep(xStep int) {
	m.xStep = xStep
	m.UpdateGraphSizes()
}

// SetYStep updates the number of steps when displaying Y axis values.
func (m *Model) SetYStep(yStep int) {
	m.yStep = yStep
	m.UpdateGraphSizes()
}

// SetXRange updates the minimum and maximum expected X values.
func (m *Model) SetXRange(min, max float64) {
	m.minX = min
	m.maxX = max
}

// SetYRange updates the minimum and maximum expected Y values.
func (m *Model) SetYRange(min, max float64) {
	m.minY = min
	m.maxY = max
}

// SetXYRange updates the minimum and maximum expected X and Y values.
func (m *Model) SetXYRange(minX, maxX, minY, maxY float64) {
	m.SetXRange(minX, maxX)
	m.SetYRange(minY, maxY)
}

// SetXRange updates the displayed minimum and maximum X values.
// Minimum and maximum values will be bounded by the expected X values.
// Returns whether not displayed X values have updated.
func (m *Model) SetViewXRange(min, max float64) bool {
	vMin := math.Max(m.minX, min)
	vMax := math.Min(m.maxX, max)
	if vMin < vMax {
		m.viewMinX = vMin
		m.viewMaxX = vMax
		m.UpdateGraphSizes()
		return true
	}
	return false
}

// SetYRange updates the displayed minimum and maximum Y values.
// Minimum and maximum values will be bounded by the expected Y values.
// Returns whether not displayed Y values have updated.
func (m *Model) SetViewYRange(min, max float64) bool {
	vMin := math.Max(m.minY, min)
	vMax := math.Min(m.maxY, max)
	if vMin < vMax {
		m.viewMinY = vMin
		m.viewMaxY = vMax
		m.UpdateGraphSizes()
		return true
	}
	return false
}

// SetViewXYRange updates the displayed minimum and maximum X and Y values.
// Minimum and maximum values will be bounded by the expected values.
func (m *Model) SetViewXYRange(minX, maxX, minY, maxY float64) {
	m.SetViewXRange(minX, maxX)
	m.SetViewYRange(minY, maxY)
}

// Resize will change linechart display width and height.
// Existing runes on the linechart will not be redrawn.
func (m *Model) Resize(w, h int) {
	m.Canvas.Resize(w, h)
	m.Canvas.ViewWidth = w
	m.Canvas.ViewHeight = h
	m.UpdateGraphSizes()
}

// AutoAdjustRange automatically adjusts both the expected X and Y values
// and the displayed X and Y values if enabled and the given Float64Point
// is outside of expected ranges.
// It returns whether or not the display X and Y ranges have been adjusted.
func (m *Model) AutoAdjustRange(f canvas.Float64Point) (b bool) {
	// adjusts both expected range and
	// the display range (if not zoomed in)
	if m.AutoMinX && (f.X < m.minX) {
		if m.minX == m.viewMinX {
			m.viewMinX = f.X
			b = true
		}
		m.minX = f.X
	}
	if m.AutoMaxX && (f.X > m.maxX) {
		if m.maxX == m.viewMaxX {
			m.viewMaxX = f.X
			b = true
		}
		m.maxX = f.X
	}
	if m.AutoMinY && (f.Y < m.minY) {
		if m.minY == m.viewMinY {
			m.viewMinY = f.Y
			b = true
		}
		m.minY = f.Y
	}
	if m.AutoMaxY && (f.Y > m.maxY) {
		if m.maxY == m.viewMaxY {
			m.viewMaxY = f.Y
			b = true
		}
		m.maxY = f.Y
	}
	return
}

// SetZoneManager enables mouse functionality
// by setting a bubblezone.Manager to the linechart.
// The bubblezone.Manager can check bubbletea mouse event Msgs
// passed to the UpdateHandler handler during an Update().
// The root bubbletea model must wrap the View() string with
// bubblezone.Manager.Scan() to enable mouse functionality.
// To disable mouse functionality after enabling, call SetZoneManager on nil.
func (m *Model) SetZoneManager(zm *zone.Manager) {
	m.zoneManager = zm
	if (zm != nil) && (m.zoneID == "") {
		m.zoneID = zm.NewPrefix()
	}
}

// ZoneManager will return linechart zone Manager.
func (m *Model) ZoneManager() *zone.Manager {
	return m.zoneManager
}

// ZoneID will return linechart zone ID used by zone Manager.
func (m *Model) ZoneID() string {
	return m.zoneID
}

// drawYLabel draws Y axis values left of the Y axis every n step.
// Repeating values will be hidden.
// Does nothing if n <= 0.
func (m *Model) drawYLabel(n int) {
	// from origin going up, draw data value left of the Y axis every n steps
	// origin X coordinates already set such that there is space available
	if n <= 0 {
		return
	}
	var lastVal string
	rangeSz := m.viewMaxY - m.viewMinY // range of possible expected values
	increment := rangeSz / float64(m.graphHeight)
	for i := 0; i <= m.graphHeight; {
		v := m.viewMinY + (increment * float64(i)) // value to set left of Y axis
		s := m.YLabelFormatter(i, v)
		if lastVal != s {
			m.Canvas.SetStringWithStyle(canvas.Point{m.origin.X - len(s), m.origin.Y - i}, s, m.LabelStyle)
			lastVal = s
		}
		i += n
	}
}

// drawXLabel draws X axis values below the X axis every n step.
// Repeating values will be hidden.
// Does nothing if n <= 0.
func (m *Model) drawXLabel(n int) {
	// from origin going right, draw data value left of the Y axis every n steps
	if n <= 0 {
		return
	}
	var lastVal string
	rangeSz := m.viewMaxX - m.viewMinX // range of possible expected values
	increment := rangeSz / float64(m.graphWidth)
	for i := 0; i < m.graphWidth; {
		// can only set if rune to the left of target coordinates is empty
		if c := m.Canvas.Cell(canvas.Point{m.origin.X + i - 1, m.origin.Y + 1}); c.Rune == runes.Null {
			v := m.viewMinX + (increment * float64(i)) // value to set under X axis
			s := m.XLabelFormatter(i, v)
			// dont display if number will be cut off or value repeats
			sLen := len(s) + m.origin.X + i
			if (s != lastVal) && (sLen <= m.Canvas.Width()) {
				m.Canvas.SetStringWithStyle(canvas.Point{m.origin.X + i, m.origin.Y + 1}, s, m.LabelStyle)
				lastVal = s
			}
		}
		i += n
	}
}

// DrawXYAxisAndLabel draws the X, Y axes.
func (m *Model) DrawXYAxisAndLabel() {
	drawY := m.yStep > 0
	drawX := m.xStep > 0
	if drawY && drawX {
		graph.DrawXYAxis(&m.Canvas, m.origin, m.AxisStyle)
	} else {
		if drawY { // draw Y axis
			graph.DrawVerticalLineUp(&m.Canvas, m.origin, m.AxisStyle)
		}
		if drawX { // draw X axis
			graph.DrawHorizonalLineRight(&m.Canvas, m.origin, m.AxisStyle)
		}
	}
	m.drawYLabel(m.yStep)
	m.drawXLabel(m.xStep)
}

// scalePoint returns a Float64Point scaled to the graph size
// of the linechart from a Float64Point data point, width and height.
func (m *Model) scalePoint(f canvas.Float64Point, w, h int) (r canvas.Float64Point) {
	dx := m.viewMaxX - m.viewMinX
	dy := m.viewMaxY - m.viewMinY
	if dx > 0 {
		xs := float64(w) / dx
		r.X = (f.X - m.viewMinX) * xs
	}
	if dy > 0 {
		ys := float64(h) / dy
		r.Y = (f.Y - m.viewMinY) * ys
	}
	return
}

// ScaleFloat64Point returns a Float64Point scaled to the graph size
// of the linechart from a Float64Point data point.
func (m *Model) ScaleFloat64Point(f canvas.Float64Point) (r canvas.Float64Point) {
	// Need to use one less width and height, otherwise values rounded to the nearest
	// integer would be would be between 0 to graph width/height,
	// and indexing the full graph width/height would be outside of the canvas
	return m.scalePoint(f, m.graphWidth-1, m.graphHeight-1)
}

// ScaleFloat64PointForLine returns a Float64Point scaled to the graph size
// of the linechart from a Float64Point data point.  Used when drawing line runes
// with line styles that can combine with the axes.
func (m *Model) ScaleFloat64PointForLine(f canvas.Float64Point) (r canvas.Float64Point) {
	// Full graph height and can be used since LineStyle runes
	// can be combined with axes instead of overriding them
	return m.scalePoint(f, m.graphWidth, m.graphHeight)
}

// DrawRune draws the rune on to the linechart
// from a given Float64Point data point.
func (m *Model) DrawRune(f canvas.Float64Point, r rune) {
	m.DrawRuneWithStyle(f, r, m.Style)
}

// DrawRuneWithStyle draws the rune with style on to the linechart
// from a given Float64Point data point.
func (m *Model) DrawRuneWithStyle(f canvas.Float64Point, r rune, s lipgloss.Style) {
	if m.AutoAdjustRange(f) { // auto adjust x and y ranges if enabled
		m.UpdateGraphSizes()
	}
	sf := m.ScaleFloat64Point(f) // scale Cartesian coordinates data point to graphing area
	p := canvas.CanvasPointFromFloat64Point(m.origin, sf)
	// draw rune avoiding the axes
	if m.yStep > 0 {
		p.X++
	}
	if m.xStep > 0 {
		p.Y--
	}
	m.Canvas.SetCell(p, canvas.NewCellWithStyle(r, s))
}

// DrawRuneLine draws the rune on to the linechart
// such that there is an approximate straight line between the two given
// Float64Point data points.
func (m *Model) DrawRuneLine(f1 canvas.Float64Point, f2 canvas.Float64Point, r rune) {
	m.DrawRuneLineWithStyle(f1, f2, r, m.Style)
}

// DrawRuneLineWithStyle draws the rune with style on to the linechart
// such that there is an approximate straight line between the two given
// Float64Point data points.
func (m *Model) DrawRuneLineWithStyle(f1 canvas.Float64Point, f2 canvas.Float64Point, r rune, s lipgloss.Style) {
	// auto adjust x and y ranges if enabled
	r1 := m.AutoAdjustRange(f1)
	r2 := m.AutoAdjustRange(f2)
	if r1 || r2 {
		m.UpdateGraphSizes()
	}

	// scale Cartesian coordinates data point to graphing area
	sf1 := m.ScaleFloat64Point(f1)
	sf2 := m.ScaleFloat64Point(f2)

	// convert scaled points to canvas points
	p1 := canvas.CanvasPointFromFloat64Point(m.origin, sf1)
	p2 := canvas.CanvasPointFromFloat64Point(m.origin, sf2)

	// draw rune on all canvas coordinates between
	// the two canvas points that approximates a line
	points := graph.GetLinePoints(p1, p2)
	for _, p := range points {
		if m.yStep > 0 {
			p.X++
		}
		if m.xStep > 0 {
			p.Y--
		}
		m.Canvas.SetCell(p, canvas.NewCellWithStyle(r, s))
	}
}

// DrawRuneCircle draws the rune on to the linechart
// such that there is an approximate circle of float64 radious around
// the center of a circle at Float64Point data point.
func (m *Model) DrawRuneCircle(c canvas.Float64Point, f float64, r rune) {
	m.DrawRuneCircleWithStyle(c, f, r, m.Style)
}

// DrawRuneCircleWithStyle draws the rune with style on to the linechart
// such that there is an approximate circle of float64 radious around
// the center of a circle at Float64Point data point.
func (m *Model) DrawRuneCircleWithStyle(c canvas.Float64Point, f float64, r rune, s lipgloss.Style) {
	center := canvas.NewPointFromFloat64Point(c) // round center to nearest integers
	radius := int(math.Round(f))                 // round radius to nearest integer

	points := graph.GetCirclePoints(center, radius)
	for _, v := range points {
		np := canvas.NewFloat64PointFromPoint(v)
		// auto adjust x and y ranges if enabled
		if m.AutoAdjustRange(np) {
			m.UpdateGraphSizes()
		}
		// scale Cartesian coordinates data point to graphing area
		sf := m.ScaleFloat64Point(np)
		// convert scaled points to canvas points
		p := canvas.CanvasPointFromFloat64Point(m.origin, sf)
		// draw rune while avoiding drawing outside of graphing area
		// or on the X and Y axes
		ok := (p.X >= m.origin.X) && (p.Y <= m.origin.Y)
		if (m.yStep > 0) && (p.X == m.origin.X) {
			ok = false
		}
		if (m.xStep > 0) && (p.Y == m.origin.Y) {
			ok = false
		}
		if ok {
			m.Canvas.SetCell(p, canvas.NewCellWithStyle(r, s))
		}
	}
}

// DrawLine draws line runes of a given LineStyle on to the linechart
// such that there is an approximate straight line between the two given Float64Point data points.
func (m *Model) DrawLine(f1 canvas.Float64Point, f2 canvas.Float64Point, ls runes.LineStyle) {
	m.DrawLineWithStyle(f1, f2, ls, m.Style)
}

// DrawLineWithStyle draws line runes of a given LineStyle and style on to the linechart
// such that there is an approximate straight line between the two given Float64Point data points.
func (m *Model) DrawLineWithStyle(f1 canvas.Float64Point, f2 canvas.Float64Point, ls runes.LineStyle, s lipgloss.Style) {
	// auto adjust x and y ranges if enabled
	r1 := m.AutoAdjustRange(f1)
	r2 := m.AutoAdjustRange(f2)
	if r1 || r2 {
		m.UpdateGraphSizes()
	}

	// scale Cartesian coordinates data points to graphing area
	sf1 := m.ScaleFloat64PointForLine(f1)
	sf2 := m.ScaleFloat64PointForLine(f2)

	// convert scaled points to canvas points
	p1 := canvas.CanvasPointFromFloat64Point(m.origin, sf1)
	p2 := canvas.CanvasPointFromFloat64Point(m.origin, sf2)

	// draw line runes on all canvas coordinates between
	// the two canvas points that approximates a line
	points := graph.GetLinePoints(p1, p2)
	if len(points) <= 0 {
		return
	}
	graph.DrawLinePoints(&m.Canvas, points, ls, s)
}

// DrawBrailleLine draws braille line runes of a given LineStyle on to the linechart
// such that there is an approximate straight line between the two given Float64Point data points.
// Braille runes will not overlap the axes.
func (m *Model) DrawBrailleLine(f1 canvas.Float64Point, f2 canvas.Float64Point) {
	m.DrawBrailleLineWithStyle(f1, f2, m.Style)
}

// DrawBrailleLineWithStyle draws braille line runes of a given LineStyle and style on to the linechart
// such that there is an approximate straight line between the two given Float64Point data points.
// Braille runes will not overlap the axes.
func (m *Model) DrawBrailleLineWithStyle(f1 canvas.Float64Point, f2 canvas.Float64Point, s lipgloss.Style) {
	// auto adjust x and y ranges if enabled
	r1 := m.AutoAdjustRange(f1)
	r2 := m.AutoAdjustRange(f2)
	if r1 || r2 {
		m.UpdateGraphSizes()
	}

	bGrid := graph.NewBrailleGrid(m.graphWidth, m.graphHeight, m.minX, m.maxX, m.minY, m.maxY)

	// get braille grid points from two Float64Point data points
	p1 := bGrid.GridPoint(f1)
	p2 := bGrid.GridPoint(f2)

	// set all points in the braille grid between two points that approximates a line
	points := graph.GetLinePoints(p1, p2)
	for _, p := range points {
		bGrid.Set(p)
	}

	// get all rune patterns for braille grid and draw them on to the canvas
	startX := 0
	if m.yStep > 0 {
		startX = m.origin.X + 1
	}
	patterns := bGrid.BraillePatterns()
	graph.DrawBraillePatterns(&m.Canvas, canvas.Point{X: startX, Y: 0}, patterns, s)
}

// DrawBrailleCircle draws braille line runes of a given LineStyle on to the linechart
// such that there is an approximate circle of given float64 radius
// around the center of a circle at Float64Point data point.
// Braille runes will not overlap the axes.
func (m *Model) DrawBrailleCircle(p canvas.Float64Point, f float64) {
	m.DrawBrailleCircleWithStyle(p, f, m.Style)
}

// DrawBrailleCircleWithStyle draws braille line runes of a given LineStyle and style on to the linechart
// such that there is an approximate circle of given float64 radius
// around the center of a circle at Float64Point data point.
// Braille runes will not overlap the axes.
func (m *Model) DrawBrailleCircleWithStyle(c canvas.Float64Point, f float64, s lipgloss.Style) {
	center := canvas.NewPointFromFloat64Point(c) // round center to nearest integer
	radius := int(math.Round(f))                 // round radius to nearest integer

	// set braille grid points from computed circle points around center
	bGrid := graph.NewBrailleGrid(m.graphWidth, m.graphHeight, m.minX, m.maxX, m.minY, m.maxY)
	points := graph.GetCirclePoints(center, radius)
	for _, p := range points {
		np := canvas.NewFloat64PointFromPoint(p)
		if m.AutoAdjustRange(np) {
			m.UpdateGraphSizes()
		}
		bGrid.Set(bGrid.GridPoint(np))
	}

	// get all rune patterns for braille grid and draw them on to the canvas
	startX := 0
	if m.yStep > 0 {
		startX = m.origin.X + 1
	}
	patterns := bGrid.BraillePatterns()
	graph.DrawBraillePatterns(&m.Canvas, canvas.Point{X: startX, Y: 0}, patterns, s)
}

// Focused returns whether canvas is being focused.
func (m *Model) Focused() bool {
	return m.focus
}

// Focus enables Update events processing.
func (m *Model) Focus() {
	m.focus = true
}

// Blur disables Update events processing.
func (m *Model) Blur() {
	m.focus = false
}

// Init initializes the linechart.
func (m Model) Init() tea.Cmd {
	return m.Canvas.Init()
}

// Update processes bubbletea Msg to by invoking
// UpdateHandlerFunc callback if linechart is focused.
func (m Model) Update(msg tea.Msg) (Model, tea.Cmd) {
	if !m.focus {
		return m, nil
	}
	m.UpdateHandler(&m, msg)
	return m, nil
}

// View returns a string used by the bubbletea framework to display the linechart.
func (m Model) View() (r string) {
	r = m.Canvas.View()
	if m.zoneManager != nil {
		r = m.zoneManager.Mark(m.zoneID, r)
	}
	return
}
