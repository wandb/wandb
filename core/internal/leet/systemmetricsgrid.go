package leet

import (
	"fmt"
	"slices"
	"sort"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	// Horizontal padding for title within chart box.
	chartTitlePadding = 4

	// Minimum readable width for chart titles.
	minTitleWidth = 10
)

// SystemMetricsGrid manages the grid of system metric charts.
type SystemMetricsGrid struct {
	// Configuration and logging.
	config     *ConfigManager
	gridConfig func() (int, int)
	logger     *observability.CoreLogger

	// Viewport dimensions.
	width, height int

	// Pagination state.
	nav GridNavigator

	// Charts state.
	byBaseKey   map[string]*TimeSeriesLineChart // baseKey -> chart
	ordered     []*TimeSeriesLineChart          // charts sorted by title
	filtered    []*TimeSeriesLineChart          // charts matching current filter
	currentPage [][]*TimeSeriesLineChart        // current page view

	// Filter state.
	filter *Filter

	// Chart focus management.
	focus *Focus

	// Coloring state for per-plot mode.
	nextColor int // next palette index

	// synchronized inspection session state (active only between press/release)
	syncInspectActive bool
}

func NewSystemMetricsGrid(
	width, height int,
	config *ConfigManager,
	gridConfig func() (int, int),
	focusState *Focus,
	filter *Filter,
	logger *observability.CoreLogger,
) *SystemMetricsGrid {
	smg := &SystemMetricsGrid{
		config:     config,
		gridConfig: gridConfig,
		byBaseKey:  make(map[string]*TimeSeriesLineChart),
		ordered:    make([]*TimeSeriesLineChart, 0),
		filtered:   make([]*TimeSeriesLineChart, 0),
		filter:     filter,
		focus:      focusState,
		width:      width,
		height:     height,
		logger:     logger,
	}

	size := smg.effectiveGridSize()
	smg.currentPage = make([][]*TimeSeriesLineChart, size.Rows)
	for row := range size.Rows {
		smg.currentPage[row] = make([]*TimeSeriesLineChart, size.Cols)
	}

	logger.Debug(fmt.Sprintf("SystemMetricsGrid: created with dimensions %dx%d (grid %dx%d)",
		width, height, size.Rows, size.Cols))

	return smg
}

// calculateChartDimensions computes dimensions for system metric charts.
func (g *SystemMetricsGrid) calculateChartDimensions() GridDims {
	cfgRows, cfgCols := g.gridConfig()
	return ComputeGridDims(g.width, g.height, GridSpec{
		Rows:        cfgRows,
		Cols:        cfgCols,
		MinCellW:    MinMetricChartWidth,
		MinCellH:    MinMetricChartHeight,
		HeaderLines: 0,
	})
}

// effectiveGridSize returns the grid size that can fit in the current viewport.
func (g *SystemMetricsGrid) effectiveGridSize() GridSize {
	cfgRows, cfgCols := g.gridConfig()
	return EffectiveGridSize(g.width, g.height, GridSpec{
		Rows:        cfgRows,
		Cols:        cfgCols,
		MinCellW:    MinMetricChartWidth,
		MinCellH:    MinMetricChartHeight,
		HeaderLines: 0,
	})
}

// nextColorHex returns the next color from the palette.
func (g *SystemMetricsGrid) nextColorHex() compat.AdaptiveColor {
	colors := colorSchemes[g.config.SystemColorScheme()]
	color := colors[g.nextColor%len(colors)]
	g.nextColor++
	return color
}

// anchoredSeriesColorProvider returns a provider that yields colors relative
// to a given base index in the current palette.
//
// The first call returns the color after the base color,
// so the base can be used for the first series.
func (g *SystemMetricsGrid) anchoredSeriesColorProvider(baseIdx int) func() compat.AdaptiveColor {
	colors := colorSchemes[g.config.SystemColorScheme()]
	idx := baseIdx + 1
	return func() compat.AdaptiveColor {
		c := colors[idx%len(colors)]
		idx++
		return c
	}
}

