package leet

import (
	"math"
	"time"

	"github.com/NimbleMarkets/ntcharts/linechart/timeserieslinechart"
	"github.com/charmbracelet/lipgloss"
)

// TimeSeriesLineChart is a custom line chart for time-based data.
//
// Used to display the system metrics.
//
// A single TimeSeriesLineChart can contain and display multiple related series.
type TimeSeriesLineChart struct {
	chart  *timeserieslinechart.Model
	def    *MetricDef
	series map[string]struct{}

	// colorProvider yields the next color for additional series on this chart.
	// It is anchored to the chart's base color so multi-series colors are stable per chart.
	colorProvider func() lipgloss.AdaptiveColor

	lastUpdate         time.Time
	minValue, maxValue float64
}

type TimeSeriesLineChartParams struct {
	Width, Height int
	Def           *MetricDef
	BaseColor     lipgloss.AdaptiveColor
	ColorProvider func() lipgloss.AdaptiveColor
	Now           time.Time
}

func NewTimeSeriesLineChart(params *TimeSeriesLineChartParams) *TimeSeriesLineChart {
	graphStyle := lipgloss.NewStyle().Foreground(params.BaseColor)

	// Show the most recent 10 minutes (slight look-back).
	// TODO: make this configurable.
	minTime := params.Now.Add(-10 * time.Minute)

	chart := timeserieslinechart.New(
		params.Width, params.Height,
		timeserieslinechart.WithTimeRange(minTime, params.Now),
		timeserieslinechart.WithYRange(params.Def.MinY, params.Def.MaxY),
		timeserieslinechart.WithAxesStyles(axisStyle, labelStyle),
		timeserieslinechart.WithStyle(graphStyle),
		timeserieslinechart.WithUpdateHandler(timeserieslinechart.SecondUpdateHandler(1)),
		timeserieslinechart.WithXLabelFormatter(timeserieslinechart.HourTimeLabelFormatter()),
		timeserieslinechart.WithYLabelFormatter(func(i int, v float64) string {
			return params.Def.Unit.Format(v)
		}),
		timeserieslinechart.WithXYSteps(2, 3),
	)

	return &TimeSeriesLineChart{
		chart:         &chart,
		def:           params.Def,
		series:        make(map[string]struct{}),
		colorProvider: params.ColorProvider,
		lastUpdate:    params.Now,
		minValue:      math.Inf(1),
		maxValue:      math.Inf(-1),
	}
}

// AddDataPoint adds a data point to this chart, creating series as needed.
func (c *TimeSeriesLineChart) AddDataPoint(
	seriesName string,
	timestamp int64,
	value float64,
) {
	c.ensureSeries(seriesName)
	c.addDataPoint(seriesName, timestamp, value)
	c.updateRanges(timestamp)
	c.draw(seriesName)
}

// ensureSeries creates a new series if it doesn't exist.
func (c *TimeSeriesLineChart) ensureSeries(seriesName string) {
	if seriesName == DefaultSystemMetricSeriesName {
		return
	}

	if _, exists := c.series[seriesName]; exists {
		return
	}

	// The first dataset uses the chart's base color set at chart creation.
	// Additional datasets advance the palette via the chart-local provider,
	// which is anchored to the base color.
	if len(c.series) > 0 {
		seriesStyle := lipgloss.NewStyle().Foreground(c.colorProvider())
		c.chart.SetDataSetStyle(seriesName, seriesStyle)
	}

	c.series[seriesName] = struct{}{}
}

// addDataPoint adds a single data point to the appropriate series on the chart.
func (c *TimeSeriesLineChart) addDataPoint(seriesName string, timestamp int64, value float64) {
	// Track min/max for auto-ranging
	if value < c.minValue {
		c.minValue = value
	}
	if value > c.maxValue {
		c.maxValue = value
	}

	timePoint := timeserieslinechart.TimePoint{
		Time:  time.Unix(timestamp, 0),
		Value: value,
	}

	if seriesName == DefaultSystemMetricSeriesName {
		c.chart.Push(timePoint)
	} else {
		c.chart.PushDataSet(seriesName, timePoint)
	}

	c.lastUpdate = time.Unix(timestamp, 0)
}

// updateRanges updates the chart's time and Y ranges.
func (c *TimeSeriesLineChart) updateRanges(timestamp int64) {
	c.updateTimeRange(timestamp)
	c.updateYRange()
}

// updateTimeRange updates the chart's time range.
//
// TODO: make this configurable.
func (c *TimeSeriesLineChart) updateTimeRange(timestamp int64) {
	minTime := time.Unix(timestamp, 0).Add(-10 * time.Minute)
	maxTime := time.Unix(timestamp, 0).Add(10 * time.Second)
	c.chart.SetTimeRange(minTime, maxTime)
	c.chart.SetViewTimeRange(minTime, maxTime)
}

// updateYRange updates the chart's Y range if auto-ranging is enabled.
func (c *TimeSeriesLineChart) updateYRange() {
	if !c.def.AutoRange || c.def.Percentage {
		return
	}

	valueRange := c.maxValue - c.minValue
	if valueRange == 0 {
		valueRange = math.Abs(c.maxValue) * 0.1
		if valueRange == 0 {
			valueRange = 1
		}
	}
	padding := valueRange * 0.1

	newMinY := c.minValue - padding
	newMaxY := c.maxValue + padding

	// Don't go negative for non-negative data.
	if c.minValue >= 0 && newMinY < 0 {
		newMinY = 0
	}

	c.chart.SetYRange(newMinY, newMaxY)
	c.chart.SetViewYRange(newMinY, newMaxY)
}

// draw renders the chart if dimensions are valid.
func (c *TimeSeriesLineChart) draw(seriesName string) {
	if !c.isDrawable() {
		return
	}

	if seriesName == DefaultSystemMetricSeriesName {
		c.chart.DrawBraille()
	} else {
		c.chart.DrawBrailleAll()
	}
}

// isDrawable checks if the chart has valid dimensions for drawing.
func (c *TimeSeriesLineChart) isDrawable() bool {
	return c.chart.Width() > 0 &&
		c.chart.Height() > 0 &&
		c.chart.GraphWidth() > 0 &&
		c.chart.GraphHeight() > 0
}

// Title returns the title including unit (e.g., "CPU (%)").
func (c *TimeSeriesLineChart) Title() string { return c.def.Title() }

// LastUpdate returns the timestamp of the most recent sample seen.
func (c *TimeSeriesLineChart) LastUpdate() time.Time { return c.lastUpdate }

// ValueBounds returns the observed [min,max] values tracked for auto-ranging.
func (c *TimeSeriesLineChart) ValueBounds() (float64, float64) { return c.minValue, c.maxValue }
