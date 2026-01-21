package leet

import (
	"fmt"
	"sort"
	"time"

	"github.com/charmbracelet/lipgloss"

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
	config *ConfigManager
	logger *observability.CoreLogger

	// Viewport dimensions.
	width, height int

	// Pagination state.
	nav GridNavigator

	// Charts state.
	byBaseKey   map[string]*TimeSeriesLineChart // baseKey -> chart
	ordered     []*TimeSeriesLineChart          // charts sorted by title
	currentPage [][]*TimeSeriesLineChart        // current page view

	// Chart focus management.
	focus *Focus

	// Coloring state for per-plot mode.
	nextColor int // next palette index
}

func NewSystemMetricsGrid(
	width, height int,
	config *ConfigManager,
	focusState *Focus,
	logger *observability.CoreLogger,
) *SystemMetricsGrid {
	smg := &SystemMetricsGrid{
		config:    config,
		byBaseKey: make(map[string]*TimeSeriesLineChart),
		ordered:   make([]*TimeSeriesLineChart, 0),
		focus:     focusState,
		width:     width,
		height:    height,
		logger:    logger,
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
	cfgRows, cfgCols := g.config.SystemGrid()
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
	cfgRows, cfgCols := g.config.SystemGrid()
	return EffectiveGridSize(g.width, g.height, GridSpec{
		Rows:        cfgRows,
		Cols:        cfgCols,
		MinCellW:    MinMetricChartWidth,
		MinCellH:    MinMetricChartHeight,
		HeaderLines: 0,
	})
}

// nextColorHex returns the next color from the palette.
func (g *SystemMetricsGrid) nextColorHex() lipgloss.AdaptiveColor {
	colors := colorSchemes[g.config.SystemColorScheme()]
	color := colors[g.nextColor%len(colors)]
	g.nextColor++
	return color
}

// anchoredSeriesColorProvider returns a provider that yields colors relative
// to a given base index in the current palette.
//
// The first call returns the color *after* the base color,
// so the base can be used for the first series.
func (g *SystemMetricsGrid) anchoredSeriesColorProvider(baseIdx int) func() lipgloss.AdaptiveColor {
	colors := colorSchemes[g.config.SystemColorScheme()]
	idx := baseIdx + 1
	return func() lipgloss.AdaptiveColor {
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
		baseColor lipgloss.AdaptiveColor
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

	return NewTimeSeriesLineChart(&TimeSeriesLineChartParams{
		chartWidth, chartHeight,
		def,
		baseColor,
		g.anchoredSeriesColorProvider(baseIdx),
		time.Now(),
	})
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
}

// getOrCreateChart returns a TimeSeriesLineChart for the given baseKey.
func (g *SystemMetricsGrid) getOrCreateChart(baseKey string, def *MetricDef) *TimeSeriesLineChart {
	chart, exists := g.byBaseKey[baseKey]
	if !exists {
		g.logger.Debug(fmt.Sprintf("systemmetricsgrid: creating new chart for baseKey=%s", baseKey))
		chart = g.createMetricChart(def)
		g.byBaseKey[baseKey] = chart
		g.addChartToGrid(chart)
	}
	return chart
}

// addChartToGrid adds a chart to the ordered list and updates pagination.
func (g *SystemMetricsGrid) addChartToGrid(chart *TimeSeriesLineChart) {
	g.ordered = append(g.ordered, chart)
	sort.Slice(g.ordered, func(i, j int) bool {
		return g.ordered[i].Title() < g.ordered[j].Title()
	})

	size := g.effectiveGridSize()
	g.nav.UpdateTotalPages(len(g.ordered), ItemsPerPage(size))
	g.LoadCurrentPage()

	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.addChartToGrid: chart added, total=%d, pages=%d",
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

	startIdx, endIdx := g.nav.PageBounds(len(g.ordered), ItemsPerPage(size))

	idx := startIdx
	for row := 0; row < size.Rows && idx < endIdx; row++ {
		for col := 0; col < size.Cols && idx < endIdx; col++ {
			g.currentPage[row][col] = g.ordered[idx]
			idx++
		}
	}
}

// Navigate changes pages.
func (g *SystemMetricsGrid) Navigate(direction int) {
	if !g.nav.Navigate(direction) {
		return
	}

	g.ClearFocus()
	g.LoadCurrentPage()
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

	g.ClearFocus()
	size := g.effectiveGridSize()

	if row >= 0 && row < size.Rows && col >= 0 && col < size.Cols &&
		row < len(g.currentPage) && col < len(g.currentPage[row]) &&
		g.currentPage[row][col] != nil {
		chart := g.currentPage[row][col]
		g.logger.Debug(fmt.Sprintf(
			"systemmetricsgrid: HandleMouseClick: focusing chart at row=%d, col=%d", row, col))

		g.focus.Type = FocusSystemChart
		g.focus.Row = row
		g.focus.Col = col
		g.focus.Title = chart.Title()

		return true
	}

	return false
}

// ClearFocus removes focus from all charts.
func (g *SystemMetricsGrid) ClearFocus() {
	if g.focus.Type == FocusSystemChart {
		g.focus.Type = FocusNone
		g.focus.Row = -1
		g.focus.Col = -1
		g.focus.Title = ""
	}
}

// FocusedChartTitle returns the title of the focused chart.
func (g *SystemMetricsGrid) FocusedChartTitle() string {
	if g.focus.Type == FocusSystemChart {
		return g.focus.Title
	}
	return ""
}

// Resize updates viewport dimensions and resizes/redraws all charts.
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
	g.nav.UpdateTotalPages(len(g.ordered), ItemsPerPage(size))

	for _, metricChart := range g.byBaseKey {
		if metricChart == nil || metricChart.chart == nil {
			continue
		}

		metricChart.chart.Resize(dims.CellW, dims.CellH)
		actualWidth := metricChart.chart.Width()
		actualHeight := metricChart.chart.Height()
		if actualWidth > 0 && actualHeight > 0 &&
			actualWidth >= MinMetricChartWidth &&
			actualHeight >= MinMetricChartHeight {
			if len(metricChart.series) > 0 {
				metricChart.chart.DrawBrailleAll()
			} else {
				metricChart.chart.DrawBraille()
			}
		}
	}

	g.LoadCurrentPage()
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
			chartView := metricChart.chart.View()

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