// createMetricChart creates a time series chart for a system metric.
func (g *SystemMetricsGrid) createMetricChart(def *MetricDef) *TimeSeriesLineChart {
	dims := g.calculateChartDimensions()
	chartWidth := max(dims.CellW, MinMetricChartWidth)
	chartHeight := max(dims.CellH, MinMetricChartHeight)

	g.logger.Debug(fmt.Sprintf(
		"systemmetricsgrid: creating chart %dx%d for %v",
		chartWidth, chartHeight, def))

	// Base color by color mode.
	var (
		baseColor compat.AdaptiveColor
		baseIdx   int
	)
	colorMode := g.config.SystemColorMode()
	colors := colorSchemes[g.config.SystemColorScheme()]
	if colorMode == ColorModePerSeries {
		baseColor = colors[0]
	} else {
		baseColor = g.nextColorHex()
		baseIdx = (g.nextColor - 1) % len(colors)
	}

	chart := NewTimeSeriesLineChart(&TimeSeriesLineChartParams{
		Width:         chartWidth,
		Height:        chartHeight,
		Def:           def,
		BaseColor:     baseColor,
		ColorProvider: g.anchoredSeriesColorProvider(baseIdx),
		Now:           time.Now(),
	})
	chart.SetTailWindow(g.config.SystemTailWindow())
	return chart
}

// AddDataPoint adds a new data point to the appropriate metric chart.
func (g *SystemMetricsGrid) AddDataPoint(metricName string, timestamp int64, value float64) {
	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.AddDataPoint: metric=%s, timestamp=%d, value=%f",
		metricName, timestamp, value))

	def := MatchMetricDef(metricName)
	if def == nil {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.AddDataPoint: no definition for metric=%s", metricName))
		return
	}

	baseKey := ExtractBaseKey(metricName)
	seriesName := ExtractSeriesName(metricName)

	chart := g.getOrCreateChart(baseKey, def)
	chart.AddDataPoint(seriesName, timestamp, value)
	if g.isChartVisible(chart) {
		chart.DrawIfNeeded()
	}
}

// getOrCreateChart returns a TimeSeriesLineChart for the given baseKey.
func (g *SystemMetricsGrid) getOrCreateChart(baseKey string, def *MetricDef) *TimeSeriesLineChart {
	chart, exists := g.byBaseKey[baseKey]
	if !exists {
		g.logger.Debug(fmt.Sprintf("systemmetricsgrid: creating new chart for baseKey=%s", baseKey))
		chart = g.createMetricChart(def)
		g.byBaseKey[baseKey] = chart
		g.addChart(chart)
	}
	return chart
}

// addChart adds a chart to the ordered list and updates pagination.
func (g *SystemMetricsGrid) addChart(chart *TimeSeriesLineChart) {
	g.ordered = append(g.ordered, chart)
	sort.Slice(g.ordered, func(i, j int) bool {
		return g.ordered[i].Title() < g.ordered[j].Title()
	})

	g.ApplyFilter()
	g.drawVisible()

	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.addChart: chart added, total=%d, pages=%d",
		len(g.ordered), g.nav.TotalPages()))
}

// LoadCurrentPage loads charts for the current page.
func (g *SystemMetricsGrid) LoadCurrentPage() {
	size := g.effectiveGridSize()

	// Reallocate if dimensions changed or clear existing page.
	if len(g.currentPage) != size.Rows ||
		(len(g.currentPage) > 0 && len(g.currentPage[0]) != size.Cols) {
		g.currentPage = make([][]*TimeSeriesLineChart, size.Rows)
		for row := range size.Rows {
			g.currentPage[row] = make([]*TimeSeriesLineChart, size.Cols)
		}
	} else {
		for row := range size.Rows {
			for col := range size.Cols {
				g.currentPage[row][col] = nil
			}
		}
	}

	startIdx, endIdx := g.nav.PageBounds(len(g.filtered), ItemsPerPage(size))

	idx := startIdx
	for row := 0; row < size.Rows && idx < endIdx; row++ {
		for col := 0; col < size.Cols && idx < endIdx; col++ {
			g.currentPage[row][col] = g.filtered[idx]
			idx++
		}
	}

	g.syncFocusToCurrentPage()
}

