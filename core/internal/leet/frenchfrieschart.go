package leet

import (
	"fmt"
	"image/color"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
)

const frenchFriesCell = "█"

func renderFrenchFriesCells(colors []compat.AdaptiveColor) []string {
	if len(colors) == 0 {
		colors = FrenchFriesColors(DefaultFrenchFriesColorScheme)
	}

	rendered := make([]string, len(colors))
	for i, color := range colors {
		rendered[i] = lipgloss.NewStyle().
			Foreground(color).
			Render(frenchFriesCell)
	}
	return rendered
}

type frenchFriesSample struct {
	x      float64
	values map[string]float64
}

type frenchFriesInspection struct {
	active bool
	mouseX int
	dataX  float64
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

type frenchFriesBucketCell struct {
	x     float64
	value float64
	ok    bool
}

// FrenchFriesChart renders one row per series and compresses the visible
// window into color-coded buckets, producing a compact heatmap.
type FrenchFriesChart struct {
	title         string
	unitFormatter func(float64) string
	xLabelFunc    func(value float64, maxWidth int) string

	// seriesColorFn returns a foreground color for a series label. When set,
	// each series is labeled with a colored "●" (or "▶" for the pinned
	// series) instead of the default text.
	// Returns nil if no color is available (label renders unstyled).
	seriesColorFn func(seriesName string) color.Color

	// pinnedSeries, when non-empty, is sorted to the top row.
	pinnedSeries string

	width  int
	height int

	// samples retain the full observed history so the chart can reuse the same
	// windowing and zoom semantics as the underlying line chart.
	samples []frenchFriesSample

	series        map[string]struct{}
	orderedSeries []string
	seriesDirty   bool

	// Fixed value range for color mapping (e.g. 0–100 for percentages).
	// When fixedMaxY > fixedMinY, colorForValue uses these instead of observed bounds.
	fixedMinY float64
	fixedMaxY float64

	// Observed value range, updated incrementally by AddDataPoint.
	observedMinY float64
	observedMaxY float64

	lastUpdate time.Time
	viewMinX   float64
	viewMaxX   float64
	viewReady  bool

	inspection frenchFriesInspection

	dirty    bool
	rendered string

	coloredCells []string
}

// FrenchFriesChartParams configures a new FrenchFriesChart.
type FrenchFriesChartParams struct {
	Width, Height int
	Title         string
	UnitFormatter func(float64) string
	XLabelFunc    func(value float64, maxWidth int) string
	SeriesColorFn func(seriesName string) color.Color
	// FixedMinY/FixedMaxY pin the color range (e.g. 0–100 for percentages).
	// When FixedMaxY > FixedMinY, colorForValue uses these instead of observed bounds.
	FixedMinY, FixedMaxY float64
	Colors               []compat.AdaptiveColor
	Now                  time.Time
}

func NewFrenchFriesChart(params *FrenchFriesChartParams) *FrenchFriesChart {
	chart := &FrenchFriesChart{
		title:         params.Title,
		unitFormatter: params.UnitFormatter,
		xLabelFunc:    params.XLabelFunc,
		seriesColorFn: params.SeriesColorFn,
		fixedMinY:     params.FixedMinY,
		fixedMaxY:     params.FixedMaxY,
		series:        make(map[string]struct{}),
		seriesDirty:   true,
		observedMinY:  math.Inf(1),
		observedMaxY:  math.Inf(-1),
		lastUpdate:    params.Now,
		dirty:         true,
		coloredCells:  renderFrenchFriesCells(params.Colors),
	}

	chart.Resize(params.Width, params.Height)
	return chart
}

func (c *FrenchFriesChart) Title() string { return c.title }

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

	return c.summarizeSeries(c.visibleSeriesNames(layout.maxVisibleRows), total)
}

// legendDetail returns a compact gradient bar with the observed range.
func (c *FrenchFriesChart) legendDetail() string {
	minY, maxY := c.colorRange()
	if maxY <= minY {
		return ""
	}
	if len(c.coloredCells) == 0 {
		return ""
	}

	formatter := c.unitFormatter
	if formatter == nil {
		formatter = UnitScalar.Format
	}

	// Pick up to 5 evenly spaced gradient cells.
	n := min(5, len(c.coloredCells))
	var bar strings.Builder
	for i := range n {
		idx := i * (len(c.coloredCells) - 1) / max(n-1, 1)
		bar.WriteString(c.coloredCells[idx])
	}

	return formatter(minY) + bar.String() + formatter(maxY)
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
	c.dirty = true
}

