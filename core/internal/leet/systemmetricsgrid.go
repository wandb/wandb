package leet

import (
	"fmt"
	"sort"
	"time"

	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
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
	byBaseKey   map[string]systemMetricChart // baseKey -> chart
	ordered     []systemMetricChart          // charts sorted by title
	filtered    []systemMetricChart          // charts matching current filter
	currentPage [][]systemMetricChart        // current page view

	// Filter state.
	filter *Filter

	// Chart focus management.
	focus *Focus

	// Coloring state for per-plot mode.
	nextColor int // next palette index

	// lastDrawnCharts holds charts from the last visible page for parking.
	lastDrawnCharts map[systemMetricChart]struct{}

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
		byBaseKey:  make(map[string]systemMetricChart),
		ordered:    make([]systemMetricChart, 0),
		filtered:   make([]systemMetricChart, 0),
		filter:     filter,
		focus:      focusState,
		width:      width,
		height:     height,
		logger:     logger,
	}

	size := smg.effectiveGridSize()
	smg.currentPage = make([][]systemMetricChart, size.Rows)
	for row := range size.Rows {
		smg.currentPage[row] = make([]systemMetricChart, size.Cols)
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

// nextPaletteColor returns the next color from the active system palette.
func (g *SystemMetricsGrid) nextPaletteColor() AdaptiveColor {
	palette := GraphColors(g.config.SystemColorScheme())
	color := palette[g.nextColor%len(palette)]
	g.nextColor++
	return color
}

// anchoredSeriesColorProvider returns a provider that yields colors relative
// to a given base index in the current palette.
//
// The first call returns the color after the base color,
// so the base can be used for the first series.
func (g *SystemMetricsGrid) anchoredSeriesColorProvider(baseIdx int) func() AdaptiveColor {
	palette := GraphColors(g.config.SystemColorScheme())
	idx := baseIdx + 1
	return func() AdaptiveColor {
		c := palette[idx%len(palette)]
		idx++
		return c
	}
}

// createMetricChart creates a time series chart for a system metric.
func (g *SystemMetricsGrid) createMetricChart(def *MetricDef) systemMetricChart {
	dims := g.calculateChartDimensions()
	chartWidth := max(dims.CellW, MinMetricChartWidth)
	chartHeight := max(dims.CellH, MinMetricChartHeight)

	g.logger.Debug(fmt.Sprintf(
		"systemmetricsgrid: creating chart %dx%d for %v",
		chartWidth, chartHeight, def))

	// Base color by color mode.
	var (
		baseColor AdaptiveColor
		baseIdx   int
	)
	colorMode := g.config.SystemColorMode()
	palette := GraphColors(g.config.SystemColorScheme())
	if colorMode == ColorModePerSeries {
		baseColor = palette[0]
	} else {
		baseColor = g.nextPaletteColor()
		baseIdx = (g.nextColor - 1) % len(palette)
	}

	now := time.Now()
	lineChart := NewTimeSeriesLineChart(&TimeSeriesLineChartParams{
		Width:         chartWidth,
		Height:        chartHeight,
		Def:           def,
		BaseColor:     baseColor,
		ColorProvider: g.anchoredSeriesColorProvider(baseIdx),
		Now:           now,
	})
	lineChart.SetTailWindow(g.config.SystemTailWindow())

	if !def.Percentage {
		return lineChart
	}

	frenchFriesChart := NewFrenchFriesChart(&FrenchFriesChartParams{
		Width:  chartWidth,
		Height: chartHeight,
		Def:    def,
		Colors: FrenchFriesColors(g.config.FrenchFriesColorScheme()),
		Now:    now,
	})
	return newFrenchFriesToggleChart(lineChart, frenchFriesChart)
}

// AddDataPoint adds a new data point to the appropriate metric chart.
//
// Drawing is deferred to the next View() call to avoid redundant redraws
// when processing a batch of metrics from a single stats record.
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
}