// Navigate changes pages.
func (g *SystemMetricsGrid) Navigate(direction int) {
	if !g.nav.Navigate(direction) {
		return
	}

	g.ClearFocus()
	g.LoadCurrentPage()
	g.drawVisible()
}

// HandleMouseClick handles mouse clicks for chart selection.
//
// Returns a bool indicating whether an element was focused.
func (g *SystemMetricsGrid) HandleMouseClick(row, col int) bool {
	g.logger.Debug(fmt.Sprintf("systemmetricsgrid: HandleMouseClick: row=%d, col=%d", row, col))

	if g.focus.Type == FocusSystemChart && row == g.focus.Row && col == g.focus.Col {
		g.logger.Debug(
			"systemmetricsgrid: HandleMouseClick: clicking on focused chart - unfocusing",
		)
		g.ClearFocus()
		return false
	}

	if !g.setFocus(row, col) {
		return false
	}
	return true
}

func (g *SystemMetricsGrid) setFocus(row, col int) bool {
	g.ClearFocus()
	size := g.effectiveGridSize()
	if row < 0 || row >= size.Rows || col < 0 || col >= size.Cols ||
		row >= len(g.currentPage) || col >= len(g.currentPage[row]) {
		return false
	}
	chart := g.currentPage[row][col]
	if chart == nil {
		return false
	}

	g.focus.Set(FocusSystemChart, row, col, chart.Title())
	return true
}

// ClearFocus removes focus from all charts.
func (g *SystemMetricsGrid) ClearFocus() {
	if g.focus.Type == FocusSystemChart {
		g.focus.Reset()
	}
}

// FocusedChartTitle returns the title of the focused chart.
func (g *SystemMetricsGrid) FocusedChartTitle() string {
	if g.focus.Type == FocusSystemChart {
		return g.focus.Title
	}
	return ""
}

// FocusedChartViewModeLabel returns a short description of the focused chart's X-axis mode.
func (g *SystemMetricsGrid) FocusedChartViewModeLabel() string {
	chart := g.focusedChart()
	if chart == nil {
		return ""
	}
	return chart.ViewModeLabel()
}

func (g *SystemMetricsGrid) focusedChart() *TimeSeriesLineChart {
	if g.focus.Type != FocusSystemChart || g.focus.Row < 0 || g.focus.Col < 0 {
		return nil
	}
	if g.focus.Row >= len(g.currentPage) || g.focus.Col >= len(g.currentPage[g.focus.Row]) {
		return nil
	}
	return g.currentPage[g.focus.Row][g.focus.Col]
}

// Resize updates viewport dimensions and resizes/redraws visible charts.
func (g *SystemMetricsGrid) Resize(width, height int) {
	if width <= 0 || height <= 0 {
		g.logger.Debug(fmt.Sprintf(
			"systemmetricsgrid: Resize: invalid dimensions %dx%d, skipping", width, height))
		return
	}

	g.width = width
	g.height = height

	dims := g.calculateChartDimensions()
	if dims.CellW <= 0 || dims.CellH <= 0 ||
		dims.CellW < MinMetricChartWidth ||
		dims.CellH < MinMetricChartHeight {
		g.logger.Debug(fmt.Sprintf(
			"systemmetricsgrid: Resize: calculated dimensions %dx%d invalid, skipping",
			dims.CellW, dims.CellH))
		return
	}

	size := g.effectiveGridSize()
	g.nav.UpdateTotalPages(len(g.filtered), ItemsPerPage(size))
	g.LoadCurrentPage()
	g.drawVisible()
}

func (g *SystemMetricsGrid) drawVisible() {
	dims := g.calculateChartDimensions()
	for row := range g.currentPage {
		for col := range g.currentPage[row] {
			chart := g.currentPage[row][col]
			if chart == nil {
				continue
			}
			chart.Resize(dims.CellW, dims.CellH)
			chart.DrawIfNeeded()
		}
	}
}

func (g *SystemMetricsGrid) isChartVisible(target *TimeSeriesLineChart) bool {
	for row := range g.currentPage {
		if slices.Contains(g.currentPage[row], target) {
			return true
		}
	}
	return false
}

