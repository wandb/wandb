package leet

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/NimbleMarkets/ntcharts/linechart/timeserieslinechart"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

// SystemMetricsGrid manages the grid of system metric charts.
type SystemMetricsGrid struct {
	// Configuration and logging.
	config *ConfigManager
	logger *observability.CoreLogger

	// Layout and navigation.
	width, height int
	nav           GridNavigator // pagination state

	// Charts state.
	byBaseKey map[string]*TimeSeriesLineChart // baseKey -> chart
	ordered   []*TimeSeriesLineChart          // charts sorted by title
	grid      [][]*TimeSeriesLineChart        // current page view

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
	grid := &SystemMetricsGrid{
		config:    config,
		byBaseKey: make(map[string]*TimeSeriesLineChart),
		ordered:   make([]*TimeSeriesLineChart, 0),
		focus:     focusState,
		width:     width,
		height:    height,
		logger:    logger,
	}

	size := grid.effectiveGridSize()
	grid.grid = make([][]*TimeSeriesLineChart, size.Rows)
	for row := range size.Rows {
		grid.grid[row] = make([]*TimeSeriesLineChart, size.Cols)
	}

	logger.Debug(fmt.Sprintf("SystemMetricsGrid: created with dimensions %dx%d (grid %dx%d)",
		width, height, size.Rows, size.Cols))

	return grid
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
func (g *SystemMetricsGrid) nextColorHex() string {
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
func (g *SystemMetricsGrid) anchoredSeriesColorProvider(baseIdx int) func() string {
	colors := colorSchemes[g.config.SystemColorScheme()]
	idx := baseIdx + 1
	return func() string {
		c := colors[idx%len(colors)]
		idx++
		return c
	}
}

// createMetricChart creates a time series chart for a system metric.
func (g *SystemMetricsGrid) createMetricChart(def *MetricDef, baseKey string) *TimeSeriesLineChart {
	dims := g.calculateChartDimensions()

	chartWidth := max(dims.CellW, MinMetricChartWidth)
	chartHeight := max(dims.CellH, MinMetricChartHeight)

	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.createMetricChart: creating chart %dx%d for %s",
		chartWidth, chartHeight, baseKey))

	minY, maxY := def.MinY, def.MaxY
	now := time.Now()
	// TODO: make this configurable.
	minTime := now.Add(-10 * time.Minute)

	// Get first color based on color mode.
	var (
		firstColor string
		baseIdx    int
	)

	colorMode := g.config.SystemColorMode()
	colors := colorSchemes[g.config.SystemColorScheme()]

	if colorMode == ColorModePerSeries {
		// All charts share the same base color.
		firstColor = colors[0]
	} else {
		// Per-plot mode: each chart gets the next color from the palette.
		firstColor = g.nextColorHex()
		baseIdx = (g.nextColor - 1) % len(colors)
	}

	graphStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(firstColor))

	fullTitle := def.Title
	if def.Unit != "" {
		fullTitle = fmt.Sprintf("%s (%s)", def.Title, def.Unit)
	}

	chart := timeserieslinechart.New(chartWidth, chartHeight,
		timeserieslinechart.WithTimeRange(minTime, now),
		timeserieslinechart.WithYRange(minY, maxY),
		timeserieslinechart.WithAxesStyles(axisStyle, labelStyle),
		timeserieslinechart.WithStyle(graphStyle),
		timeserieslinechart.WithUpdateHandler(
			timeserieslinechart.SecondUpdateHandler(1)),
		timeserieslinechart.WithXLabelFormatter(
			timeserieslinechart.HourTimeLabelFormatter()),
		timeserieslinechart.WithYLabelFormatter(func(i int, v float64) string {
			return FormatYLabel(v, def.Unit)
		}),
		timeserieslinechart.WithXYSteps(2, 3),
	)

	return &TimeSeriesLineChart{
		chart:         &chart,
		def:           def,
		baseKey:       baseKey,
		title:         def.Title,
		fullTitle:     fullTitle,
		series:        make(map[string]int),
		seriesColors:  []string{firstColor},
		colorProvider: g.anchoredSeriesColorProvider(baseIdx),
		hasData:       false,
		lastUpdate:    now,
		minValue:      math.Inf(1),
		maxValue:      math.Inf(-1),
	}
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

// getOrCreateChart retrieves an existing chart or creates a new one.
func (g *SystemMetricsGrid) getOrCreateChart(baseKey string, def *MetricDef) *TimeSeriesLineChart {
	chart, exists := g.byBaseKey[baseKey]
	if !exists {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.getOrCreateChart: creating new chart for baseKey=%s", baseKey))

		chart = g.createMetricChart(def, baseKey)
		g.byBaseKey[baseKey] = chart

		g.addChartToGrid(chart)
	}
	return chart
}

