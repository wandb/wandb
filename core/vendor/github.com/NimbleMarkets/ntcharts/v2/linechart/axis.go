// ntcharts - Copyright (c) 2026 Neomantra Corp.

package linechart

// File contains the Y axes of a linechart: the left axis, kept in the
// Model's own fields, and an optional right axis.

import (
	"math"

	"charm.land/lipgloss/v2"

	"github.com/NimbleMarkets/ntcharts/v2/canvas"
	"github.com/NimbleMarkets/ntcharts/v2/canvas/graph"
	"github.com/NimbleMarkets/ntcharts/v2/canvas/runes"
)

// Axis describes one Y axis of a line chart. Read an axis with YAxis or
// Y2Axis, change its fields, and set it back with SetYAxis or SetY2Axis:
//
//	a, _ := m.Y2Axis()
//	a.Min, a.Max = 5, 20
//	m.SetY2Axis(a)
//
// The left axis's LabelStyle is the chart's LabelStyle, which the X axis
// labels share. Right axis labels fall on the left axis's label rows (on a
// linear right axis) and use the same YStep; there is no separate step.
//
// The right axis has no view of its own: its displayed range is derived
// from where the left axis's view sits within the left axis's range, so
// zooming or moving the left axis carries the right one along, and
// SetY2Axis ignores ViewMin and ViewMax. With a Y step of 0 the right axis
// is not drawn and reserves no space, but it still maps values through Y2ToY.
type Axis struct {
	Min, Max         float64        // expected data range
	ViewMin, ViewMax float64        // displayed range; ViewMin == ViewMax means Min..Max
	Scale            Scale          // ScaleLinear (the default) or ScaleLog
	AutoMin, AutoMax bool           // widen Min or Max when data falls outside
	LabelFormatter   LabelFormatter // nil means DefaultLabelFormatter()
	LabelStyle       lipgloss.Style // style of this axis's labels
}

// YAxisSide selects the left or right Y axis of a line chart.
type YAxisSide int

const (
	// YAxisLeft is the chart's main Y axis. It is the zero value.
	YAxisLeft YAxisSide = iota
	// YAxisRight is the optional second Y axis set with SetY2Axis.
	YAxisRight
)

// YAxis returns the left Y axis.
func (m *Model) YAxis() Axis {
	return Axis{
		Min:            m.minY,
		Max:            m.maxY,
		ViewMin:        m.viewMinY,
		ViewMax:        m.viewMaxY,
		Scale:          m.yScale,
		AutoMin:        m.AutoMinY,
		AutoMax:        m.AutoMaxY,
		LabelFormatter: m.YLabelFormatter,
		LabelStyle:     m.LabelStyle,
	}
}

// SetYAxis sets the left Y axis. It has the effect of SetYScale,
// SetYRange and SetViewYRange, in that order, then sets AutoMinY,
// AutoMaxY, YLabelFormatter and LabelStyle. LabelStyle also styles the X
// axis labels.
func (m *Model) SetYAxis(a Axis) {
	m.SetYScale(a.Scale)
	m.SetYRange(a.Min, a.Max)
	m.viewMinY, m.viewMaxY = m.minY, m.maxY
	if a.ViewMin != a.ViewMax {
		m.SetViewYRange(a.ViewMin, a.ViewMax)
	}
	m.AutoMinY, m.AutoMaxY = a.AutoMin, a.AutoMax
	m.YLabelFormatter = a.LabelFormatter
	if m.YLabelFormatter == nil {
		m.YLabelFormatter = DefaultLabelFormatter()
	}
	m.LabelStyle = a.LabelStyle
	m.UpdateGraphSizes()
}

// Y2Axis returns the right Y axis and true, or false if the chart has
// none. ViewMin and ViewMax are the displayed range derived from the left
// axis (see Axis).
func (m *Model) Y2Axis() (Axis, bool) {
	if m.y2 == nil {
		return Axis{}, false
	}
	a := *m.y2
	a.ViewMin, a.ViewMax = m.y2View()
	return a, true
}

