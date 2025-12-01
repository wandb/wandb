// ntcharts - Copyright (c) 2024 Neomantra Corp.

// Package timeserieslinechart implements a linechart that draws lines
// for time series data points
package timeserieslinechart

// https://en.wikipedia.org/wiki/Moving_average

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/NimbleMarkets/ntcharts/canvas"
	"github.com/NimbleMarkets/ntcharts/canvas/buffer"
	"github.com/NimbleMarkets/ntcharts/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/canvas/runes"
	"github.com/NimbleMarkets/ntcharts/linechart"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const DefaultDataSetName = "default"

func DateTimeLabelFormatter() linechart.LabelFormatter {
	var yearLabel string
	return func(i int, v float64) string {
		if i == 0 { // reset year labeling if redisplaying values
			yearLabel = ""
		}
		t := time.Unix(int64(v), 0).UTC()
		monthDay := t.Format("01/02")
		year := t.Format("'06")
		if yearLabel != year { // apply year label if first time seeing year
			yearLabel = year
			return fmt.Sprintf("%s %s", yearLabel, monthDay)
		} else {
			return monthDay
		}
	}
}

func HourTimeLabelFormatter() linechart.LabelFormatter {
	return func(i int, v float64) string {
		t := time.Unix(int64(v), 0).UTC()
		return t.Format("15:04:05")
	}
}

type TimePoint struct {
	Time  time.Time
	Value float64
}

// cAverage tracks cumulative average
type cAverage struct {
	Avg   float64
	Count float64
}

// Add adds a float64 to current cumulative average
func (a *cAverage) Add(f float64) float64 {
	a.Count += 1
	a.Avg += (f - a.Avg) / a.Count
	return a.Avg
}

type dataSet struct {
	LineStyle runes.LineStyle // type of line runes to draw
	Style     lipgloss.Style

	// stores TimePoints as FloatPoint64{X:time.Time, Y: value}
	// time.Time will be converted to seconds since epoch.
	// both time and value will be scaled to fit the graphing area
	tBuf *buffer.Float64PointScaleBuffer
}

// Model contains state of a timeserieslinechart with an embedded linechart.Model
// The X axis contains time.Time values and the Y axis contains float64 values.
// A data set consists of a sequence TimePoints in chronological order.
// If multiple TimePoints map to the same column, then average value the time points
// will be used as the Y value of the column.
// The X axis contains a time range and the Y axis contains a numeric value range.
// Uses linechart Model UpdateHandler() for processing keyboard and mouse messages.
type Model struct {
	linechart.Model
	dLineStyle runes.LineStyle     // default data set LineStyletype
	dStyle     lipgloss.Style      // default data set Style
	dSets      map[string]*dataSet // maps names to data sets
}

// New returns a timeserieslinechart Model initialized from
// width, height, Y value range and various options.
// By default, the chart will set time.Now() as the minimum time,
// enable auto set X and Y value ranges,
// and only allow moving viewport on X axis.
func New(w, h int, opts ...Option) Model {
	min := time.Now()
	max := min.Add(time.Second)
	m := Model{
		Model: linechart.New(w, h, float64(min.Unix()), float64(max.Unix()), 0, 1,
			linechart.WithXYSteps(4, 2),
			linechart.WithXLabelFormatter(DateTimeLabelFormatter()),
			linechart.WithAutoXYRange(),                        // automatically adjust value ranges
			linechart.WithUpdateHandler(DateUpdateHandler(1))), // only scroll on X axis, increments by 1 day
		dLineStyle: runes.ArcLineStyle,
		dStyle:     lipgloss.NewStyle(),
		dSets:      make(map[string]*dataSet),
	}
	for _, opt := range opts {
		opt(&m)
	}
	m.UpdateGraphSizes()
	m.rescaleData()
	if _, ok := m.dSets[DefaultDataSetName]; !ok {
		m.dSets[DefaultDataSetName] = m.newDataSet()
	}
	return m
}

// newDataSet returns a new initialize *dataSet.
func (m *Model) newDataSet() *dataSet {
	xs := float64(m.GraphWidth()) / (m.ViewMaxX() - m.ViewMinX()) // x scale factor
	ys := float64(m.Origin().Y) / (m.ViewMaxY() - m.ViewMinY())   // y scale factor
	offset := canvas.Float64Point{X: m.ViewMinX(), Y: m.ViewMinY()}
	scale := canvas.Float64Point{X: xs, Y: ys}
	return &dataSet{
		LineStyle: m.dLineStyle,
		Style:     m.dStyle,
		tBuf:      buffer.NewFloat64PointScaleBuffer(offset, scale),
	}
}