// getOrCreateChart returns a chart for the given baseKey.
func (g *SystemMetricsGrid) getOrCreateChart(baseKey string, def *MetricDef) systemMetricChart {
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
func (g *SystemMetricsGrid) addChart(chart systemMetricChart) {
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
		g.currentPage = make([][]systemMetricChart, size.Rows)
		for row := range size.Rows {
			g.currentPage[row] = make([]systemMetricChart, size.Cols)
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
	g.NavigateFocus(0, 0)
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
	size := g.effectiveGridSize()
	if row < 0 || row >= size.Rows || col < 0 || col >= size.Cols ||
		row >= len(g.currentPage) || col >= len(g.currentPage[row]) {
		return false
	}
	chart := g.currentPage[row][col]
	if chart == nil {
		return false
	}

	g.ClearFocus()
	g.focus.Set(FocusSystemChart, row, col, chart.Title())
	return true
}

// NavigateFocus moves chart focus by (dr, dc) within the current page.
// On partial pages, vertical moves clamp to the last populated cell in the
// target row.
//
// Returns true if focus changed or was re-materialized.
func (g *SystemMetricsGrid) NavigateFocus(dr, dc int) bool {
	if len(g.currentPage) == 0 {
		return false
	}

	row, col := g.focus.Row, g.focus.Col
	if g.focusedChart() == nil {
		var ok bool
		row, col, ok = g.firstNonNilCell()
		if !ok {
			return false
		}
	}

	newRow := clamp(row+dr, 0, len(g.currentPage)-1)
	lastCol := g.lastNonNilCol(newRow)
	if lastCol < 0 {
		return false
	}

	newCol := clamp(col+dc, 0, lastCol)
	chart := g.currentPage[newRow][newCol]
	if chart == nil {
		return false
	}

	if g.focus.Type == FocusSystemChart &&
		g.focus.Row == newRow &&
		g.focus.Col == newCol &&
		g.focus.Title == chart.Title() {
		return false
	}

	return g.setFocus(newRow, newCol)
}

func (g *SystemMetricsGrid) firstNonNilCell() (int, int, bool) {
	for r, cells := range g.currentPage {
		for c, ch := range cells {
			if ch != nil {
				return r, c, true
			}
		}
	}
	return 0, 0, false
}

func (g *SystemMetricsGrid) lastNonNilCol(row int) int {
	if row >= len(g.currentPage) {
		return -1
	}
	for c := len(g.currentPage[row]) - 1; c >= 0; c-- {
		if g.currentPage[row][c] != nil {
			return c
		}
	}
	return -1
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

func (g *SystemMetricsGrid) FocusedChartScaleLabel() string {
	chart := g.focusedChart()
	if chart == nil {
		return ""
	}
	return chart.ScaleLabel()
}

func (g *SystemMetricsGrid) FocusedChartTitleDetail() string {
	chart := g.focusedChart()
	if chart == nil {
		return ""
	}
	return chart.TitleDetail()
}

func (g *SystemMetricsGrid) focusedChart() systemMetricChart {
	if g.focus.Type != FocusSystemChart || g.focus.Row < 0 || g.focus.Col < 0 {
		return nil
	}
	if g.focus.Row >= len(g.currentPage) || g.focus.Col >= len(g.currentPage[g.focus.Row]) {
		return nil
	}
	return g.currentPage[g.focus.Row][g.focus.Col]
}

func (g *SystemMetricsGrid) toggleFocusedChartLogY() bool {
	chart := g.focusedChart()
	if chart == nil || !chart.ToggleYScale() {
		return false
	}
	chart.DrawIfNeeded()
	return true
}

func (g *SystemMetricsGrid) toggleFocusedChartHeatmapMode() bool {
	chart := g.focusedChart()
	if chart == nil || !chart.SupportsHeatmap() || !chart.ToggleHeatmapMode() {
		return false
	}
	chart.DrawIfNeeded()
	return true
}

func (g *SystemMetricsGrid) cycleFocusedChartMode() bool {
	chart := g.focusedChart()
	if chart == nil {
		return false
	}

	if !chart.SupportsHeatmap() {
		if !chart.ToggleYScale() {
			return false
		}
		chart.DrawIfNeeded()
		return true
	}

	if chart.IsHeatmapMode() {
		if !chart.ToggleHeatmapMode() {
			return false
		}
		if chart.IsLogY() {
			chart.ToggleYScale()
		}
		chart.DrawIfNeeded()
		return true
	}

	if chart.IsLogY() {
		if !chart.ToggleHeatmapMode() {
			return false
		}
		chart.DrawIfNeeded()
		return true
	}

	if chart.ToggleYScale() {
		chart.DrawIfNeeded()
		return true
	}
	if chart.ToggleHeatmapMode() {
		chart.DrawIfNeeded()
		return true
	}
	return false
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

// drawVisible resizes and draws charts on the current page.
//
// Charts no longer visible are parked to reduce memory usage.
func (g *SystemMetricsGrid) drawVisible() {
	dims := g.calculateChartDimensions()

	currentCharts := make(map[systemMetricChart]struct{})
	for row := range g.currentPage {
		for col := range g.currentPage[row] {
			if chart := g.currentPage[row][col]; chart != nil {
				currentCharts[chart] = struct{}{}
			}
		}
	}

	for ch := range g.lastDrawnCharts {
		if _, stillVisible := currentCharts[ch]; !stillVisible {
			ch.Park()
		}
	}
	g.lastDrawnCharts = currentCharts

	for ch := range currentCharts {
		ch.Resize(dims.CellW, dims.CellH)
		ch.DrawIfNeeded()
	}
}

func (g *SystemMetricsGrid) syncFocusToCurrentPage() {
	if g.focus.Type != FocusSystemChart || g.focus.Title == "" {
		return
	}

	// If the chart at the current position still matches, keep it.
	// This avoids jumping when multiple charts share the same title.
	r, c := g.focus.Row, g.focus.Col
	if r >= 0 && c >= 0 && r < len(g.currentPage) && c < len(g.currentPage[r]) {
		if ch := g.currentPage[r][c]; ch != nil && ch.Title() == g.focus.Title {
			return
		}
	}

	// Position changed (e.g. chart order shifted) — scan by title.
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
//
// Dirty visible charts are drawn before rendering so that data added
// since the last frame is reflected without per-point draw overhead.
func (g *SystemMetricsGrid) View() string {
	dims := g.calculateChartDimensions()
	size := g.effectiveGridSize()

	// Draw any visible charts that received new data since the last frame.
	for row := range g.currentPage {
		for col := range g.currentPage[row] {
			if chart := g.currentPage[row][col]; chart != nil {
				chart.DrawIfNeeded()
			}
		}
	}

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

			renderedTitle := renderSystemMetricChartTitle(metricChart, dims.CellW)

			boxContent := lipgloss.JoinVertical(lipgloss.Left, renderedTitle, chartView)
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

type systemMetricHeaderExtras struct {
	detail string
	mode   string
}

func renderSystemMetricChartTitle(chart systemMetricChart, maxWidth int) string {
	if chart == nil || maxWidth <= 0 {
		return ""
	}

	extras := chartHeaderExtras(chart)
	showDetail := extras.detail != ""
	showMode := extras.mode != ""
	for {
		suffixWidth := 0
		if showDetail {
			suffixWidth += lipgloss.Width(extras.detail)
		}
		if showMode {
			suffixWidth += lipgloss.Width(extras.mode)
		}
		if maxWidth-suffixWidth >= 1 {
			break
		}
		if showMode {
			showMode = false
			continue
		}
		if showDetail {
			showDetail = false
			continue
		}
		break
	}

	suffixWidth := 0
	if showDetail {
		suffixWidth += lipgloss.Width(extras.detail)
	}
	if showMode {
		suffixWidth += lipgloss.Width(extras.mode)
	}
	titleWidth := max(maxWidth-suffixWidth, 1)
	label := titleStyle.Render(TruncateTitle(chart.Title(), titleWidth))
	if showDetail {
		label += seriesCountStyle.Render(extras.detail)
	}
	if showMode {
		label += navInfoStyle.Render(extras.mode)
	}
	return label
}

func chartHeaderExtras(chart systemMetricChart) systemMetricHeaderExtras {
	extras := systemMetricHeaderExtras{}
	if detail := chart.TitleDetail(); detail != "" {
		extras.detail = " " + detail
	}
	switch {
	case chart.IsHeatmapMode():
		extras.mode = " [heatmap]"
	case chart.IsLogY():
		extras.mode = " [log]"
	}
	return extras
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
) (chart systemMetricChart, relX int, needFocus, ok bool) {
	chart, relX, _, needFocus, ok = g.hitChartAndRelPos(adjustedX, 0, row, col, dims)
	return chart, relX, needFocus, ok
}

// hitChartAndRelPos returns the chart under (row, col) on the grid
// with relative graph-local coordinates.
func (g *SystemMetricsGrid) hitChartAndRelPos(
	adjustedX, adjustedY, row, col int,
	dims GridDims,
) (chart systemMetricChart, relX, relY int, needFocus, ok bool) {
	size := g.effectiveGridSize()
	if row < 0 || row >= size.Rows || col < 0 || col >= size.Cols ||
		row >= len(g.currentPage) || col >= len(g.currentPage[row]) {
		return nil, 0, 0, false, false
	}
	chart = g.currentPage[row][col]
	if chart == nil {
		return nil, 0, 0, false, false
	}

	chartStartX := col * dims.CellWWithPadding
	chartStartY := row * dims.CellHWithPadding
	relX = adjustedX - (chartStartX + chart.GraphStartX())
	relY = adjustedY - (chartStartY + chart.GraphStartY())

	needFocus = g.focus.Type != FocusSystemChart || g.focus.Row != row || g.focus.Col != col
	return chart, relX, relY, needFocus, true
}

// HandleWheel performs zoom handling on a system chart at (row, col).
func (g *SystemMetricsGrid) HandleWheel(
	adjustedX, row, col int,
	dims GridDims,
	wheelUp bool,
) {
	chart, relX, needFocus, ok := g.hitChartAndRelX(adjustedX, row, col, dims)
	if !ok || chart == nil {
		return
	}
	if relX < 0 || relX >= chart.GraphWidth() {
		return
	}
	if needFocus {
		g.setFocus(row, col)
	}

	direction := "out"
	if wheelUp {
		direction = "in"
	}
	chart.HandleZoom(direction, relX)
	chart.DrawIfNeeded()
}

// StartInspection focuses the chart and begins inspection if inside the graph.
//
// If synced is true (Alt+right-press), a synchronized inspection session starts:
// the anchor X from the focused chart is broadcast to all visible charts.
func (g *SystemMetricsGrid) StartInspection(
	adjustedX, adjustedY, row, col int,
	dims GridDims,
	synced bool,
) {
	chart, relX, relY, needFocus, ok := g.hitChartAndRelPos(adjustedX, adjustedY, row, col, dims)
	if !ok || chart == nil {
		return
	}
	if relX < -2 || relX > chart.GraphWidth()+1 || relY < -2 || relY > chart.GraphHeight()+1 {
		return
	}
	if needFocus {
		g.setFocus(row, col)
	}

	chart.StartInspectionAt(relX, relY)
	chart.DrawIfNeeded()

	if !synced {
		return
	}

	if x, _, active := chart.InspectionData(); active {
		g.syncInspectActive = true
		g.broadcastInspectAtDataX(x)
	}
}

// UpdateInspection updates the crosshair position on the focused chart.
//
// If a synchronized inspection session is active, broadcasts the position
// to all visible charts on the current page.
func (g *SystemMetricsGrid) UpdateInspection(adjustedX, adjustedY, row, col int, dims GridDims) {
	chart, relX, relY, _, ok := g.hitChartAndRelPos(adjustedX, adjustedY, row, col, dims)
	if !ok || chart == nil || !chart.IsInspecting() {
		return
	}

	chart.UpdateInspectionAt(relX, relY)
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