// SetY2Axis adds a right Y axis to the chart, or replaces it. The range is
// sanitized as for the left axis (see SetYRange); a range that is not
// Min < Max becomes 0..1 on a linear axis or 1..10 on a log axis. ViewMin
// and ViewMax are ignored, since the right axis's view follows the left
// (see Axis). A nil LabelFormatter means DefaultLabelFormatter().
//
// Draw right-axis values with any Draw method by mapping them with Y2ToY,
// and auto-range them with AutoAdjustY2Range. The data-set charts do both
// for data sets assigned to the right axis. With a Y step of 0 the right
// axis is not drawn and reserves no space, but right-axis data still maps
// through Y2ToY.
func (m *Model) SetY2Axis(a Axis) {
	a.Min, a.Max = a.Scale.sanitize(a.Min, a.Max)
	if !(a.Min < a.Max) {
		a.Min, a.Max = 0, 1
		if a.Scale == ScaleLog {
			a.Min, a.Max = 1, 10
		}
	}
	a.ViewMin, a.ViewMax = 0, 0
	if a.LabelFormatter == nil {
		a.LabelFormatter = DefaultLabelFormatter()
	}
	m.y2 = &a
	m.UpdateGraphSizes()
}

// ClearY2Axis removes the right Y axis. The chart then renders as if it
// never had one.
func (m *Model) ClearY2Axis() {
	m.y2 = nil
	m.UpdateGraphSizes()
}

// y2View returns the displayed range of the right axis: the part of its
// range at the same relative position, in each axis's scale space, as the
// left view within the left range. Requires m.y2 != nil.
func (m *Model) y2View() (float64, float64) {
	a := m.y2
	d := m.yScale.span(m.minY, m.maxY)
	if !(d > 0) {
		return a.Min, a.Max
	}
	r0, dr := a.Scale.forward(a.Min), a.Scale.span(a.Min, a.Max)
	at := func(v float64) float64 {
		switch f := m.yScale.span(m.minY, v) / d; f {
		case 0:
			return a.Min
		case 1:
			return a.Max
		default:
			return a.Scale.inverse(r0 + f*dr)
		}
	}
	return at(m.viewMinY), at(m.viewMaxY)
}

// Y2ToY maps a right-axis value to the left-axis value at the same height
// on the chart, so it can be drawn with any Draw method. Both scales are
// taken into account. It returns v if the chart has no right axis, and NaN
// if v has no place on the right axis (see Scale.Valid); check for NaN
// before drawing, since the Draw methods accept it on a linear left axis and
// draw a stray stroke at the baseline. The Draw methods auto-range the left
// axis with the value they are given, so call AutoAdjustY2Range on the raw
// right-axis point first, or a value outside the right range widens the left
// axis. After any range change, redraw: earlier mappings were made against
// the old view.
func (m *Model) Y2ToY(v float64) float64 {
	if m.y2 == nil {
		return v
	}
	if !m.y2.Scale.Valid(v) {
		return math.NaN()
	}
	lo, hi := m.y2View()
	d := m.y2.Scale.span(lo, hi)
	if !(d > 0) {
		return m.viewMinY
	}
	switch f := m.y2.Scale.span(lo, v) / d; f {
	case 0:
		return m.viewMinY
	case 1:
		return m.viewMaxY
	default:
		return m.yScale.inverse(m.yScale.forward(m.viewMinY) + f*m.yScale.span(m.viewMinY, m.viewMaxY))
	}
}

// y2Drawn reports whether the right axis is drawn: the chart has one and
// shows Y axes (YStep > 0).
func (m *Model) y2Drawn() bool {
	return m.y2 != nil && m.yStep > 0
}

// GraphRight returns the canvas column just right of the graphing area:
// the right Y axis's column when one is drawn, else the canvas width.
// Line runes drawn by the data-set charts span Origin().X to GraphRight()-1.
func (m *Model) GraphRight() int {
	if m.y2Drawn() {
		return m.origin.X + m.graphWidth + 1
	}
	return m.Canvas.Width()
}