// rescaleData will reinitialize time chunks and
// map time points into graph columns for display
func (m *Model) rescaleData() {
	// rescale time points buffer
	xs := float64(m.GraphWidth()) / (m.ViewMaxX() - m.ViewMinX()) // x scale factor
	ys := float64(m.Origin().Y) / (m.ViewMaxY() - m.ViewMinY())   // y scale factor
	offset := canvas.Float64Point{X: m.ViewMinX(), Y: m.ViewMinY()}
	scale := canvas.Float64Point{X: xs, Y: ys}
	for _, ds := range m.dSets {
		if ds.tBuf.Offset() != offset {
			ds.tBuf.SetOffset(offset)
		}
		if ds.tBuf.Scale() != scale {
			ds.tBuf.SetScale(scale)
		}
	}
}

// ClearAllData will reset stored data values in all data sets.
func (m *Model) ClearAllData() {
	for _, ds := range m.dSets {
		ds.tBuf.Clear()
	}
	m.dSets[DefaultDataSetName] = m.newDataSet()
}

// ClearDataSet will erase stored data set given by name string.
func (m *Model) ClearDataSet(n string) {
	if ds, ok := m.dSets[n]; ok {
		ds.tBuf.Clear()
	}
}

// SetTimeRange updates the minimum and maximum expected time values.
// Existing data will be rescaled.
func (m *Model) SetTimeRange(min, max time.Time) {
	m.Model.SetXRange(float64(min.Unix()), float64(max.Unix()))
	m.rescaleData()
}

// SetYRange updates the minimum and maximum expected Y values.
// Existing data will be rescaled.
func (m *Model) SetYRange(min, max float64) {
	m.Model.SetYRange(min, max)
	m.rescaleData()
}

// SetViewTimeRange updates the displayed minimum and maximum time values.
// Existing data will be rescaled.
func (m *Model) SetViewTimeRange(min, max time.Time) {
	m.Model.SetViewXRange(float64(min.Unix()), float64(max.Unix()))
	m.rescaleData()
}

// SetViewYRange updates the displayed minimum and maximum Y values.
// Existing data will be rescaled.
func (m *Model) SetViewYRange(min, max float64) {
	m.Model.SetViewYRange(min, max)
	m.rescaleData()
}

// SetViewTimeAndYRange updates the displayed minimum and maximum time and Y values.
// Existing data will be rescaled.
func (m *Model) SetViewTimeAndYRange(minX, maxX time.Time, minY, maxY float64) {
	m.Model.SetViewXRange(float64(minX.Unix()), float64(maxX.Unix()))
	m.Model.SetViewYRange(minY, maxY)
	m.rescaleData()
}

// Resize will change timeserieslinechart display width and height.
// Existing data will be rescaled.
func (m *Model) Resize(w, h int) {
	m.Model.Resize(w, h)
	m.rescaleData()
}

// SetLineStyle will set the default line styles of data sets.
func (m *Model) SetLineStyle(ls runes.LineStyle) {
	m.dLineStyle = ls
	m.SetDataSetLineStyle(DefaultDataSetName, ls)
}

// SetStyle will set the default lipgloss styles of data sets.
func (m *Model) SetStyle(s lipgloss.Style) {
	m.dStyle = s
	m.SetDataSetStyle(DefaultDataSetName, s)
}

// SetDataSetLineStyle will set the line style of the given data set by name string.
func (m *Model) SetDataSetLineStyle(n string, ls runes.LineStyle) {
	if _, ok := m.dSets[n]; !ok {
		m.dSets[n] = m.newDataSet()
	}
	ds := m.dSets[n]
	ds.LineStyle = ls
}

// SetDataSetStyle will set the lipgloss style of the given data set by name string.
func (m *Model) SetDataSetStyle(n string, s lipgloss.Style) {
	if _, ok := m.dSets[n]; !ok {
		m.dSets[n] = m.newDataSet()
	}
	ds := m.dSets[n]
	ds.Style = s
}

// Push will push a TimePoint data value to the default data set
// to be displayed with Draw.
func (m *Model) Push(t TimePoint) {
	m.PushDataSet(DefaultDataSetName, t)
}

// Push will push a TimePoint data value to a data set
// to be displayed with Draw. Using given data set by name string.
func (m *Model) PushDataSet(n string, t TimePoint) {
	f := canvas.Float64Point{X: float64(t.Time.Unix()), Y: t.Value}
	// auto adjust x and y ranges if enabled
	if m.AutoAdjustRange(f) {
		m.UpdateGraphSizes()
		m.rescaleData()
	}
	if _, ok := m.dSets[n]; !ok {
		m.dSets[n] = m.newDataSet()
	}
	ds := m.dSets[n]
	ds.tBuf.Push(f)
}