func (g *SystemMetricsGrid) syncFocusToCurrentPage() {
	if g.focus.Type != FocusSystemChart || g.focus.Title == "" {
		return
	}

	for row := range g.currentPage {
		for col := range g.currentPage[row] {
			ch := g.currentPage[row][col]
			if ch != nil && ch.Title() == g.focus.Title {
				g.focus.Row = row
				g.focus.Col = col
				return
			}
		}
	}

	// Focused chart is not visible on this page.
	g.ClearFocus()
}

// View renders the system metrics grid.
func (g *SystemMetricsGrid) View() string {
	dims := g.calculateChartDimensions()
	size := g.effectiveGridSize()

	var rows []string
	for row := range size.Rows {
		var cols []string
		for col := range size.Cols {
			// Empty cell.
			if g.currentPage[row][col] == nil {
				cols = append(cols, lipgloss.NewStyle().
					Width(dims.CellWWithPadding).
					Height(dims.CellHWithPadding).
					Render(""))
				continue
			}

			metricChart := g.currentPage[row][col]
			chartView := metricChart.View()

			titleText := metricChart.Title()
			if len(metricChart.series) > 1 {
				count := fmt.Sprintf(" [%d]", len(metricChart.series))
				availableWidth := max(
					dims.CellWWithPadding-chartTitlePadding-lipgloss.Width(count), minTitleWidth)
				displayTitle := TruncateTitle(titleText, availableWidth)
				titleText = titleStyle.Render(displayTitle) + seriesCountStyle.Render(count)
			} else {
				availableWidth := max(dims.CellWWithPadding-chartTitlePadding, minTitleWidth)
				titleText = titleStyle.Render(TruncateTitle(titleText, availableWidth))
			}

			boxContent := lipgloss.JoinVertical(lipgloss.Left, titleText, chartView)
			boxStyle := borderStyle
			if g.focus.Type == FocusSystemChart &&
				row == g.focus.Row && col == g.focus.Col {
				boxStyle = focusedBorderStyle
			}
			box := boxStyle.Render(boxContent)
			cell := lipgloss.Place(
				dims.CellWWithPadding,
				dims.CellHWithPadding,
				lipgloss.Left,
				lipgloss.Top,
				box,
			)
			cols = append(cols, cell)
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}

	grid := lipgloss.JoinVertical(lipgloss.Left, rows...)

	// Bottom filler.
	used := size.Rows * dims.CellHWithPadding
	if extra := g.height - used; extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		grid = lipgloss.JoinVertical(lipgloss.Left, grid, filler)
	}

	return grid
}

// ChartCount returns the number of charts on the grid.
func (g *SystemMetricsGrid) ChartCount() int {
	return len(g.ordered)
}

// hitChartAndRelX returns the chart under (row, col) on the grid
// with relative graph-local X.
//
// needFocus is true if this chart differs from current focus.
// ok is false if row/col doesn't map to a visible chart.
func (g *SystemMetricsGrid) hitChartAndRelX(
	adjustedX, row, col int,
	dims GridDims,
) (chart *TimeSeriesLineChart, relX int, needFocus, ok bool) {
	size := g.effectiveGridSize()
	if row < 0 || row >= size.Rows || col < 0 || col >= size.Cols ||
		row >= len(g.currentPage) || col >= len(g.currentPage[row]) {
		return nil, 0, false, false
	}
	chart = g.currentPage[row][col]
	if chart == nil {
		return nil, 0, false, false
	}

	chartStartX := col * dims.CellWWithPadding
	graphStartX := chartStartX + ChartBorderSize/2
	if chart.YStep() > 0 {
		graphStartX += chart.Origin().X + 1
	}
	relX = adjustedX - graphStartX

	needFocus = g.focus.Type != FocusSystemChart || g.focus.Row != row || g.focus.Col != col
	return chart, relX, needFocus, true
}

