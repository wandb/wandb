package leet

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"charm.land/lipgloss/v2"
)

const frenchFriesCell = "█"

var frenchFriesPalette = []string{
	"#1A9850",
	"#3EAE51",
	"#67C35C",
	"#97D168",
	"#C8DE72",
	"#F1DD6B",
	"#FDB863",
	"#F89C5A",
	"#F67C4B",
	"#E85D4F",
	"#D73027",
}

type frenchFriesSample struct {
	timestamp int64
	values    map[string]float64
}

type frenchFriesInspection struct {
	active     bool
	mouseX     int
	mouseY     int
	dataX      float64
	dataY      float64
	seriesName string
}

type frenchFriesRowBand struct {
	seriesName string
	label      string
	startY     int
	height     int
}

func (b frenchFriesRowBand) centerY() int {
	if b.height <= 0 {
		return b.startY
	}
	return b.startY + (b.height-1)/2
}

type frenchFriesLayout struct {
	labelWidth     int
	plotStartX     int
	plotStartY     int
	plotWidth      int
	plotHeight     int
	timeAxisY      int
	maxVisibleRows int
	bands          []frenchFriesRowBand
}

func (l frenchFriesLayout) bandAt(y int) (frenchFriesRowBand, bool) {
	for _, band := range l.bands {
		if y >= band.startY && y < band.startY+band.height {
			return band, true
		}
	}
	return frenchFriesRowBand{}, false
}

func (l frenchFriesLayout) bandForSeries(seriesName string) (frenchFriesRowBand, bool) {
	for _, band := range l.bands {
		if band.seriesName == seriesName {
			return band, true
		}
	}
	return frenchFriesRowBand{}, false
}

type frenchFriesBucketCell struct {
	timestamp int64
	value     float64
	ok        bool
}

// FrenchFriesChart renders one row per series and compresses the visible time
// window into color-coded buckets, producing a compact heatmap.
type FrenchFriesChart struct {
	def *MetricDef

	width  int
	height int

	// historyCap tracks the widest chart width observed so we can preserve enough
	// recent history when the chart later expands again.
	historyCap int
	samples    []frenchFriesSample

	series        map[string]struct{}
	orderedSeries []string
	seriesDirty   bool

	lastUpdate time.Time
	viewMinX   float64
	viewMaxX   float64
	viewReady  bool

	inspection frenchFriesInspection

	dirty    bool
	rendered string

	coloredCells []string
}

type FrenchFriesChartParams struct {
	Width, Height int
	Def           *MetricDef
	Now           time.Time
}

func NewFrenchFriesChart(params *FrenchFriesChartParams) *FrenchFriesChart {
	chart := &FrenchFriesChart{
		def:          params.Def,
		series:       make(map[string]struct{}),
		seriesDirty:  true,
		lastUpdate:   params.Now,
		dirty:        true,
		coloredCells: make([]string, len(frenchFriesPalette)),
	}

	for i, hex := range frenchFriesPalette {
		chart.coloredCells[i] = lipgloss.NewStyle().
			Foreground(lipgloss.Color(hex)).Render(frenchFriesCell)
	}

	chart.Resize(params.Width, params.Height)
	return chart
}

func (c *FrenchFriesChart) Title() string { return c.def.Title() }

func (c *FrenchFriesChart) TitleDetail() string {
	series := c.sortedSeriesNames()
	total := len(series)
	if total <= 1 {
		return ""
	}

	layout := c.layout()
	if layout.maxVisibleRows <= 0 || total <= layout.maxVisibleRows {
		return fmt.Sprintf("[%d]", total)
	}

	return summarizeFrenchFriesSeries(c.visibleSeriesNames(layout.maxVisibleRows), total)
}

func (c *FrenchFriesChart) View() string {
	c.DrawIfNeeded()
	return c.rendered
}

func (c *FrenchFriesChart) Resize(width, height int) {
	width = max(width, 0)
	height = max(height, 0)
	if c.width == width && c.height == height {
		return
	}

	c.width = width
	c.height = height
	if c.width > c.historyCap {
		c.historyCap = c.width
	}
	c.trimHistory()
	c.dirty = true
}