func (c *FrenchFriesChart) DrawIfNeeded() {
	if c.dirty {
		c.draw()
	}
}

func (c *FrenchFriesChart) AddDataPoint(seriesName string, x, value float64) {
	if seriesName == "" {
		seriesName = DefaultSystemMetricSeriesName
	}
	if _, ok := c.series[seriesName]; !ok {
		c.series[seriesName] = struct{}{}
		c.seriesDirty = true
	}

	// Fast path: append when x >= last sample (most common for live data).
	n := len(c.samples)
	switch {
	case n > 0 && c.samples[n-1].x == x:
		c.samples[n-1].values[seriesName] = value
	case n == 0 || x > c.samples[n-1].x:
		c.samples = append(c.samples, frenchFriesSample{
			x:      x,
			values: map[string]float64{seriesName: value},
		})
	default:
		// Out-of-order: binary search for the correct position.
		idx := sort.Search(n, func(i int) bool { return c.samples[i].x >= x })
		if idx < n && c.samples[idx].x == x {
			c.samples[idx].values[seriesName] = value
		} else {
			c.samples = slices.Insert(c.samples, idx, frenchFriesSample{
				x:      x,
				values: map[string]float64{seriesName: value},
			})
		}
	}

	c.observedMinY = min(c.observedMinY, value)
	c.observedMaxY = max(c.observedMaxY, value)
	c.lastUpdate = time.Unix(int64(x), 0)

	if !c.viewReady {
		c.setDefaultViewWindow()
	}

	c.dirty = true
}

// RemoveSeries removes all data for the named series.
func (c *FrenchFriesChart) RemoveSeries(key string) {
	if _, ok := c.series[key]; !ok {
		return
	}
	delete(c.series, key)
	c.seriesDirty = true

	for i := range c.samples {
		delete(c.samples[i].values, key)
	}
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
		c.InspectAtDataX(c.inspection.dataX)
	}
}

func (c *FrenchFriesChart) StartInspectionAt(mouseX, _ int) {
	if c.GraphWidth() <= 0 || c.GraphHeight() <= 0 {
		return
	}
	c.inspection.active = true
	c.UpdateInspectionAt(mouseX, 0)
}

func (c *FrenchFriesChart) UpdateInspectionAt(mouseX, _ int) {
	if !c.inspection.active {
		return
	}

	layout := c.layout()
	if layout.plotWidth <= 0 || layout.plotHeight <= 0 || len(layout.bands) == 0 {
		return
	}

	c.inspection.mouseX = max(0, min(layout.plotWidth-1, mouseX))
	c.inspection.dataX = c.dataXForMouse(c.inspection.mouseX, layout.plotWidth)
	c.dirty = true
}

func (c *FrenchFriesChart) EndInspection() {
	c.inspection = frenchFriesInspection{}
	c.dirty = true
}

func (c *FrenchFriesChart) IsInspecting() bool { return c.inspection.active }

func (c *FrenchFriesChart) InspectAtDataX(targetX float64) {
	layout := c.layout()
	if layout.plotWidth <= 0 || layout.plotHeight <= 0 || len(layout.bands) == 0 {
		return
	}
	c.inspection.active = true
	c.inspection.mouseX = c.bucketForDataX(targetX, layout.plotWidth)
	c.inspection.dataX = targetX
	c.dirty = true
}

func (c *FrenchFriesChart) InspectionData() (float64, float64, bool) {
	return c.inspection.dataX, 0, c.inspection.active
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
	if c.inspection.active {
		selectedBucket = max(0, min(layout.plotWidth-1, c.inspection.mouseX))
	}

	for _, band := range layout.bands {
		for y := band.startY; y < band.startY+band.height; y++ {
			for x := 0; x < layout.plotWidth; x++ {
				bucket := bucketed[band.seriesName][x]
				cell := " "
				if bucket.ok {
					cell = c.colorForValue(bucket.value)
				}
				cells[y][layout.plotStartX+x] = cell
			}
		}

		c.renderBandLabel(cells, layout, band)
	}

	c.renderTruncationIndicator(cells, layout)
	c.renderInspectionHairline(cells, layout, selectedBucket)
	c.renderTimeLabels(cells, layout)
	c.renderInspectionLabels(cells, layout, bucketed)
	c.renderInspectionTimeLabel(cells, layout, bucketed)

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

	if c.seriesColorFn != nil {
		// Colored dot: render the styled label into a single cell.
		if clr := c.seriesColorFn(band.seriesName); clr != nil {
			cells[row][start] = lipgloss.NewStyle().Foreground(clr).Render(label)
			return
		}
	}

	for i, r := range label {
		if start+i >= layout.labelWidth-1 {
			break
		}
		cells[row][start+i] = string(r)
	}
}