// hitChartAndRelPoint returns the chart under (row, col) together with
// graph-local X/Y coordinates.
func (g *SystemMetricsGrid) hitChartAndRelPoint(
	adjustedX, adjustedY, row, col int,
	dims GridDims,
) (chart *TimeSeriesLineChart, relX, relY int, needFocus, ok bool) {
	chart, relX, needFocus, ok = g.hitChartAndRelX(adjustedX, row, col, dims)
	if !ok || chart == nil {
		return nil, 0, 0, false, false
	}

	chartStartY := row * dims.CellHWithPadding
	graphStartY := chartStartY + ChartBorderSize/2 + ChartTitleHeight
	relY = adjustedY - graphStartY
	return chart, relX, relY, needFocus, true
}

// HandleWheel performs zoom handling on a system chart at (row, col).
func (g *SystemMetricsGrid) HandleWheel(
	adjustedX, adjustedY, row, col int,
	dims GridDims,
	wheelUp, vertical bool,
) {
	chart, relX, relY, needFocus, ok := g.hitChartAndRelPoint(adjustedX, adjustedY, row, col, dims)
	if !ok || chart == nil {
		return
	}
	if relX < 0 || relX >= chart.GraphWidth() {
		return
	}
	if vertical && (relY < 0 || relY >= chart.GraphHeight()) {
		return
	}
	if needFocus {
		g.setFocus(row, col)
	}

	direction := "out"
	if wheelUp {
		direction = "in"
	}
	if vertical {
		chart.HandleVerticalZoom(direction, relY)
	} else {
		chart.HandleZoom(direction, relX)
	}
	chart.DrawIfNeeded()
}

// StartInspection focuses the chart and begins inspection if inside the graph.
//
// If synced is true (Alt+right-press), a synchronized inspection session starts:
// the anchor X from the focused chart is broadcast to all visible charts.
func (g *SystemMetricsGrid) StartInspection(
	adjustedX, row, col int,
	dims GridDims,
	synced bool,
) {
	chart, relX, needFocus, ok := g.hitChartAndRelX(adjustedX, row, col, dims)
	if !ok || chart == nil {
		return
	}
	if relX < -2 || relX > chart.GraphWidth()+1 {
		return
	}
	if needFocus {
		g.setFocus(row, col)
	}

	chart.StartInspection(relX)
	chart.DrawIfNeeded()

	if synced {
		g.syncInspectActive = true
		if x, _, active := chart.InspectionData(); active {
			g.broadcastInspectAtDataX(x)
		}
	}
}

// UpdateInspection updates the crosshair position on the focused chart.
//
// If a synchronized inspection session is active, broadcasts the position
// to all visible charts on the current page.
func (g *SystemMetricsGrid) UpdateInspection(adjustedX, row, col int, dims GridDims) {
	chart, relX, _, ok := g.hitChartAndRelX(adjustedX, row, col, dims)
	if !ok || chart == nil || !chart.IsInspecting() {
		return
	}

	chart.UpdateInspection(relX)
	chart.DrawIfNeeded()

	if g.syncInspectActive {
		if x, _, active := chart.InspectionData(); active {
			g.broadcastInspectAtDataX(x)
		}
	}
}

// EndInspection clears inspection mode.
//
// If a synchronized session is active, clears inspection on all visible charts;
// otherwise clears only the focused chart.
func (g *SystemMetricsGrid) EndInspection() {
	if g.syncInspectActive {
		g.broadcastEndInspection()
		g.syncInspectActive = false
		return
	}

	chart := g.focusedChart()
	if chart == nil {
		return
	}
	chart.EndInspection()
	chart.DrawIfNeeded()
}

// broadcastInspectAtDataX applies InspectAtDataX to all visible charts on the current page.
func (g *SystemMetricsGrid) broadcastInspectAtDataX(anchorX float64) {
	for row := range g.currentPage {
		for col := range g.currentPage[row] {
			if chart := g.currentPage[row][col]; chart != nil {
				chart.InspectAtDataX(anchorX)
				chart.DrawIfNeeded()
			}
		}
	}
}

// broadcastEndInspection clears inspection on all visible charts on the current page.
func (g *SystemMetricsGrid) broadcastEndInspection() {
	for row := range g.currentPage {
		for col := range g.currentPage[row] {
			if chart := g.currentPage[row][col]; chart != nil && chart.IsInspecting() {
				chart.EndInspection()
				chart.DrawIfNeeded()
			}
		}
	}
}