func (c *FrenchFriesChart) DrawIfNeeded() {
	if c.dirty {
		c.draw()
	}
}

func (c *FrenchFriesChart) AddDataPoint(seriesName string, timestamp int64, value float64) {
	if seriesName == "" {
		seriesName = DefaultSystemMetricSeriesName
	}
	if _, ok := c.series[seriesName]; !ok {
		c.series[seriesName] = struct{}{}
		c.seriesDirty = true
	}

	if len(c.samples) == 0 || c.samples[len(c.samples)-1].timestamp != timestamp {
		c.samples = append(c.samples, frenchFriesSample{
			timestamp: timestamp,
			values:    make(map[string]float64),
		})
	}
	c.samples[len(c.samples)-1].values[seriesName] = value
	c.lastUpdate = time.Unix(timestamp, 0)

	if !c.viewReady {
		c.setDefaultViewWindow()
	}

	c.trimHistory()
	c.dirty = true
}

func (c *FrenchFriesChart) GraphWidth() int {
	return c.layout().plotWidth
}

func (c *FrenchFriesChart) GraphHeight() int {
	return c.layout().plotHeight
}

func (c *FrenchFriesChart) GraphStartX() int {
	return 1 + c.layout().plotStartX
}

func (c *FrenchFriesChart) GraphStartY() int {
	return 1 + ChartTitleHeight + c.layout().plotStartY
}

func (c *FrenchFriesChart) HandleZoom(string, int) {}

func (c *FrenchFriesChart) ToggleYScale() bool { return false }
func (c *FrenchFriesChart) IsLogY() bool       { return false }

func (c *FrenchFriesChart) SupportsHeatmap() bool { return true }

func (c *FrenchFriesChart) ToggleHeatmapMode() bool { return false }

func (c *FrenchFriesChart) IsHeatmapMode() bool { return true }

func (c *FrenchFriesChart) ViewModeLabel() string {
	viewMinX, viewMaxX := c.effectiveViewWindow()
	span := viewMaxX - viewMinX
	if span > 0 {
		return "window " + compactDuration(time.Duration(math.Round(span))*time.Second)
	}
	visible := min(len(c.samples), c.GraphWidth())
	if visible <= 0 {
		return "heatmap"
	}
	return fmt.Sprintf("heatmap %d samples", visible)
}

func (c *FrenchFriesChart) ScaleLabel() string { return "heatmap" }

// SetViewWindow updates the time window used to bucket samples into columns.
func (c *FrenchFriesChart) SetViewWindow(minX, maxX float64) {
	if !isFinite(minX) || !isFinite(maxX) || maxX <= minX {
		c.setDefaultViewWindow()
		return
	}
	if c.viewReady && c.viewMinX == minX && c.viewMaxX == maxX {
		return
	}
	c.viewMinX = minX
	c.viewMaxX = maxX
	c.viewReady = true
	c.dirty = true
	if c.inspection.active {
		c.inspectSeriesAtDataX(c.inspection.seriesName, c.inspection.dataX)
	}
}

func (c *FrenchFriesChart) StartInspectionAt(mouseX, mouseY int) {
	if c.GraphWidth() <= 0 || c.GraphHeight() <= 0 {
		return
	}
	c.inspection.active = true
	c.UpdateInspectionAt(mouseX, mouseY)
}

func (c *FrenchFriesChart) UpdateInspectionAt(mouseX, mouseY int) {
	if !c.inspection.active {
		return
	}

	layout := c.layout()
	if layout.plotWidth <= 0 || layout.plotHeight <= 0 || len(layout.bands) == 0 {
		return
	}

	clampedX := max(0, min(layout.plotWidth-1, mouseX))
	clampedY := max(0, min(layout.plotHeight-1, mouseY))
	band, ok := layout.bandAt(clampedY)
	if !ok {
		return
	}

	targetX := c.dataXForMouse(clampedX, layout.plotWidth)
	if !c.inspectSeriesAtDataX(band.seriesName, targetX) {
		return
	}
	c.inspection.mouseY = clampedY
}

func (c *FrenchFriesChart) EndInspection() {
	c.inspection = frenchFriesInspection{}
	c.dirty = true
}