// renderTruncationIndicator shows "+N" when series are hidden due to space.
func (c *FrenchFriesChart) renderTruncationIndicator(
	cells [][]string,
	layout frenchFriesLayout,
) {
	total := len(c.sortedSeriesNames())
	visible := len(layout.bands)
	if total <= visible || visible == 0 || layout.plotWidth <= 0 {
		return
	}

	label := fmt.Sprintf("+%d", total-visible)
	row := layout.bands[visible-1].centerY()

	// Right-align in the plot area.
	startX := layout.plotStartX + layout.plotWidth - lipgloss.Width(label)
	if startX < layout.plotStartX {
		startX = layout.plotStartX
	}
	for i, r := range label {
		x := startX + i
		if x >= layout.plotStartX && x < layout.plotStartX+layout.plotWidth {
			cells[row][x] = navInfoStyle.Render(string(r))
		}
	}
}

func (c *FrenchFriesChart) renderInspectionHairline(
	cells [][]string,
	layout frenchFriesLayout,
	selectedBucket int,
) {
	if !c.inspection.active || selectedBucket < 0 || selectedBucket >= layout.plotWidth {
		return
	}

	x := layout.plotStartX + selectedBucket
	for y := 0; y < layout.plotHeight; y++ {
		cells[y][x] = inspectionLineStyle.Render(string(boxLightVertical))
	}
}

func (c *FrenchFriesChart) renderInspectionLabels(
	cells [][]string,
	layout frenchFriesLayout,
	bucketed map[string][]frenchFriesBucketCell,
) {
	if !c.inspection.active || layout.plotWidth <= 0 || layout.plotHeight <= 0 {
		return
	}
	bucket := max(0, min(layout.plotWidth-1, c.inspection.mouseX))
	labels := make(map[string]string, len(layout.bands))
	maxLabelWidth := 0
	for _, band := range layout.bands {
		label := string(unicodeEmDash)
		if cellsForSeries, ok := bucketed[band.seriesName]; ok {
			label = c.inspectionValueLabel(band.seriesName, cellsForSeries[bucket])
		}
		labels[band.seriesName] = label
		maxLabelWidth = max(maxLabelWidth, lipgloss.Width(label))
	}
	if maxLabelWidth <= 0 {
		return
	}

	startX := selectedLabelStartX(bucket, layout.plotWidth, maxLabelWidth)
	for _, band := range layout.bands {
		row := band.centerY()
		label := labels[band.seriesName]
		if lipgloss.Width(label) > maxLabelWidth {
			label = TruncateTitle(label, maxLabelWidth)
		}
		c.writeLabelToCells(cells[row], layout.plotStartX+startX,
			layout.plotStartX, layout.plotStartX+layout.plotWidth,
			label, band.seriesName)
	}
}

