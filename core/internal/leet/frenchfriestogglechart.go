package leet

// frenchFriesToggleChart keeps the existing time-series line chart as the
// source of truth for time-window behavior while optionally rendering the same
// metric as a heatmap-style French Fries chart.
type frenchFriesToggleChart struct {
	line        *TimeSeriesLineChart
	frenchFries *FrenchFriesChart
	heatmapMode bool
}

func newFrenchFriesToggleChart(
	line *TimeSeriesLineChart,
	frenchFries *FrenchFriesChart,
) *frenchFriesToggleChart {
	chart := &frenchFriesToggleChart{
		line:        line,
		frenchFries: frenchFries,
	}
	chart.syncViewWindow()
	return chart
}

func (c *frenchFriesToggleChart) activeChart() systemMetricChart {
	if c.heatmapMode {
		return c.frenchFries
	}
	return c.line
}

func (c *frenchFriesToggleChart) syncViewWindow() {
	if c == nil || c.line == nil || c.frenchFries == nil {
		return
	}
	c.frenchFries.SetViewWindow(c.line.ViewMinX(), c.line.ViewMaxX())
}

func (c *frenchFriesToggleChart) Title() string {
	return c.line.Title()
}

func (c *frenchFriesToggleChart) TitleDetail() string {
	return c.activeChart().TitleDetail()
}

func (c *frenchFriesToggleChart) View() string {
	return c.activeChart().View()
}

func (c *frenchFriesToggleChart) Resize(width, height int) {
	c.line.Resize(width, height)
	c.frenchFries.Resize(width, height)
	c.syncViewWindow()
}

func (c *frenchFriesToggleChart) DrawIfNeeded() {
	c.syncViewWindow()
	c.activeChart().DrawIfNeeded()
}

func (c *frenchFriesToggleChart) AddDataPoint(seriesName string, timestamp int64, value float64) {
	c.line.AddDataPoint(seriesName, timestamp, value)
	c.frenchFries.AddDataPoint(seriesName, timestamp, value)
	c.syncViewWindow()
}

func (c *frenchFriesToggleChart) GraphWidth() int {
	return c.activeChart().GraphWidth()
}

func (c *frenchFriesToggleChart) GraphHeight() int {
	return c.activeChart().GraphHeight()
}

func (c *frenchFriesToggleChart) GraphStartX() int {
	return c.activeChart().GraphStartX()
}

func (c *frenchFriesToggleChart) GraphStartY() int {
	return c.activeChart().GraphStartY()
}

func (c *frenchFriesToggleChart) HandleZoom(direction string, mouseX int) {
	c.line.HandleZoom(direction, mouseX)
	c.syncViewWindow()
	c.activeChart().DrawIfNeeded()
}

func (c *frenchFriesToggleChart) ToggleYScale() bool {
	if c.heatmapMode {
		return false
	}
	return c.line.ToggleYScale()
}

func (c *frenchFriesToggleChart) IsLogY() bool {
	if c.heatmapMode {
		return false
	}
	return c.line.IsLogY()
}

func (c *frenchFriesToggleChart) SupportsHeatmap() bool { return true }

func (c *frenchFriesToggleChart) ToggleHeatmapMode() bool {
	c.heatmapMode = !c.heatmapMode
	c.syncViewWindow()
	c.activeChart().DrawIfNeeded()
	return true
}

func (c *frenchFriesToggleChart) IsHeatmapMode() bool { return c.heatmapMode }

func (c *frenchFriesToggleChart) ViewModeLabel() string {
	return c.line.ViewModeLabel()
}

func (c *frenchFriesToggleChart) ScaleLabel() string {
	if c.heatmapMode {
		return "heatmap"
	}
	return c.line.ScaleLabel()
}

func (c *frenchFriesToggleChart) StartInspectionAt(mouseX, mouseY int) {
	c.syncViewWindow()
	c.activeChart().StartInspectionAt(mouseX, mouseY)
}

func (c *frenchFriesToggleChart) UpdateInspectionAt(mouseX, mouseY int) {
	c.syncViewWindow()
	c.activeChart().UpdateInspectionAt(mouseX, mouseY)
}

func (c *frenchFriesToggleChart) EndInspection() {
	c.line.EndInspection()
	c.frenchFries.EndInspection()
}

func (c *frenchFriesToggleChart) IsInspecting() bool {
	return c.activeChart().IsInspecting()
}

func (c *frenchFriesToggleChart) InspectionData() (x, y float64, active bool) {
	return c.activeChart().InspectionData()
}

func (c *frenchFriesToggleChart) InspectAtDataX(targetX float64) {
	c.syncViewWindow()
	c.activeChart().InspectAtDataX(targetX)
}
