// ntcharts - Copyright (c) 2024 Neomantra Corp.

package linechart

// File contains options used by the linechart during initialization with New().

import (
	"github.com/NimbleMarkets/ntcharts/canvas"

	"github.com/charmbracelet/lipgloss"
	zone "github.com/lrstanley/bubblezone"
)

// Option is used to set options when initializing a linechart. Example:
//
//	lc := New(width, height, minX, maxX, minY, maxY, WithZoneManager(someZoneManager))
type Option func(*Model)

// WithStyles sets the default style of the axes, the value shown for the axes
// and runes drawn on linechart.
func WithStyles(as lipgloss.Style, ls lipgloss.Style, s lipgloss.Style) Option {
	return func(m *Model) {
		m.AxisStyle = as
		m.LabelStyle = ls
		m.Style = s
	}
}

// WithXLabelFormatter sets the default X label formatter for displaying X values as strings.
func WithXLabelFormatter(fmter LabelFormatter) Option {
	return func(m *Model) {
		m.XLabelFormatter = fmter
	}
}

// WithYLabelFormatter sets the default Y label formatter for displaying Y values as strings.
func WithYLabelFormatter(fmter LabelFormatter) Option {
	return func(m *Model) {
		m.YLabelFormatter = fmter
	}
}

// / WithKeyMap sets the KeyMap used
// when processing keyboard event messages in Update().
func WithKeyMap(k canvas.KeyMap) Option {
	return func(m *Model) {
		m.Canvas.KeyMap = k
	}
}

// WithUpdateHandler sets the UpdateHandler used
// when processing bubbletea Msg events in Update().
func WithUpdateHandler(h UpdateHandler) Option {
	return func(m *Model) {
		m.UpdateHandler = h
	}
}

// WithZoneManager sets the bubblezone Manager used
// when processing bubbletea Msg mouse events in Update().
func WithZoneManager(zm *zone.Manager) Option {
	return func(m *Model) {
		m.SetZoneManager(zm)
	}
}

// WithXYSteps sets the number of steps when drawing
// X and Y axes values.
func WithXYSteps(x, y int) Option {
	return func(m *Model) {
		m.xStep = x
		m.yStep = y
	}
}

// WithAutoXYRange enables automatically setting the minimum and maximum
// expected X and Y values if new data values are beyond the current ranges.
func WithAutoXYRange() Option {
	return func(m *Model) {
		m.AutoMinX = true
		m.AutoMaxX = true
		m.AutoMinY = true
		m.AutoMaxY = true
	}
}

// WithAutoXRange enables automatically setting the minimum and maximum
// expected X values if new data values are beyond the current range.
func WithAutoXRange() Option {
	return func(m *Model) {
		m.AutoMinX = true
		m.AutoMaxX = true
	}
}

// WithAutoYRange enables automatically setting the minimum and maximum
// expected Y values if new data values are beyond the current range.
func WithAutoYRange() Option {
	return func(m *Model) {
		m.AutoMinY = true
		m.AutoMaxY = true
	}
}