func (c *FrenchFriesChart) IsInspecting() bool { return c.inspection.active }

func (c *FrenchFriesChart) InspectAtDataX(targetX float64) {
	seriesName := c.inspection.seriesName
	if seriesName == "" {
		layout := c.layout()
		if len(layout.bands) == 0 {
			return
		}
		seriesName = layout.bands[0].seriesName
	}
	c.inspection.active = true
	c.inspectSeriesAtDataX(seriesName, targetX)
}

func (c *FrenchFriesChart) InspectionData() (float64, float64, bool) {
	return c.inspection.dataX, c.inspection.dataY, c.inspection.active
}

func (c *FrenchFriesChart) draw() {
	if c.width <= 0 || c.height <= 0 {
		c.rendered = ""
		c.dirty = false
		return
	}

	layout := c.layout()
	cells := make([][]string, c.height)
	for y := range cells {
		cells[y] = make([]string, c.width)
		for x := range cells[y] {
			cells[y][x] = " "
		}
	}

	bucketed := c.bucketedSeries(layout)
	selectedBucket := -1
	selectedSeries := ""
	if c.inspection.active {
		selectedBucket = c.bucketForDataX(c.inspection.dataX, layout.plotWidth)
		selectedSeries = c.inspection.seriesName
	}

	for _, band := range layout.bands {
		for y := band.startY; y < band.startY+band.height; y++ {
			for x := 0; x < layout.plotWidth; x++ {
				cell := " "
				if bucket := bucketed[band.seriesName][x]; bucket.ok {
					cell = c.colorForValue(bucket.value)
					if c.inspection.active &&
						band.seriesName == selectedSeries && x == selectedBucket {
						cell = lipgloss.NewStyle().Reverse(true).Render(cell)
					}
				}
				cells[y][layout.plotStartX+x] = cell
			}
		}

		c.renderBandLabel(cells, layout, band)
	}

	c.renderInspectionLabel(cells, layout)
	c.renderTimeLabels(cells, layout)

	lines := make([]string, len(cells))
	for y := range cells {
		lines[y] = strings.Join(cells[y], "")
	}
	c.rendered = strings.Join(lines, "\n")
	c.dirty = false
}

func (c *FrenchFriesChart) renderBandLabel(
	cells [][]string,
	layout frenchFriesLayout,
	band frenchFriesRowBand,
) {
	if layout.labelWidth <= 0 || band.label == "" {
		return
	}
	row := band.centerY()
	label := band.label
	if lipgloss.Width(label) > layout.labelWidth-1 {
		label = TruncateTitle(label, layout.labelWidth-1)
	}
	start := max(layout.labelWidth-1-lipgloss.Width(label), 0)
	for i, r := range label {
		if start+i >= layout.labelWidth-1 {
			break
		}
		cells[row][start+i] = string(r)
	}
}

func (c *FrenchFriesChart) renderInspectionLabel(cells [][]string, layout frenchFriesLayout) {
	if !c.inspection.active || layout.plotWidth <= 0 || layout.plotHeight <= 0 {
		return
	}
	band, ok := layout.bandForSeries(c.inspection.seriesName)
	if !ok {
		return
	}

	row := band.centerY()
	label := c.inspectionLabel(layout.plotWidth)
	if label == "" {
		return
	}

	startX := layout.plotStartX + selectedLabelStartX(c.inspection.mouseX, layout.plotWidth, lipgloss.Width(label))
	for i, r := range label {
		x := startX + i
		if x < layout.plotStartX || x >= layout.plotStartX+layout.plotWidth {
			continue
		}
		cells[row][x] = lipgloss.NewStyle().Bold(true).Render(string(r))
	}
}

func selectedLabelStartX(mouseX, plotWidth, labelWidth int) int {
	if labelWidth <= 0 || plotWidth <= 0 {
		return 0
	}
	start := mouseX + 1
	if start+labelWidth > plotWidth {
		start = max(mouseX-labelWidth, 0)
	}
	return max(0, min(start, max(plotWidth-labelWidth, 0)))
}

