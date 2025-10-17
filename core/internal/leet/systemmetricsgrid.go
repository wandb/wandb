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
	config *ConfigManager

	chartsByMetric map[string]*TimeSeriesLineChart
	orderedCharts  []*TimeSeriesLineChart

	charts    [][]*TimeSeriesLineChart
	navigator GridNavigator

	focusState *FocusState

	width, height int

	nextColorIdx int

	logger *observability.CoreLogger
}

func NewSystemMetricsGrid(
	width, height int,
	config *ConfigManager,
	focusState *FocusState,
	logger *observability.CoreLogger,
) *SystemMetricsGrid {
	grid := &SystemMetricsGrid{
		config:         config,
		chartsByMetric: make(map[string]*TimeSeriesLineChart),
		orderedCharts:  make([]*TimeSeriesLineChart, 0),
		focusState:     focusState,
		width:          width,
		height:         height,
		logger:         logger,
	}

	size := grid.effectiveGridSize()
	grid.charts = make([][]*TimeSeriesLineChart, size.Rows)
	for row := range size.Rows {
		grid.charts[row] = make([]*TimeSeriesLineChart, size.Cols)
	}

	logger.Debug(fmt.Sprintf("SystemMetricsGrid: created with dimensions %dx%d (grid %dx%d)",
		width, height, size.Rows, size.Cols))

	return grid
}

// effectiveGridSize returns the grid size that can fit in the current viewport.
func (g *SystemMetricsGrid) effectiveGridSize() GridSize {
	cfgRows, cfgCols := g.config.SystemGrid()
	spec := GridSpec{
		Rows:        cfgRows,
		Cols:        cfgCols,
		MinCellW:    MinMetricChartWidth,
		MinCellH:    MinMetricChartHeight,
		HeaderLines: 0,
	}
	return EffectiveGridSize(g.width, g.height, spec)
}

// MetricChartDimensions represents dimensions for system metric charts.
type MetricChartDimensions struct {
	ChartWidth, ChartHeight                       int
	ChartWidthWithPadding, ChartHeightWithPadding int
}

// calculateChartDimensions computes dimensions for system metric charts.
func (g *SystemMetricsGrid) calculateChartDimensions() MetricChartDimensions {
	cfgRows, cfgCols := g.config.SystemGrid()
	spec := GridSpec{
		Rows:        cfgRows,
		Cols:        cfgCols,
		MinCellW:    MinMetricChartWidth,
		MinCellH:    MinMetricChartHeight,
		HeaderLines: 0,
	}

	size := EffectiveGridSize(g.width, g.height, spec)
	d := ComputeGridDims(g.width, g.height, spec, size)

	return MetricChartDimensions{
		ChartWidth:             d.CellW,
		ChartHeight:            d.CellH,
		ChartWidthWithPadding:  d.CellWWithPadding,
		ChartHeightWithPadding: d.CellHWithPadding,
	}
}

// getNextColor returns the next color from the palette.
func (g *SystemMetricsGrid) getNextColor() string {
	colors := colorSchemes[g.config.SystemColorScheme()]
	color := colors[g.nextColorIdx%len(colors)]
	g.nextColorIdx++
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

	chartWidth := max(dims.ChartWidth, MinMetricChartWidth)
	chartHeight := max(dims.ChartHeight, MinMetricChartHeight)

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
		firstColor = g.getNextColor()
		// getNextColor() advanced g.nextColorIdx; base is the previous index.
		baseIdx = (g.nextColorIdx - 1) % len(colors)
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
	chart, exists := g.chartsByMetric[baseKey]
	if !exists {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.getOrCreateChart: creating new chart for baseKey=%s", baseKey))

		chart = g.createMetricChart(def, baseKey)
		g.chartsByMetric[baseKey] = chart

		g.addChartToGrid(chart)
	}
	return chart
}

// addChartToGrid adds a chart to the ordered list and updates pagination.
func (g *SystemMetricsGrid) addChartToGrid(chart *TimeSeriesLineChart) {
	g.orderedCharts = append(g.orderedCharts, chart)
	sort.Slice(g.orderedCharts, func(i, j int) bool {
		return g.orderedCharts[i].title < g.orderedCharts[j].title
	})

	size := g.effectiveGridSize()
	g.navigator.UpdateTotalPages(len(g.orderedCharts), ItemsPerPage(size))
	g.LoadCurrentPage()

	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.addChartToGrid: chart added, total=%d, pages=%d",
		len(g.orderedCharts), g.navigator.TotalPages()))
}

// LoadCurrentPage loads charts for the current page.
func (g *SystemMetricsGrid) LoadCurrentPage() {
	size := g.effectiveGridSize()

	if len(g.charts) != size.Rows ||
		(len(g.charts) > 0 && len(g.charts[0]) != size.Cols) {
		g.charts = make([][]*TimeSeriesLineChart, size.Rows)
		for row := range size.Rows {
			g.charts[row] = make([]*TimeSeriesLineChart, size.Cols)
		}
	}

	for row := range size.Rows {
		for col := range size.Cols {
			g.charts[row][col] = nil
		}
	}

	startIdx, endIdx := g.navigator.GetPageBounds(
		len(g.orderedCharts), ItemsPerPage(size))

	idx := startIdx
	for row := 0; row < size.Rows && idx < endIdx; row++ {
		for col := 0; col < size.Cols && idx < endIdx; col++ {
			if g.orderedCharts[idx].hasData {
				g.charts[row][col] = g.orderedCharts[idx]
			}
			idx++
		}
	}
}