// Draw will draw lines runes displayed from left to right
// of the graphing area of the canvas. Uses default data set.
func (m *Model) Draw() {
	m.DrawDataSets([]string{DefaultDataSetName})
}

// DrawAll will draw lines runes for all data sets
// from left to right of the graphing area of the canvas.
func (m *Model) DrawAll() {
	names := make([]string, 0, len(m.dSets))
	for n, ds := range m.dSets {
		if ds.tBuf.Length() > 0 {
			names = append(names, n)
		}
	}
	sort.Strings(names)
	m.DrawDataSets(names)
}

// DrawDataSets will draw lines runes from left to right
// of the graphing area of the canvas for each data set given
// by name strings.
func (m *Model) DrawDataSets(names []string) {
	if len(names) == 0 {
		return
	}
	m.Clear()
	m.DrawXYAxisAndLabel()
	for _, n := range names {
		if ds, ok := m.dSets[n]; ok {
			dataPoints := ds.tBuf.ReadAll()
			dataLen := len(dataPoints)
			if dataLen == 0 {
				return
			}
			// get sequence of line values for graphing
			seqY := m.getLineSequence(dataPoints)
			// convert to canvas coordinates and avoid drawing below X axis
			yCoords := canvas.CanvasYCoordinates(m.Origin().Y, seqY)
			if m.XStep() > 0 {
				for i, v := range yCoords {
					if v > m.Origin().Y {
						yCoords[i] = m.Origin().Y
					}
				}
			}
			startX := m.Canvas.Width() - len(yCoords)
			graph.DrawLineSequence(&m.Canvas,
				(startX == m.Origin().X),
				startX,
				yCoords,
				ds.LineStyle,
				ds.Style)
		}
	}
}

// DrawBraille will draw braille runes displayed from left to right
// of the graphing area of the canvas. Uses default data set.
func (m *Model) DrawBraille() {
	m.DrawBrailleDataSets([]string{DefaultDataSetName})
}

// DrawBrailleAll will draw braille runes for all data sets
// from left to right of the graphing area of the canvas.
func (m *Model) DrawBrailleAll() {
	names := make([]string, 0, len(m.dSets))
	for n, ds := range m.dSets {
		if ds.tBuf.Length() > 0 {
			names = append(names, n)
		}
	}
	sort.Strings(names)
	m.DrawBrailleDataSets(names)
}

// DrawBraille will draw braille runes displayed from left to right
// of the graphing area of the canvas.
// Requires four data sets containing candlestick data open, high, low, close values.
// Assumes that all data sets have the same number of TimePoints and
// the TimePoint at the same index of each data set has the same Time value.
func (m *Model) DrawCandle(openName, highName, lowName, closeName string, bullStyle, bearStyle lipgloss.Style) {
	if len(openName) == 0 || len(highName) == 0 || len(lowName) == 0 || len(closeName) == 0 {
		return
	}
	if _, ok := m.dSets[openName]; !ok {
		return
	}
	if _, ok := m.dSets[highName]; !ok {
		return
	}
	if _, ok := m.dSets[lowName]; !ok {
		return
	}
	if _, ok := m.dSets[closeName]; !ok {
		return
	}
	// only draws up to the number of candles of the data sets with the lowest
	// amount of data values if length if data is not the same across all data sets
	oData := m.dSets[openName].tBuf.ReadAll()
	hData := m.dSets[highName].tBuf.ReadAll()
	lData := m.dSets[lowName].tBuf.ReadAll()
	cData := m.dSets[closeName].tBuf.ReadAll()
	limit := len(oData)
	if len(hData) < limit {
		limit = len(hData)
	}
	if len(lData) < limit {
		limit = len(lData)
	}
	if len(cData) < limit {
		limit = len(cData)
	}

	m.Clear()
	m.DrawXYAxisAndLabel()
	for i := 0; i < limit; i++ {
		// assuming all time values are the same, can just any of the values to check
		// if data point is outside of the current graph view to ignore
		if oData[i].X < 0 {
			continue
		}
		var s lipgloss.Style
		var bl, bh float64
		if oData[i].Y > cData[i].Y { // check if bearish or bullish candle
			s = bearStyle
			bl = cData[i].Y
			bh = oData[i].Y
		} else {
			s = bullStyle
			bh = cData[i].Y
			bl = oData[i].Y
		}
		drawX := int(oData[i].X) + m.Origin().X
		if m.YStep() > 0 {
			drawX += 1
		}
		graph.DrawCandlestickBottomToTop(&m.Canvas,
			canvas.Point{X: drawX, Y: m.Origin().Y - 1},
			lData[i].Y, bl, bh, hData[i].Y, s)
	}
}

