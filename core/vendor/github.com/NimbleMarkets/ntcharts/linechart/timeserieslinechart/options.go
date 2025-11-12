// ntcharts - Copyright (c) 2024 Neomantra Corp.

package timeserieslinechart

// File contains options used by the timeserieslinechart during initialization with New().

import (
	"time"

	"github.com/NimbleMarkets/ntcharts/canvas/runes"
	"github.com/NimbleMarkets/ntcharts/linechart"

	"github.com/charmbracelet/lipgloss"
	zone "github.com/lrstanley/bubblezone"
)

// Option is used to set options when initializing a timeserieslinechart. Example:
//
//	tslc := New(width, height, minX, maxX, minY, maxY, WithStyles(someLineStyle, someLipglossStyle))
type Option func(*Model)

// WithLineChart sets internal linechart to given linechart.
func WithLineChart(lc *linechart.Model) Option {
	return func(m *Model) {
		m.Model = *lc
	}
}

// WithUpdateHandler sets the UpdateHandler used
// when processing bubbletea Msg events in Update().
func WithUpdateHandler(h linechart.UpdateHandler) Option {
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

// WithXLabelFormatter sets the default X label formatter for displaying X values as strings.
func WithXLabelFormatter(fmter linechart.LabelFormatter) Option {
	return func(m *Model) {
		m.XLabelFormatter = fmter
	}
}

// WithYLabelFormatter sets the default Y label formatter for displaying Y values as strings.
func WithYLabelFormatter(fmter linechart.LabelFormatter) Option {
	return func(m *Model) {
		m.YLabelFormatter = fmter
	}
}

// WithAxesStyles sets the axes line and line label styles.
func WithAxesStyles(as lipgloss.Style, ls lipgloss.Style) Option {
	return func(m *Model) {
		m.AxisStyle = as
		m.LabelStyle = ls
	}
}

// WithXYSteps sets the number of steps when drawing X and Y axes values.
// If X steps 0, then X axis will be hidden.
// If Y steps 0, then Y axis will be hidden.
func WithXYSteps(x, y int) Option {
	return func(m *Model) {
		m.SetXStep(x)
		m.SetYStep(y)
	}
}

// WithYRange sets expected and displayed
// minimum and maximum Y value range.
func WithYRange(min, max float64) Option {
	return func(m *Model) {
		m.SetYRange(min, max)
		m.SetViewYRange(min, max)
	}
}

// WithTimeRange sets expected and displayed minimun and maximum
// time values range on the X axis.
func WithTimeRange(min, max time.Time) Option {
	return func(m *Model) {
		m.SetTimeRange(min, max)
		m.SetViewTimeRange(min, max)
	}
}

// WithLineStyle sets the default line style of data sets.
func WithLineStyle(ls runes.LineStyle) Option {
	return func(m *Model) {
		m.SetLineStyle(ls)
	}
}

// WithDataSetLineStyle sets the line style of the data set given by name.
func WithDataSetLineStyle(n string, ls runes.LineStyle) Option {
	return func(m *Model) {
		m.SetDataSetLineStyle(n, ls)
	}
}

// WithStyle sets the default lipgloss style of data sets.
func WithStyle(s lipgloss.Style) Option {
	return func(m *Model) {
		m.SetStyle(s)
	}
}

// WithDataSetStyle sets the lipgloss style of the data set given by name.
func WithDataSetStyle(n string, s lipgloss.Style) Option {
	return func(m *Model) {
		m.SetDataSetStyle(n, s)
	}
}

// WithTimeSeries adds []TimePoint values to the default data set.
func WithTimeSeries(p []TimePoint) Option {
	return func(m *Model) {
		for _, v := range p {
			m.Push(v)
		}
	}
}

// WithDataSetTimeSeries adds []TimePoint data points to the data set given by name.
func WithDataSetTimeSeries(n string, p []TimePoint) Option {
	return func(m *Model) {
		for _, v := range p {
			m.PushDataSet(n, v)
		}
	}
}
