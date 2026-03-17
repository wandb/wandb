package leet

import (
	"fmt"
	"math"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
)

const (
	minSystemMetricsRightPad      = 2 * time.Second
	maxSystemMetricsRightPad      = 10 * time.Second
	preferredSystemTimeLabelWidth = len("15:04")
)

// TimeSeriesLineChart is a time-based system metrics chart.
//
// It reuses EpochLineChart's custom multi-series rendering and inspection
// behavior while adding live-tail windowing semantics for timestamped data.
//
// A single chart can contain multiple related series (for example GPU 0 / GPU 1).
// By default the chart auto-trails the most recent data using tailWindow.
// Users can zoom out to show the entire history; if the latest point remains
// visible after a zoom operation, the view continues trailing live updates.
type TimeSeriesLineChart struct {
	*EpochLineChart

	def *MetricDef

	// series tracks named (non-default) series for display purposes.
	series map[string]struct{}

	// seriesColors stores the assigned color for each underlying series key.
	seriesColors map[string]compat.AdaptiveColor
	baseColor    compat.AdaptiveColor

	// colorProvider yields the next color for additional series on this chart.
	// It is anchored to the chart's base color so multi-series colors are stable per chart.
	colorProvider func() compat.AdaptiveColor

	tailWindow time.Duration
	viewWindow time.Duration

	viewInitialized bool
	autoTrail       bool
	showAll         bool

	lastUpdate         time.Time
	minValue, maxValue float64
}

type TimeSeriesLineChartParams struct {
	Width, Height int
	Def           *MetricDef
	BaseColor     compat.AdaptiveColor
	ColorProvider func() compat.AdaptiveColor
	Now           time.Time
}

func NewTimeSeriesLineChart(params *TimeSeriesLineChartParams) *TimeSeriesLineChart {
	tailWindow := time.Duration(DefaultSystemTailWindowMins) * time.Minute

	baseChart := NewEpochLineChart(params.Def.Title())
	chart := &TimeSeriesLineChart{
		EpochLineChart: baseChart,
		def:            params.Def,
		series:         make(map[string]struct{}),
		seriesColors:   make(map[string]compat.AdaptiveColor),
		baseColor:      params.BaseColor,
		colorProvider:  params.ColorProvider,
		tailWindow:     tailWindow,
		viewWindow:     tailWindow,
		autoTrail:      true,
		lastUpdate:     params.Now,
		minValue:       math.Inf(1),
		maxValue:       math.Inf(-1),
	}

	chart.XLabelFormatter = func(_ int, v float64) string {
		return chart.formatXAxisTick(v, chart.maxXLabelWidth())
	}
	chart.YLabelFormatter = func(_ int, v float64) string {
		return params.Def.Unit.Format(v)
	}
	chart.SetInspectionLabelFormatter(chart.formatInspectionLabel)
	chart.Resize(params.Width, params.Height)

	return chart
}

// SetTailWindow updates the default live tail window.
func (c *TimeSeriesLineChart) SetTailWindow(window time.Duration) {
	c.tailWindow = window
	if !c.viewInitialized || c.autoTrail {
		c.viewWindow = window
	}
	c.applyRanges()
}

// AddDataPoint adds a data point to this chart, creating series as needed.
func (c *TimeSeriesLineChart) AddDataPoint(seriesName string, timestamp int64, value float64) {
	seriesKey := c.ensureSeries(seriesName)
	pointTime := time.Unix(timestamp, 0)
	c.lastUpdate = pointTime

	if value < c.minValue {
		c.minValue = value
	}
	if value > c.maxValue {
		c.maxValue = value
	}

	c.AddData(seriesKey, MetricData{
		X: []float64{float64(timestamp)},
		Y: []float64{value},
	})

	style := lipgloss.NewStyle().Foreground(c.seriesColors[seriesKey])
	c.SetSeriesStyle(seriesKey, &style)
	c.applyRanges()
}

// Resize updates the underlying chart size and reapplies the current view policy.
func (c *TimeSeriesLineChart) Resize(width, height int) {
	c.EpochLineChart.Resize(width, height)
	c.applyRanges()
}

// HandleZoom updates the current time window and live-trailing state.
func (c *TimeSeriesLineChart) HandleZoom(direction string, mouseX int) {
	c.EpochLineChart.HandleZoom(direction, mouseX)
	c.viewInitialized = true
	c.reconcileViewState()
}

// ViewModeLabel returns a short description of the current X-axis mode.
func (c *TimeSeriesLineChart) ViewModeLabel() string {
	if c == nil {
		return ""
	}
	if c.showAll {
		return "all history"
	}

	window := c.viewWindow
	if window <= 0 {
		window = c.tailWindow
	}
	window = window.Round(time.Second)

	if c.autoTrail {
		return "live tail " + compactDuration(window)
	}
	return "frozen " + compactDuration(window)
}