// DrawBrailleDataSets will draw braille runes from left to right
// of the graphing area of the canvas for each data set given
// by name strings.
func (m *Model) DrawBrailleDataSets(names []string) {
	if len(names) == 0 {
		return
	}
	m.Clear()
	m.DrawXYAxisAndLabel()
	for _, n := range names {
		if ds, ok := m.dSets[n]; ok {
			dataPoints := ds.tBuf.ReadAll()
			dataLen := len(dataPoints)
			if dataLen == 0 {
				return
			}
			// draw lines from each point to the next point
			bGrid := graph.NewBrailleGrid(m.GraphWidth(), m.GraphHeight(),
				0, float64(m.GraphWidth()), // X values already scaled to graph
				0, float64(m.GraphHeight())) // Y values already scaled to graph
			for i := 0; i < dataLen; i++ {
				j := i + 1
				if j >= dataLen {
					j = i
				}
				p1 := dataPoints[i]
				p2 := dataPoints[j]
				// ignore points that will not be displayed
				bothBeforeMin := (p1.X < 0 && p2.X < 0)
				bothAfterMax := (p1.X > float64(m.GraphWidth()) && p2.X > float64(m.GraphWidth()))
				if bothBeforeMin || bothAfterMax {
					continue
				}
				// get braille grid points from two Float64Point data points
				gp1 := bGrid.GridPoint(p1)
				gp2 := bGrid.GridPoint(p2)
				// set all points in the braille grid
				// between two points that approximates a line
				points := graph.GetLinePoints(gp1, gp2)
				for _, p := range points {
					bGrid.Set(p)
				}
			}

			// get all rune patterns for braille grid
			// and draw them on to the canvas
			startX := 0
			if m.YStep() > 0 {
				startX = m.Origin().X + 1
			}
			patterns := bGrid.BraillePatterns()
			graph.DrawBraillePatterns(&m.Canvas,
				canvas.Point{X: startX, Y: 0}, patterns, ds.Style)
		}
	}
}

// Set column background style to given lipgloss.Style background
// corresponding to timestamp at given time.Time.
func (m *Model) SetColumnBackgroundStyle(ts time.Time, s lipgloss.Style) {
	f := canvas.Float64Point{X: float64(ts.Unix()), Y: 0}
	if f.X < m.ViewMinX() || f.X > m.ViewMaxX() {
		return
	}
	// use default dataset to scale the given time to the canvas (any dataset do)
	sf := m.dSets[DefaultDataSetName].tBuf.ScaleDatum(f)
	drawX := int(sf.X) + m.Origin().X
	if m.YStep() > 0 {
		drawX += 1
	}
	for i := range m.Origin().Y {
		cs := m.Canvas.Cell(canvas.Point{X: drawX, Y: i}).Style.Copy() // copy cell foreground
		cs = cs.Background(s.GetBackground())                          // set cell background to given style background
		m.Canvas.SetCellStyle(canvas.Point{X: drawX, Y: i}, cs)
	}
}

// getLineSequence returns a sequence of Y values
// to draw line runes from a given set of scaled []FloatPoint64.
func (m *Model) getLineSequence(points []canvas.Float64Point) []int {
	width := m.Width() - m.Origin().X // line runes can draw on axes
	if width <= 0 {
		return []int{}
	}
	dataLen := len(points)
	// each index of the bucket corresponds to a graph column.
	// each index value is the average of data point values
	// that is mapped to that graph column.
	buckets := make([]cAverage, width)
	for i := 0; i < dataLen; i++ {
		j := i + 1
		if j >= dataLen {
			j = i
		}
		p1 := canvas.NewPointFromFloat64Point(points[i])
		p2 := canvas.NewPointFromFloat64Point(points[j])
		// ignore points that will not be displayed on the graph
		bothBeforeMin := (p1.X < 0 && p2.X < 0)
		bothAfterMax := (p1.X > m.GraphWidth() && p2.X > m.GraphWidth())
		if bothBeforeMin || bothAfterMax {
			continue
		}
		// place all points between two points
		// that approximates a line into buckets
		points := graph.GetLinePoints(p1, p2)
		for _, p := range points {
			if (p.X >= 0) && (p.X) < width {
				buckets[p.X].Add(float64(p.Y))
			}
		}
	}
	// populate sequence of Y values for drawing lines
	r := make([]int, width)
	for i, v := range buckets {
		r[i] = int(math.Round(v.Avg))
	}
	return r
}

// Update processes bubbletea Msg by invoking
// UpdateHandlerFunc callback if linechart is focused.
func (m Model) Update(msg tea.Msg) (Model, tea.Cmd) {
	if !m.Focused() {
		return m, nil
	}
	m.UpdateHandler(&m.Model, msg)
	m.rescaleData()
	return m, nil
}
