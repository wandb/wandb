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

// FrenchFriesChart renders one row per device/series and appends a color-coded
// cell for each new timestamped sample.
//
// It intentionally focuses on the live tail only. Each timestamp corresponds
// to one rendered column, so metrics for multiple GPUs from the same StatsMsg
// align vertically.
type FrenchFriesChart struct {
	def *MetricDef

	width  int
	height int

	// historyCap is the maximum number of sample-columns retained. It tracks the
	// widest chart width seen so far so resizing wider does not discard recent
	// history.
	historyCap int
	samples    []frenchFriesSample

	series        map[string]struct{}
	orderedSeries []string
	seriesDirty   bool

	lastUpdate time.Time

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
	if c.height <= 0 || total <= c.height {
		return fmt.Sprintf("[%d]", total)
	}

	return summarizeFrenchFriesSeries(c.visibleSeriesNames(c.height), total)
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

	c.trimHistory()
	c.dirty = true
}

func (c *FrenchFriesChart) GraphWidth() int  { return c.width }
func (c *FrenchFriesChart) GraphStartX() int { return 1 }

func (c *FrenchFriesChart) HandleZoom(string, int) {}

func (c *FrenchFriesChart) ToggleYScale() bool { return false }
func (c *FrenchFriesChart) IsLogY() bool       { return false }

func (c *FrenchFriesChart) ViewModeLabel() string {
	visible := min(len(c.samples), c.width)
	if visible <= 0 {
		return "live tail"
	}
	return fmt.Sprintf("live tail %d samples", visible)
}

func (c *FrenchFriesChart) ScaleLabel() string { return "" }

func (c *FrenchFriesChart) StartInspection(int)                      {}
func (c *FrenchFriesChart) UpdateInspection(int)                     {}
func (c *FrenchFriesChart) EndInspection()                           {}
func (c *FrenchFriesChart) IsInspecting() bool                       { return false }
func (c *FrenchFriesChart) InspectAtDataX(float64)                   {}
func (c *FrenchFriesChart) InspectionData() (float64, float64, bool) { return 0, 0, false }

func (c *FrenchFriesChart) draw() {
	if c.width <= 0 || c.height <= 0 {
		c.rendered = ""
		c.dirty = false
		return
	}

	columns := c.samples
	if len(columns) > c.width {
		columns = columns[len(columns)-c.width:]
	}
	leftPad := max(c.width-len(columns), 0)

	rows := make([]string, 0, c.height)
	for _, name := range c.visibleSeriesNames(c.height) {
		rows = append(rows, c.renderRow(name, leftPad, columns))
	}

	blankRow := strings.Repeat(" ", c.width)
	for len(rows) < c.height {
		rows = append(rows, blankRow)
	}

	c.rendered = lipgloss.Place(
		c.width,
		c.height,
		lipgloss.Left,
		lipgloss.Top,
		strings.Join(rows, "\n"),
	)
	c.dirty = false
}

func (c *FrenchFriesChart) renderRow(
	seriesName string, leftPad int, columns []frenchFriesSample) string {
	var b strings.Builder
	for i := 0; i < leftPad; i++ {
		b.WriteByte(' ')
	}

	for _, column := range columns {
		value, ok := column.values[seriesName]
		if !ok {
			b.WriteByte(' ')
			continue
		}
		b.WriteString(c.colorForValue(value))
	}

	return b.String()
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