func (c *FrenchFriesChart) renderTimeLabels(cells [][]string, layout frenchFriesLayout) {
	if layout.timeAxisY < 0 || layout.plotWidth <= 0 || c.height <= 0 {
		return
	}
	viewMinX, viewMaxX := c.effectiveViewWindow()
	if viewMaxX <= viewMinX {
		return
	}

	y := layout.timeAxisY
	span := time.Duration(math.Round(viewMaxX-viewMinX)) * time.Second
	layouts := systemTimeLayouts(span)

	labels := []struct {
		text string
		pos  int
	}{
		{text: fitTimeLayouts(time.Unix(int64(math.Round(viewMinX)), 0).Local(), layout.plotWidth, layouts), pos: 0},
		{text: fitTimeLayouts(time.Unix(int64(math.Round(viewMaxX)), 0).Local(), layout.plotWidth, layouts), pos: max(layout.plotWidth-len([]rune(fitTimeLayouts(time.Unix(int64(math.Round(viewMaxX)), 0).Local(), layout.plotWidth, layouts))), 0)},
	}

	midX := (viewMinX + viewMaxX) / 2
	midText := fitTimeLayouts(time.Unix(int64(math.Round(midX)), 0).Local(), layout.plotWidth, layouts)
	midPos := max(layout.plotWidth/2-lipgloss.Width(midText)/2, 0)
	if midText != "" && layout.plotWidth >= lipgloss.Width(midText)*3 {
		labels = append(labels, struct {
			text string
			pos  int
		}{text: midText, pos: midPos})
	}

	for _, label := range labels {
		for i, r := range label.text {
			x := layout.plotStartX + label.pos + i
			if x < layout.plotStartX || x >= c.width {
				continue
			}
			cells[y][x] = string(r)
		}
	}
}

func (c *FrenchFriesChart) inspectionLabel(maxWidth int) string {
	if !c.inspection.active {
		return ""
	}
	span := time.Duration(math.Round(c.viewMaxX-c.viewMinX)) * time.Second
	layouts := systemTimeLayouts(span)
	timeLabel := fitTimeLayouts(
		time.Unix(int64(math.Round(c.inspection.dataX)), 0).Local(),
		maxWidth,
		layouts,
	)
	valueLabel := c.def.Unit.Format(c.inspection.dataY)
	seriesLabel := compactSystemMetricSeriesLabel(c.inspection.seriesName)
	parts := make([]string, 0, 3)
	if seriesLabel != "" {
		parts = append(parts, seriesLabel)
	}
	if timeLabel != "" {
		parts = append(parts, timeLabel)
	}
	parts = append(parts, valueLabel)
	label := strings.Join(parts, " ")
	if lipgloss.Width(label) > maxWidth {
		return TruncateTitle(label, maxWidth)
	}
	return label
}

func (c *FrenchFriesChart) layout() frenchFriesLayout {
	layout := frenchFriesLayout{plotStartY: 0, timeAxisY: -1}
	if c.width <= 0 || c.height <= 0 {
		return layout
	}

	timeAxisRows := 0
	if c.height >= 2 {
		timeAxisRows = 1
		layout.timeAxisY = c.height - 1
	}
	layout.plotHeight = max(c.height-timeAxisRows, 0)
	layout.maxVisibleRows = layout.plotHeight
	visibleSeries := c.visibleSeriesNames(layout.maxVisibleRows)
	layout.bands = make([]frenchFriesRowBand, 0, len(visibleSeries))

	maxLabelWidth := 0
	labels := make([]string, len(visibleSeries))
	for i, name := range visibleSeries {
		labels[i] = compactSystemMetricSeriesLabel(name)
		maxLabelWidth = max(maxLabelWidth, lipgloss.Width(labels[i]))
	}
	if maxLabelWidth > 0 && c.width >= maxLabelWidth+2 {
		layout.labelWidth = maxLabelWidth + 1
	}
	layout.plotStartX = layout.labelWidth
	layout.plotWidth = max(c.width-layout.plotStartX, 0)
	if layout.plotWidth == 0 {
		layout.labelWidth = 0
		layout.plotStartX = 0
		layout.plotWidth = c.width
	}

	if len(visibleSeries) == 0 || layout.plotHeight <= 0 {
		return layout
	}

	baseBandHeight := max(layout.plotHeight/len(visibleSeries), 1)
	extraRows := max(layout.plotHeight-len(visibleSeries)*baseBandHeight, 0)
	y := 0
	for i, name := range visibleSeries {
		bandHeight := baseBandHeight
		if i < extraRows {
			bandHeight++
		}
		layout.bands = append(layout.bands, frenchFriesRowBand{
			seriesName: name,
			label:      labels[i],
			startY:     y,
			height:     bandHeight,
		})
		y += bandHeight
	}
	return layout
}