// Navigate changes pages.
func (g *SystemMetricsGrid) Navigate(direction int) {
	if !g.navigator.Navigate(direction) {
		return
	}

	g.ClearFocus()
	g.LoadCurrentPage()
}

// HandleMouseClick handles mouse clicks for chart selection.
func (g *SystemMetricsGrid) HandleMouseClick(row, col int) bool {
	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: row=%d, col=%d", row, col))

	if g.focusState.Type == FocusSystemChart &&
		row == g.focusState.Row && col == g.focusState.Col {
		g.logger.Debug("SystemMetricsGrid.HandleMouseClick: clicking on focused chart - unfocusing")
		g.ClearFocus()
		return false
	}

	g.ClearFocus()

	size := g.effectiveGridSize()

	if row >= 0 && row < size.Rows && col >= 0 && col < size.Cols &&
		row < len(g.charts) && col < len(g.charts[row]) &&
		g.charts[row][col] != nil {
		chart := g.charts[row][col]
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.HandleMouseClick: focusing chart at row=%d, col=%d", row, col))

		g.focusState.Type = FocusSystemChart
		g.focusState.Row = row
		g.focusState.Col = col
		g.focusState.Title = chart.fullTitle

		return true
	}

	return false
}

// ClearFocus removes focus from all charts.
func (g *SystemMetricsGrid) ClearFocus() {
	if g.focusState.Type == FocusSystemChart {
		g.focusState.Type = FocusNone
		g.focusState.Row = -1
		g.focusState.Col = -1
		g.focusState.Title = ""
	}
}

// GetFocusedChartTitle returns the title of the focused chart.
func (g *SystemMetricsGrid) GetFocusedChartTitle() string {
	if g.focusState.Type == FocusSystemChart {
		return g.focusState.Title
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
	if dims.ChartWidth <= 0 || dims.ChartHeight <= 0 ||
		dims.ChartWidth < MinMetricChartWidth ||
		dims.ChartHeight < MinMetricChartHeight {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.Resize: calculated dimensions %dx%d invalid, skipping",
			dims.ChartWidth, dims.ChartHeight))
		return
	}

	size := g.effectiveGridSize()
	g.navigator.UpdateTotalPages(len(g.orderedCharts), ItemsPerPage(size))

	for _, metricChart := range g.chartsByMetric {
		if metricChart != nil && metricChart.chart != nil {
			metricChart.chart.Resize(dims.ChartWidth, dims.ChartHeight)
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
			cellIdx := g.navigator.CurrentPage()*ItemsPerPage(size) +
				row*size.Cols + col

			if row < len(g.charts) && col < len(g.charts[row]) &&
				g.charts[row][col] != nil && cellIdx < len(g.orderedCharts) {
				metricChart := g.charts[row][col]
				chartView := metricChart.chart.View()

				titleText := metricChart.fullTitle
				if len(metricChart.series) > 1 {
					countStyle := lipgloss.NewStyle().Foreground(colorSubtle)
					count := fmt.Sprintf(" [%d]", len(metricChart.series))

					availableWidth := max(
						dims.ChartWidthWithPadding-4-lipgloss.Width(count), 10)
					displayTitle := TruncateTitle(titleText, availableWidth)
					titleText = titleStyle.Render(displayTitle) +
						countStyle.Render(count)
				} else {
					availableWidth := max(dims.ChartWidthWithPadding-4, 10)
					titleText = titleStyle.Render(
						TruncateTitle(titleText, availableWidth))
				}

				boxContent := lipgloss.JoinVertical(lipgloss.Left, titleText, chartView)

				boxStyle := borderStyle
				if g.focusState.Type == FocusSystemChart &&
					row == g.focusState.Row && col == g.focusState.Col {
					boxStyle = focusedBorderStyle
				}

				box := boxStyle.Render(boxContent)
				cell := lipgloss.Place(
					dims.ChartWidthWithPadding,
					dims.ChartHeightWithPadding,
					lipgloss.Left,
					lipgloss.Top,
					box,
				)
				cols = append(cols, cell)
			} else {
				cols = append(cols, lipgloss.NewStyle().
					Width(dims.ChartWidthWithPadding).
					Height(dims.ChartHeightWithPadding).
					Render(""))
			}
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}

	grid := lipgloss.JoinVertical(lipgloss.Left, rows...)

	// Bottom filler
	used := size.Rows * dims.ChartHeightWithPadding
	if extra := g.height - used; extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		grid = lipgloss.JoinVertical(lipgloss.Left, grid, filler)
	}

	return grid
}

// GetChartCount returns the number of charts with data.
func (g *SystemMetricsGrid) GetChartCount() int {
	count := 0
	for _, chart := range g.orderedCharts {
		if chart.hasData {
			count++
		}
	}
	return count
}
