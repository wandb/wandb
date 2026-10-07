// ntcharts - Copyright (c) 2026 Neomantra Corp.

package linechart

// File contains the axis scales of a linechart and the transform between
// data values and positions along an axis.

import (
	"math"

	"github.com/NimbleMarkets/ntcharts/v2/canvas"
)

// Scale selects how values are spaced along a linechart axis.
// Ranges, data points and label formatter values are in data units on
// every scale; only the mapping from value to row or column changes.
type Scale int

const (
	// ScaleLinear spaces values evenly along the axis. It is the zero
	// value and the default.
	ScaleLinear Scale = iota
	// ScaleLog spaces values by their base-10 logarithm, so each decade
	// takes the same length of axis. Only values greater than zero have a
	// place on a log axis.
	ScaleLog
)

// String returns "linear" or "log".
func (s Scale) String() string {
	if s == ScaleLog {
		return "log"
	}
	return "linear"
}

// Valid reports whether v has a place on an axis of this scale.
// Every value is valid on a linear axis; a log axis takes only finite
// values greater than zero.
func (s Scale) Valid(v float64) bool {
	if s == ScaleLog {
		return v > 0 && !math.IsInf(v, 1)
	}
	return true
}

// logSnap is how close (in decades) a position must be to a whole number
// to count as a power of ten. It absorbs floating-point drift:
// math.Log10(1000) is 2.9999999999999996, and math.Pow(10, that) is
// 999.9999999999991.
const logSnap = 1e-9

// forward maps a valid data value to scale space: its base-10 logarithm on
// a log axis (exact for powers of ten), itself on a linear axis.
func (s Scale) forward(v float64) float64 {
	if s != ScaleLog {
		return v
	}
	p := math.Log10(v)
	if r := math.Round(p); math.Abs(p-r) < logSnap {
		return r
	}
	return p
}

// inverse maps a scale-space position back to a data value. On a log axis
// a position within logSnap of a whole number is exactly that power of ten.
func (s Scale) inverse(p float64) float64 {
	if s != ScaleLog {
		return p
	}
	if r := math.Round(p); math.Abs(p-r) < logSnap {
		return math.Pow10(int(r))
	}
	return math.Pow(10, p)
}

// span returns the scale-space distance from a to b.
func (s Scale) span(a, b float64) float64 {
	if s != ScaleLog {
		return b - a
	}
	return s.forward(b) - s.forward(a)
}

// shift moves v by d in scale space: v+d on a linear axis, v*10^d on a
// log axis.
func (s Scale) shift(v, d float64) float64 {
	if s != ScaleLog {
		return v + d
	}
	return s.inverse(s.forward(v) + d)
}

// sanitize returns a range that an axis of this scale can show. A linear
// axis takes any range. On a log axis a minimum that is not valid becomes
// one decade below the maximum, a maximum that is not valid becomes one
// decade above the minimum, and if neither is valid the range is 1..10.
func (s Scale) sanitize(min, max float64) (float64, float64) {
	if s != ScaleLog {
		return min, max
	}
	switch okMin, okMax := s.Valid(min), s.Valid(max); {
	case okMin && okMax:
		return min, max
	case okMax:
		return max / 10, max
	case okMin:
		return min, min * 10
	}
	return 1, 10
}

// drawable reports whether both coordinates of f have a place on the
// linechart's axes.
func (m *Model) drawable(f canvas.Float64Point) bool {
	return m.xScale.Valid(f.X) && m.yScale.Valid(f.Y)
}

// XScale returns the scale of the X axis.
func (m *Model) XScale() Scale {
	return m.xScale
}

// YScale returns the scale of the Y axis.
func (m *Model) YScale() Scale {
	return m.yScale
}

// SetXScale sets the scale of the X axis. Ranges stay in data units.
// A log axis cannot show a non-positive bound, so on ScaleLog the expected
// and displayed X ranges are sanitized as described on SetXRange.
func (m *Model) SetXScale(s Scale) {
	m.xScale = s
	m.minX, m.maxX = s.sanitize(m.minX, m.maxX)
	m.viewMinX, m.viewMaxX = sanitizeView(s, m.viewMinX, m.viewMaxX, m.minX, m.maxX)
	m.UpdateGraphSizes()
}

// SetYScale sets the scale of the Y axis. Ranges stay in data units.
// A log axis cannot show a non-positive bound, so on ScaleLog the expected
// and displayed Y ranges are sanitized as described on SetYRange.
func (m *Model) SetYScale(s Scale) {
	m.yScale = s
	m.minY, m.maxY = s.sanitize(m.minY, m.maxY)
	m.viewMinY, m.viewMaxY = sanitizeView(s, m.viewMinY, m.viewMaxY, m.minY, m.maxY)
	m.UpdateGraphSizes()
}

// sanitizeView sanitizes a displayed range and keeps it inside the
// expected range min..max, falling back to the whole expected range.
func sanitizeView(s Scale, viewMin, viewMax, min, max float64) (float64, float64) {
	if s != ScaleLog {
		return viewMin, viewMax
	}
	viewMin, viewMax = s.sanitize(viewMin, viewMax)
	viewMin, viewMax = math.Max(min, viewMin), math.Min(max, viewMax)
	if viewMin < viewMax {
		return viewMin, viewMax
	}
	return min, max
}