func (c *FrenchFriesChart) bucketedSeries(layout frenchFriesLayout) map[string][]frenchFriesBucketCell {
	bucketed := make(map[string][]frenchFriesBucketCell, len(layout.bands))
	for _, band := range layout.bands {
		bucketed[band.seriesName] = make([]frenchFriesBucketCell, layout.plotWidth)
	}
	if layout.plotWidth <= 0 {
		return bucketed
	}

	viewMinX, viewMaxX := c.effectiveViewWindow()
	if viewMaxX <= viewMinX {
		return bucketed
	}

	for _, sample := range c.samples {
		ts := float64(sample.timestamp)
		if ts < viewMinX || ts > viewMaxX {
			continue
		}
		bucket := c.bucketForDataX(ts, layout.plotWidth)
		for seriesName, value := range sample.values {
			cells, ok := bucketed[seriesName]
			if !ok {
				continue
			}
			if !cells[bucket].ok || sample.timestamp >= cells[bucket].timestamp {
				cells[bucket] = frenchFriesBucketCell{timestamp: sample.timestamp, value: value, ok: true}
			}
		}
	}

	return bucketed
}

func (c *FrenchFriesChart) colorForValue(value float64) string {
	if !isFinite(value) {
		return " "
	}

	minY := c.def.MinY
	maxY := c.def.MaxY
	if maxY <= minY {
		minY = 0
		maxY = 100
	}

	normalized := (value - minY) / (maxY - minY)
	normalized = max(0, min(1, normalized))
	idx := int(math.Round(normalized * float64(len(c.coloredCells)-1)))
	return c.coloredCells[idx]
}

func (c *FrenchFriesChart) trimHistory() {
	if c.historyCap <= 0 || len(c.samples) <= c.historyCap {
		return
	}

	trimmed := make([]frenchFriesSample, c.historyCap)
	copy(trimmed, c.samples[len(c.samples)-c.historyCap:])
	c.samples = trimmed
}

func (c *FrenchFriesChart) setDefaultViewWindow() {
	if len(c.samples) == 0 {
		c.viewReady = false
		return
	}
	minX := float64(c.samples[0].timestamp)
	maxX := float64(c.samples[len(c.samples)-1].timestamp)
	if maxX <= minX {
		maxX = minX + 1
	}
	c.viewMinX = minX
	c.viewMaxX = maxX
	c.viewReady = true
}

func (c *FrenchFriesChart) effectiveViewWindow() (float64, float64) {
	if c.viewReady && c.viewMaxX > c.viewMinX {
		return c.viewMinX, c.viewMaxX
	}
	c.setDefaultViewWindow()
	return c.viewMinX, c.viewMaxX
}

func (c *FrenchFriesChart) dataXForMouse(mouseX, plotWidth int) float64 {
	viewMinX, viewMaxX := c.effectiveViewWindow()
	if plotWidth <= 1 || viewMaxX <= viewMinX {
		return viewMinX
	}
	frac := float64(max(0, min(plotWidth-1, mouseX))) / float64(max(plotWidth-1, 1))
	return viewMinX + frac*(viewMaxX-viewMinX)
}

func (c *FrenchFriesChart) bucketForDataX(dataX float64, plotWidth int) int {
	viewMinX, viewMaxX := c.effectiveViewWindow()
	if plotWidth <= 1 || viewMaxX <= viewMinX {
		return 0
	}
	if dataX <= viewMinX {
		return 0
	}
	if dataX >= viewMaxX {
		return plotWidth - 1
	}
	frac := (dataX - viewMinX) / (viewMaxX - viewMinX)
	bucket := int(math.Round(frac * float64(plotWidth-1)))
	return max(0, min(plotWidth-1, bucket))
}

