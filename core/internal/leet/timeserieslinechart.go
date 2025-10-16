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
type TimeSeriesLineChart struct {
	chart        *timeserieslinechart.Model
	def          *MetricDef
	baseKey      string
	title        string
	fullTitle    string
	series       map[string]int
	seriesColors []string

	// colorProvider yields the next color for additional series on this chart.
	// It is anchored to the chart's base color so multi-series colors are stable per chart.
	colorProvider func() string

	hasData    bool
	lastUpdate time.Time
	minValue   float64
	maxValue   float64
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
	if seriesName == "Default" {
		return
	}

	if _, exists := c.series[seriesName]; exists {
		return
	}

	var color string
	if len(c.series) == 0 {
		// First dataset uses the chart's base color.
		color = c.seriesColors[0]
	} else {
		// Additional datasets advance the palette via the chart-local provider.
		color = c.colorProvider()
		c.seriesColors = append(c.seriesColors, color)
	}
	c.series[seriesName] = len(c.series)
	seriesStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(color))
	c.chart.SetDataSetStyle(seriesName, seriesStyle)
}

// addDataPoint adds a single data point to the chart.
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

	if seriesName == "Default" {
		c.chart.Push(timePoint)
	} else {
		c.chart.PushDataSet(seriesName, timePoint)
	}

	c.hasData = true
	c.lastUpdate = time.Unix(timestamp, 0)
}

// updateRanges updates the chart's time and Y ranges.
func (c *TimeSeriesLineChart) updateRanges(timestamp int64) {
	c.updateTimeRange(timestamp)
	c.updateYRange()
}

// updateTimeRange updates the chart's time range.
func (c *TimeSeriesLineChart) updateTimeRange(timestamp int64) {
	// TODO: make this configurable.
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

	// Don't go negative for non-negative data
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

	if seriesName == "Default" || len(c.series) == 0 {
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