// writeLabelToCells writes label text to cells starting at startX.
// When seriesColorFn is set, the series dot prefix gets the series color
// while the rest of the label uses inspectionLegendStyle.
func (c *FrenchFriesChart) writeLabelToCells(
	row []string,
	startX, minX, maxX int,
	label, seriesName string,
) {
	// The series prefix is 1 rune (● or ▶) — style it with the series color.
	prefixRunes := 0
	var prefixStyle lipgloss.Style
	if c.seriesColorFn != nil {
		if clr := c.seriesColorFn(seriesName); clr != nil {
			prefixRunes = 1
			prefixStyle = lipgloss.NewStyle().Foreground(clr)
		}
	}

	col := 0
	for _, r := range label {
		x := startX + col
		if x >= minX && x < maxX {
			ch := string(r)
			if col < prefixRunes {
				row[x] = prefixStyle.Render(ch)
			} else {
				row[x] = inspectionLegendStyle.Render(ch)
			}
		}
		col++
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

func (c *FrenchFriesChart) inspectionValueLabel(
	seriesName string,
	bucket frenchFriesBucketCell,
) string {
	valueLabel := string(unicodeEmDash)
	if bucket.ok {
		if c.unitFormatter != nil {
			valueLabel = c.unitFormatter(bucket.value)
		} else {
			valueLabel = UnitScalar.Format(bucket.value)
		}
	}

	seriesLabel := c.seriesLabel(seriesName)
	if seriesLabel == "" {
		return valueLabel
	}
	return seriesLabel + ": " + valueLabel
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

	minLabel := c.formatXLabel(viewMinX, layout.plotWidth)
	maxLabel := c.formatXLabel(viewMaxX, layout.plotWidth)
	labels := []struct {
		text string
		pos  int
	}{
		{text: minLabel, pos: 0},
		{text: maxLabel, pos: max(layout.plotWidth-lipgloss.Width(maxLabel), 0)},
	}

	midX := (viewMinX + viewMaxX) / 2
	midText := c.formatXLabel(midX, layout.plotWidth)
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

// formatXLabel formats an X-axis value for display.
// Uses the pluggable xLabelFunc if set, otherwise defaults to time formatting.
func (c *FrenchFriesChart) formatXLabel(value float64, maxWidth int) string {
	if c.xLabelFunc != nil {
		return c.xLabelFunc(value, maxWidth)
	}
	// Default: format as timestamp (system metrics).
	viewMinX, viewMaxX := c.effectiveViewWindow()
	span := time.Duration(math.Round(viewMaxX-viewMinX)) * time.Second
	return fitTimeLayouts(
		time.Unix(int64(math.Round(value)), 0).Local(),
		maxWidth,
		systemTimeLayouts(span),
	)
}

func (c *FrenchFriesChart) renderInspectionTimeLabel(
	cells [][]string,
	layout frenchFriesLayout,
	bucketed map[string][]frenchFriesBucketCell,
) {
	if !c.inspection.active || layout.timeAxisY < 0 || layout.plotWidth <= 0 {
		return
	}

	bucket := max(0, min(layout.plotWidth-1, c.inspection.mouseX))
	dataX := c.inspection.dataX
	if bx, ok := bucketX(bucketed, bucket); ok {
		dataX = bx
	}

	label := c.formatXLabel(dataX, layout.plotWidth)
	if label == "" {
		return
	}
	startX := selectedLabelStartX(bucket, layout.plotWidth, lipgloss.Width(label))
	for i, r := range label {
		x := layout.plotStartX + startX + i
		if x < layout.plotStartX || x >= layout.plotStartX+layout.plotWidth {
			continue
		}
		cells[layout.timeAxisY][x] = lipgloss.NewStyle().Bold(true).Render(string(r))
	}
}

func bucketX(
	bucketed map[string][]frenchFriesBucketCell,
	bucket int,
) (float64, bool) {
	var (
		best float64
		ok   bool
	)
	for _, cells := range bucketed {
		if bucket < 0 || bucket >= len(cells) {
			continue
		}
		cell := cells[bucket]
		if !cell.ok {
			continue
		}
		if !ok || cell.x > best {
			best = cell.x
			ok = true
		}
	}
	return best, ok
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
		labels[i] = c.seriesLabel(name)
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

func (c *FrenchFriesChart) visibleSampleRange(viewMinX, viewMaxX float64) (start, end int) {
	start = sort.Search(len(c.samples), func(i int) bool {
		return c.samples[i].x >= viewMinX
	})
	end = sort.Search(len(c.samples), func(i int) bool {
		return c.samples[i].x > viewMaxX
	})
	return start, end
}

func (c *FrenchFriesChart) bucketedSeries(
	layout frenchFriesLayout,
) map[string][]frenchFriesBucketCell {
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

	// Accumulate sum and count per bucket so the final value is an average.
	// Averaging makes the display stable when a single sample shifts between
	// neighbouring buckets due to a small view-window change.
	type accum struct {
		sum   float64
		count int
		lastX float64
	}
	accums := make(map[string][]accum, len(layout.bands))
	for _, band := range layout.bands {
		accums[band.seriesName] = make([]accum, layout.plotWidth)
	}

	start, end := c.visibleSampleRange(viewMinX, viewMaxX)
	for _, sample := range c.samples[start:end] {
		bucket := c.bucketForDataX(sample.x, layout.plotWidth)
		for seriesName, value := range sample.values {
			a, ok := accums[seriesName]
			if !ok {
				continue
			}
			a[bucket].sum += value
			a[bucket].count++
			if sample.x > a[bucket].lastX {
				a[bucket].lastX = sample.x
			}
		}
	}

	for seriesName, cells := range bucketed {
		a := accums[seriesName]
		for i := range cells {
			if a[i].count > 0 {
				cells[i] = frenchFriesBucketCell{
					x:     a[i].lastX,
					value: a[i].sum / float64(a[i].count),
					ok:    true,
				}
			}
		}
	}

	return bucketed
}

func (c *FrenchFriesChart) colorForValue(value float64) string {
	if !isFinite(value) || len(c.coloredCells) == 0 {
		return " "
	}

	minY, maxY := c.colorRange()
	if maxY <= minY {
		return c.coloredCells[len(c.coloredCells)/2]
	}

	normalized := (value - minY) / (maxY - minY)
	normalized = max(0, min(1, normalized))
	idx := int(math.Round(normalized * float64(len(c.coloredCells)-1)))
	return c.coloredCells[idx]
}

// colorRange returns the [min, max] used for color mapping.
func (c *FrenchFriesChart) colorRange() (float64, float64) {
	if c.fixedMaxY > c.fixedMinY {
		return c.fixedMinY, c.fixedMaxY
	}
	if !isFinite(c.observedMinY) || !isFinite(c.observedMaxY) {
		return 0, 0
	}
	return c.observedMinY, c.observedMaxY
}

// ObservedRange returns the tracked [min, max] of ingested values.
func (c *FrenchFriesChart) ObservedRange() (float64, float64) {
	return c.observedMinY, c.observedMaxY
}

func (c *FrenchFriesChart) setDefaultViewWindow() {
	if len(c.samples) == 0 {
		c.viewReady = false
		return
	}
	minX := c.samples[0].x
	maxX := c.samples[len(c.samples)-1].x
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
	// Map mouse position to the center of the corresponding bucket.
	bucketWidth := (viewMaxX - viewMinX) / float64(plotWidth)
	return viewMinX + (float64(max(0, min(plotWidth-1, mouseX)))+0.5)*bucketWidth
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
	// Stable interval-based bucketing: each bucket covers a fixed time
	// width so that small view-window changes don't redistribute samples.
	bucketWidth := (viewMaxX - viewMinX) / float64(plotWidth)
	bucket := int(math.Floor((dataX - viewMinX) / bucketWidth))
	return max(0, min(plotWidth-1, bucket))
}

func (c *FrenchFriesChart) sortedSeriesNames() []string {
	if !c.seriesDirty {
		return c.orderedSeries
	}

	names := make([]string, 0, len(c.series))
	for name := range c.series {
		names = append(names, name)
	}

	pinned := c.pinnedSeries
	sort.Slice(names, func(i, j int) bool {
		// Pinned series always sorts first.
		if pinned != "" {
			if names[i] == pinned {
				return true
			}
			if names[j] == pinned {
				return false
			}
		}
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
	// Pinned is already first in sorted order, so taking the first
	// maxRows entries always includes it.
	return names[:maxRows]
}

func (c *FrenchFriesChart) summarizeSeries(names []string, total int) string {
	if total <= len(names) {
		return fmt.Sprintf("[%d]", total)
	}

	labels := make([]string, 0, 4)
	if len(names) <= 3 {
		for _, name := range names {
			labels = append(labels, c.seriesLabel(name))
		}
	} else {
		labels = append(labels,
			c.seriesLabel(names[0]),
			c.seriesLabel(names[1]),
			"...",
			c.seriesLabel(names[len(names)-1]),
		)
	}

	return fmt.Sprintf("[%s/%d]", strings.Join(labels, ","), total)
}

const (
	seriesDot    = "●"
	seriesPinned = "▶"
)

// seriesLabel returns a compact display label for the given series name.
// When seriesColorFn is set, returns "●" (or "▶" for the pinned series).
// Otherwise falls back to the default extractor (e.g. "GPU 0" → "0").
func (c *FrenchFriesChart) seriesLabel(name string) string {
	if c.seriesColorFn != nil {
		if c.pinnedSeries != "" && name == c.pinnedSeries {
			return seriesPinned
		}
		return seriesDot
	}
	return defaultSeriesLabel(name)
}

// SetPinnedSeries marks a series to sort to the top row and use "▶".
// Pass "" to clear.
func (c *FrenchFriesChart) SetPinnedSeries(key string) {
	if c.pinnedSeries == key {
		return
	}
	c.pinnedSeries = key
	c.seriesDirty = true
	c.dirty = true
}

func defaultSeriesLabel(name string) string {
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