// addChartToGrid adds a chart to the ordered list and updates pagination.
func (g *SystemMetricsGrid) addChartToGrid(chart *TimeSeriesLineChart) {
	g.ordered = append(g.ordered, chart)
	sort.Slice(g.ordered, func(i, j int) bool {
		return g.ordered[i].title < g.ordered[j].title
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

	if len(g.grid) != size.Rows ||
		(len(g.grid) > 0 && len(g.grid[0]) != size.Cols) {
		g.grid = make([][]*TimeSeriesLineChart, size.Rows)
		for row := range size.Rows {
			g.grid[row] = make([]*TimeSeriesLineChart, size.Cols)
		}
	}

	for row := range size.Rows {
		for col := range size.Cols {
			g.grid[row][col] = nil
		}
	}

	startIdx, endIdx := g.nav.PageBounds(
		len(g.ordered), ItemsPerPage(size))

	idx := startIdx
	for row := 0; row < size.Rows && idx < endIdx; row++ {
		for col := 0; col < size.Cols && idx < endIdx; col++ {
			if g.ordered[idx].hasData {
				g.grid[row][col] = g.ordered[idx]
			}
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
func (g *SystemMetricsGrid) HandleMouseClick(row, col int) bool {
	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: row=%d, col=%d", row, col))

	if g.focus.Type == FocusSystemChart &&
		row == g.focus.Row && col == g.focus.Col {
		g.logger.Debug("SystemMetricsGrid.HandleMouseClick: clicking on focused chart - unfocusing")
		g.ClearFocus()
		return false
	}

	g.ClearFocus()

	size := g.effectiveGridSize()

	if row >= 0 && row < size.Rows && col >= 0 && col < size.Cols &&
		row < len(g.grid) && col < len(g.grid[row]) &&
		g.grid[row][col] != nil {
		chart := g.grid[row][col]
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.HandleMouseClick: focusing chart at row=%d, col=%d", row, col))

		g.focus.Type = FocusSystemChart
		g.focus.Row = row
		g.focus.Col = col
		g.focus.Title = chart.fullTitle

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

// Resize updates dimensions and resizes all charts.
func (g *SystemMetricsGrid) Resize(width, height int) {
	if width <= 0 || height <= 0 {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.Resize: invalid dimensions %dx%d, skipping", width, height))
		return
	}

	g.width = width
	g.height = height

	dims := g.calculateChartDimensions()
	if dims.CellW <= 0 || dims.CellH <= 0 ||
		dims.CellW < MinMetricChartWidth ||
		dims.CellH < MinMetricChartHeight {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.Resize: calculated dimensions %dx%d invalid, skipping",
			dims.CellW, dims.CellH))
		return
	}

	size := g.effectiveGridSize()
	g.nav.UpdateTotalPages(len(g.ordered), ItemsPerPage(size))

	for _, metricChart := range g.byBaseKey {
		if metricChart != nil && metricChart.chart != nil {
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
	}

	g.LoadCurrentPage()
}

// View renders the metrics grid.
func (g *SystemMetricsGrid) View() string {
	dims := g.calculateChartDimensions()
	size := g.effectiveGridSize()

	var rows []string
	for row := range size.Rows {
		var cols []string
		for col := range size.Cols {
			cellIdx := g.nav.CurrentPage()*ItemsPerPage(size) +
				row*size.Cols + col

			if row < len(g.grid) && col < len(g.grid[row]) &&
				g.grid[row][col] != nil && cellIdx < len(g.ordered) {
				metricChart := g.grid[row][col]
				chartView := metricChart.chart.View()

				titleText := metricChart.fullTitle
				if len(metricChart.series) > 1 {
					countStyle := lipgloss.NewStyle().Foreground(colorSubtle)
					count := fmt.Sprintf(" [%d]", len(metricChart.series))

					availableWidth := max(
						dims.CellWWithPadding-4-lipgloss.Width(count), 10)
					displayTitle := TruncateTitle(titleText, availableWidth)
					titleText = titleStyle.Render(displayTitle) +
						countStyle.Render(count)
				} else {
					availableWidth := max(dims.CellWWithPadding-4, 10)
					titleText = titleStyle.Render(
						TruncateTitle(titleText, availableWidth))
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
			} else {
				cols = append(cols, lipgloss.NewStyle().
					Width(dims.CellWWithPadding).
					Height(dims.CellHWithPadding).
					Render(""))
			}
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}

	grid := lipgloss.JoinVertical(lipgloss.Left, rows...)

	// Bottom filler
	used := size.Rows * dims.CellHWithPadding
	if extra := g.height - used; extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		grid = lipgloss.JoinVertical(lipgloss.Left, grid, filler)
	}

	return grid
}

// ChartCount returns the number of charts with data.
func (g *SystemMetricsGrid) ChartCount() int {
	count := 0
	for _, chart := range g.ordered {
		if chart.hasData {
			count++
		}
	}
	return count
}