// inPlot reports whether canvas point p is left of the right Y axis, if
// one is drawn.
func (m *Model) inPlot(p canvas.Point) bool {
	return !m.y2Drawn() || p.X <= m.origin.X+m.graphWidth
}

// linearYTicks returns the labels of a linear Y axis showing lo..hi over
// graphHeight rows: every n rows from the bottom plus the top row,
// skipping a label equal to the one below it.
func linearYTicks(lo, hi float64, graphHeight, n int, fmter LabelFormatter) []tick {
	if n <= 0 {
		return nil
	}
	var ticks []tick
	var last string
	increment := (hi - lo) / float64(graphHeight)
	for i := 0; i <= graphHeight; {
		v := lo
		if i > 0 {
			v = lo + increment*float64(i)
		}
		if s := fmter(i, v); s != last {
			ticks = append(ticks, tick{pos: i, value: v, label: s})
			last = s
		}
		if i == graphHeight {
			break
		}
		i = min(i+n, graphHeight)
	}
	return ticks
}

// y2Ticks returns the labels of the right axis over its displayed range
// and graphHeight rows. Requires m.y2 != nil.
func (m *Model) y2Ticks(graphHeight int) []tick {
	lo, hi := m.y2View()
	if m.y2.Scale == ScaleLog {
		return yTicks(lo, hi, graphHeight, m.yStep, m.y2.LabelFormatter)
	}
	return linearYTicks(lo, hi, graphHeight, m.yStep, m.y2.LabelFormatter)
}

// drawY2Axis draws the right axis line, meeting the X axis with a corner.
// The X axis stops at the right axis.
func (m *Model) drawY2Axis() {
	if !m.y2Drawn() {
		return
	}
	x := m.origin.X + m.graphWidth + 1
	if m.xStep <= 0 {
		graph.DrawVerticalLineUp(&m.Canvas, canvas.Point{X: x, Y: m.origin.Y}, m.AxisStyle)
		return
	}
	for c := x + 1; c < m.Canvas.Width(); c++ {
		m.Canvas.SetCell(canvas.Point{X: c, Y: m.origin.Y}, canvas.Cell{})
	}
	m.Canvas.SetCell(canvas.Point{X: x, Y: m.origin.Y}, canvas.NewCellWithStyle(runes.LineUpLeft, m.AxisStyle))
	graph.DrawVerticalLineUp(&m.Canvas, canvas.Point{X: x, Y: m.origin.Y - 1}, m.AxisStyle)
}

// drawY2Label draws the right axis labels, left-aligned right of its line.
func (m *Model) drawY2Label() {
	if !m.y2Drawn() {
		return
	}
	x := m.origin.X + m.graphWidth + 2
	for _, t := range m.y2Ticks(m.graphHeight) {
		m.Canvas.SetStringWithStyle(canvas.Point{X: x, Y: m.origin.Y - t.pos}, t.label, m.y2.LabelStyle)
	}
}

// AutoAdjustY2Range is AutoAdjustRange for a point whose Y is a right-axis
// value: it widens the X range as AutoAdjustRange does, and the right
// axis's Min or Max if its AutoMin or AutoMax is set. The left axis is
// untouched. It returns whether the displayed ranges changed, and if so
// recomputes the layout. Without a right axis, or for a point with no
// place on the X or right axis, it does nothing and returns false.
func (m *Model) AutoAdjustY2Range(f canvas.Float64Point) (b bool) {
	if m.y2 == nil || !m.xScale.Valid(f.X) || !m.y2.Scale.Valid(f.Y) {
		return false
	}
	b = m.autoAdjustX(f.X)
	a := *m.y2 // copy: Model copies share m.y2
	changed := false
	if a.AutoMin && f.Y < a.Min {
		a.Min, changed = f.Y, true
	}
	if a.AutoMax && f.Y > a.Max {
		a.Max, changed = f.Y, true
	}
	if changed {
		m.y2 = &a
		b = true
	}
	if b {
		m.UpdateGraphSizes()
	}
	return b
}