// LastUpdate returns the timestamp of the most recent sample seen.
func (c *TimeSeriesLineChart) LastUpdate() time.Time { return c.lastUpdate }

// ValueBounds returns the observed [min,max] values tracked for auto-ranging.
func (c *TimeSeriesLineChart) ValueBounds() (minValue, maxValue float64) {
	return c.minValue, c.maxValue
}

func (c *TimeSeriesLineChart) ensureSeries(seriesName string) string {
	seriesKey := seriesName
	if seriesKey == "" {
		seriesKey = DefaultSystemMetricSeriesName
	}
	if _, ok := c.seriesColors[seriesKey]; ok {
		return seriesKey
	}

	color := c.baseColor
	if seriesKey != DefaultSystemMetricSeriesName {
		if len(c.series) > 0 {
			color = c.nextSeriesColor()
		}
		c.series[seriesKey] = struct{}{}
	}
	c.seriesColors[seriesKey] = color
	return seriesKey
}

func (c *TimeSeriesLineChart) nextSeriesColor() compat.AdaptiveColor {
	if c.colorProvider == nil {
		return c.baseColor
	}
	return c.colorProvider()
}

func (c *TimeSeriesLineChart) applyRanges() {
	if c.SeriesCount() == 0 {
		return
	}

	dataMin := c.xMin
	dataMax := c.xMax
	if !isFinite(dataMin) || !isFinite(dataMax) {
		return
	}

	yMin, yMax := c.computeYRange()
	c.SetYRange(yMin, yMax)
	if c.isYZoomed {
		c.clampYView(yMin, yMax)
	} else {
		c.SetViewYRange(yMin, yMax)
	}

	domainMax := dataMax + c.rightPad().Seconds()
	if domainMax-dataMin < minZoomRange {
		domainMax = dataMin + minZoomRange
	}
	c.SetXRange(dataMin, domainMax)

	switch {
	case c.showAll:
		c.SetViewXRange(dataMin, domainMax)
		c.userViewMinX = dataMin
		c.userViewMaxX = domainMax
	case !c.viewInitialized || c.autoTrail:
		window := c.viewWindow.Seconds()
		if !c.viewInitialized || window <= 0 {
			window = c.tailWindow.Seconds()
		}
		if window < minZoomRange {
			window = minZoomRange
		}
		c.snapViewToTail(window, dataMin, domainMax)
		c.viewInitialized = true
	default:
		c.clampUserView(dataMin, domainMax)
	}

	c.SetXYRange(c.MinX(), c.MaxX(), yMin, yMax)
	if c.inspection.Active {
		c.refreshInspectionAfterViewChange()
	}
	c.dirty = true
}