func (c *FrenchFriesChart) inspectSeriesAtDataX(seriesName string, targetX float64) bool {
	dataX, dataY, ok := c.nearestSample(seriesName, targetX)
	if !ok {
		return false
	}

	layout := c.layout()
	band, ok := layout.bandForSeries(seriesName)
	if !ok {
		return false
	}

	c.inspection.active = true
	c.inspection.seriesName = seriesName
	c.inspection.dataX = dataX
	c.inspection.dataY = dataY
	c.inspection.mouseX = c.bucketForDataX(dataX, layout.plotWidth)
	c.inspection.mouseY = band.centerY()
	c.dirty = true
	return true
}

func (c *FrenchFriesChart) nearestSample(seriesName string, targetX float64) (dataX, dataY float64, ok bool) {
	viewMinX, viewMaxX := c.effectiveViewWindow()
	bestDist := math.Inf(1)
	for _, sample := range c.samples {
		value, exists := sample.values[seriesName]
		if !exists {
			continue
		}
		ts := float64(sample.timestamp)
		if ts < viewMinX || ts > viewMaxX {
			continue
		}
		dist := math.Abs(ts - targetX)
		if dist < bestDist {
			bestDist = dist
			dataX = ts
			dataY = value
			ok = true
		}
	}
	return dataX, dataY, ok
}

func (c *FrenchFriesChart) sortedSeriesNames() []string {
	if !c.seriesDirty {
		return c.orderedSeries
	}

	names := make([]string, 0, len(c.series))
	for name := range c.series {
		names = append(names, name)
	}
	sort.Slice(names, func(i, j int) bool {
		return systemMetricSeriesLess(names[i], names[j])
	})

	c.orderedSeries = names
	c.seriesDirty = false
	return c.orderedSeries
}

func (c *FrenchFriesChart) visibleSeriesNames(maxRows int) []string {
	names := c.sortedSeriesNames()
	if maxRows <= 0 || len(names) == 0 {
		return nil
	}
	if len(names) <= maxRows {
		return names
	}
	if maxRows == 1 {
		return names[:1]
	}

	visible := make([]string, 0, maxRows)
	visible = append(visible, names[:maxRows-1]...)
	visible = append(visible, names[len(names)-1])
	return visible
}

func summarizeFrenchFriesSeries(names []string, total int) string {
	if total <= len(names) {
		return fmt.Sprintf("[%d]", total)
	}

	labels := make([]string, 0, 4)
	if len(names) <= 3 {
		for _, name := range names {
			labels = append(labels, compactSystemMetricSeriesLabel(name))
		}
	} else {
		labels = append(labels,
			compactSystemMetricSeriesLabel(names[0]),
			compactSystemMetricSeriesLabel(names[1]),
			"...",
			compactSystemMetricSeriesLabel(names[len(names)-1]),
		)
	}

	return fmt.Sprintf("[%s/%d]", strings.Join(labels, ","), total)
}

func compactSystemMetricSeriesLabel(name string) string {
	if name == "" || name == DefaultSystemMetricSeriesName {
		return ""
	}
	fields := strings.Fields(name)
	if len(fields) == 0 {
		return name
	}
	last := fields[len(fields)-1]
	if _, err := strconv.Atoi(last); err == nil {
		return last
	}
	return name
}

func systemMetricSeriesLess(a, b string) bool {
	aPrefix, aIndex, aIndexed := splitSystemMetricSeriesIndex(a)
	bPrefix, bIndex, bIndexed := splitSystemMetricSeriesIndex(b)
	if aIndexed && bIndexed && aPrefix == bPrefix {
		return aIndex < bIndex
	}
	return a < b
}

func splitSystemMetricSeriesIndex(name string) (prefix string, index int, ok bool) {
	fields := strings.Fields(name)
	if len(fields) < 2 {
		return "", 0, false
	}

	index, err := strconv.Atoi(fields[len(fields)-1])
	if err != nil {
		return "", 0, false
	}
	return strings.Join(fields[:len(fields)-1], " "), index, true
}