func (c *TimeSeriesLineChart) computeYRange() (float64, float64) {
	if !c.def.AutoRange || c.def.Percentage || !isFinite(c.minValue) || !isFinite(c.maxValue) {
		return c.def.MinY, c.def.MaxY
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
	if c.minValue >= 0 && newMinY < 0 {
		newMinY = 0
	}
	return newMinY, newMaxY
}

func (c *TimeSeriesLineChart) rightPad() time.Duration {
	pad := min(max(c.tailWindow/60, minSystemMetricsRightPad), maxSystemMetricsRightPad)
	return pad
}

func (c *TimeSeriesLineChart) snapViewToTail(window, dataMin, domainMax float64) {
	if window <= 0 {
		window = max(c.tailWindow.Seconds(), minZoomRange)
	}
	viewMax := domainMax
	viewMin := max(viewMax-window, dataMin)
	c.SetViewXRange(viewMin, viewMax)
	c.userViewMinX = viewMin
	c.userViewMaxX = viewMax
}

func (c *TimeSeriesLineChart) clampUserView(dataMin, domainMax float64) {
	viewMin := c.userViewMinX
	viewMax := c.userViewMaxX
	viewRange := viewMax - viewMin
	if viewRange <= 0 {
		c.autoTrail = true
		window := c.viewWindow.Seconds()
		if window <= 0 {
			window = c.tailWindow.Seconds()
		}
		c.snapViewToTail(window, dataMin, domainMax)
		return
	}

	if viewMin < dataMin {
		viewMax += dataMin - viewMin
		viewMin = dataMin
	}
	if viewMax > domainMax {
		viewMin -= viewMax - domainMax
		viewMax = domainMax
		if viewMin < dataMin {
			viewMin = dataMin
		}
	}

	c.SetViewXRange(viewMin, viewMax)
	c.userViewMinX = viewMin
	c.userViewMaxX = viewMax
}

func (c *TimeSeriesLineChart) reconcileViewState() {
	if c.SeriesCount() == 0 {
		return
	}

	dataMin := c.xMin
	dataMax := c.xMax
	if !isFinite(dataMin) || !isFinite(dataMax) {
		return
	}

	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin
	if viewRange <= 0 {
		return
	}

	eps := max(c.pixelEpsX(viewRange)*2, 1)
	fullRange := c.MaxX() - dataMin

	c.showAll = fullRange > 0 && viewRange >= fullRange-eps
	c.autoTrail = viewMax >= dataMax-eps
	if c.showAll {
		c.autoTrail = true
	}

	c.viewWindow = time.Duration(math.Round(viewRange)) * time.Second
	if c.viewWindow < time.Duration(minZoomRange)*time.Second {
		c.viewWindow = time.Duration(minZoomRange) * time.Second
	}

	if c.showAll {
		c.userViewMinX = dataMin
		c.userViewMaxX = c.MaxX()
		return
	}
	if c.autoTrail {
		c.snapViewToTail(viewRange, dataMin, c.MaxX())
		return
	}

	c.userViewMinX = c.ViewMinX()
	c.userViewMaxX = c.ViewMaxX()
}

func (c *TimeSeriesLineChart) formatXAxisTick(v float64, maxWidth int) string {
	if !isFinite(v) {
		return ""
	}

	ts := time.Unix(int64(math.Round(v)), 0).Local()
	span := time.Duration(math.Round(c.ViewMaxX()-c.ViewMinX())) * time.Second
	layouts := systemTimeLayouts(span)

	if c.shouldUseEndpointLabels(maxWidth) {
		if !c.isEndpointTick(v) {
			return ""
		}
		maxWidth = c.endpointXLabelWidth()
	}
	if maxWidth <= 0 {
		maxWidth = preferredSystemTimeLabelWidth
	}

	return fitTimeLayouts(ts, maxWidth, layouts)
}

func systemTimeLayouts(span time.Duration) []string {
	switch {
	case span >= 48*time.Hour:
		return []string{"Jan 2 15:04", "Jan 2", "01/02", "0102"}
	case span >= time.Hour:
		return []string{"15:04", "1504"}
	default:
		return []string{"15:04:05", "15:04", "1504"}
	}
}

func (c *TimeSeriesLineChart) shouldUseEndpointLabels(maxWidth int) bool {
	return maxWidth > 0 && maxWidth < preferredSystemTimeLabelWidth && c.endpointXLabelWidth() > 0
}

func (c *TimeSeriesLineChart) endpointXLabelWidth() int {
	if c.GraphWidth() <= 0 {
		return 0
	}
	return max(c.GraphWidth()/2, 1)
}

func (c *TimeSeriesLineChart) isEndpointTick(v float64) bool {
	viewMin := c.ViewMinX()
	viewMax := c.ViewMaxX()
	viewRange := viewMax - viewMin
	if viewRange <= 0 {
		return true
	}

	eps := max(c.pixelEpsX(viewRange)*2, viewRange/float64(max(c.XStep(), 1))*0.25)
	return math.Abs(v-viewMin) <= eps || math.Abs(v-viewMax) <= eps
}

func (c *TimeSeriesLineChart) formatInspectionLabel(seriesKey string, x, y float64) string {
	ts := time.Unix(int64(math.Round(x)), 0).Local()
	span := time.Duration(math.Round(c.ViewMaxX()-c.ViewMinX())) * time.Second
	layout := "15:04:05"
	if span >= 48*time.Hour {
		layout = "Jan 2 15:04:05"
	}

	label := ts.Format(layout) + " " + c.def.Unit.Format(y)
	if seriesKey == "" || seriesKey == DefaultSystemMetricSeriesName {
		return label
	}
	return fmt.Sprintf("%s: %s", seriesKey, label)
}

func fitTimeLayouts(ts time.Time, maxWidth int, layouts []string) string {
	for _, layout := range layouts {
		formatted := ts.Format(layout)
		if lipgloss.Width(formatted) <= maxWidth {
			return formatted
		}
	}

	formatted := ts.Format(layouts[len(layouts)-1])
	if lipgloss.Width(formatted) <= maxWidth {
		return formatted
	}
	return TruncateTitle(formatted, maxWidth)
}

func compactDuration(d time.Duration) string {
	d = d.Round(time.Second)
	if d <= 0 {
		return "0s"
	}

	if d%time.Hour == 0 {
		return fmt.Sprintf("%dh", int(d/time.Hour))
	}
	if d >= time.Hour {
		hours := int(d / time.Hour)
		minutes := int((d % time.Hour) / time.Minute)
		if minutes == 0 {
			return fmt.Sprintf("%dh", hours)
		}
		return fmt.Sprintf("%dh%dm", hours, minutes)
	}
	if d%time.Minute == 0 {
		return fmt.Sprintf("%dm", int(d/time.Minute))
	}
	if d >= time.Minute {
		minutes := int(d / time.Minute)
		seconds := int((d % time.Minute) / time.Second)
		if seconds == 0 {
			return fmt.Sprintf("%dm", minutes)
		}
		return fmt.Sprintf("%dm%ds", minutes, seconds)
	}
	return fmt.Sprintf("%ds", int(d/time.Second))
}
