package leet

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/NimbleMarkets/ntcharts/linechart/timeserieslinechart"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

// RightSidebar represents a collapsible right sidebar panel.
type RightSidebar struct {
	config         *ConfigManager
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int
	animationStep  int
	animationTimer time.Time

	// System metrics grid
	metricsGrid *SystemMetricsGrid

	// Logger
	logger *observability.CoreLogger
}

// SystemMetricChart represents a single metric chart that can have multiple series
type SystemMetricChart struct {
	chart        *timeserieslinechart.Model
	def          *MetricDef // Metric definition
	baseKey      string
	title        string
	fullTitle    string         // Full title with unit
	series       map[string]int // series name -> color index
	seriesColors []string       // colors assigned to each series
	hasData      bool
	lastUpdate   time.Time
	minValue     float64 // Track min value for auto-range
	maxValue     float64 // Track max value for auto-range
}

// SystemMetricsGrid manages the grid of system metric charts
type SystemMetricsGrid struct {
	config *ConfigManager

	// Dynamic chart management
	chartsByMetric map[string]*SystemMetricChart // base metric key -> chart
	orderedCharts  []*SystemMetricChart          // alphabetically ordered list

	// Grid display
	charts       [][]*SystemMetricChart // Grid arrangement
	currentPage  int
	totalPages   int
	focusedRow   int
	focusedCol   int
	focusedChart *SystemMetricChart // Currently focused chart
	width        int
	height       int

	// Color management
	nextColorIdx int

	// Logger
	logger *observability.CoreLogger
}

// NewSystemMetricsGrid creates a new system metrics grid
func NewSystemMetricsGrid(width, height int, config *ConfigManager, logger *observability.CoreLogger) *SystemMetricsGrid {
	gridRows, gridCols := config.GetSystemGrid()

	grid := &SystemMetricsGrid{
		config:         config,
		chartsByMetric: make(map[string]*SystemMetricChart),
		orderedCharts:  make([]*SystemMetricChart, 0),
		charts:         make([][]*SystemMetricChart, gridRows),
		currentPage:    0,
		focusedRow:     -1,
		focusedCol:     -1,
		width:          width,
		height:         height,
		nextColorIdx:   0,
		logger:         logger,
	}

	// Initialize grid rows
	for row := 0; row < gridRows; row++ {
		grid.charts[row] = make([]*SystemMetricChart, gridCols)
	}

	logger.Debug(fmt.Sprintf("SystemMetricsGrid: created with dimensions %dx%d", width, height))

	return grid
}

// getNextColor returns the next color from the wandb-vibe-10 palette.
func (g *SystemMetricsGrid) getNextColor() string {
	// TODO: make this configurable
	colors := colorSchemes["wandb-vibe-10"]
	color := colors[g.nextColorIdx%len(colors)]
	g.nextColorIdx++
	return color
}

// createMetricChart creates a time series chart for a system metric.
func (g *SystemMetricsGrid) createMetricChart(def *MetricDef, baseKey string) *SystemMetricChart {
	dims := g.calculateChartDimensions()

	// Ensure minimum dimensions to prevent panic
	chartWidth := dims.ChartWidth
	chartHeight := dims.ChartHeight
	if chartWidth < MinMetricChartWidth {
		chartWidth = MinMetricChartWidth
	}
	if chartHeight < MinMetricChartHeight {
		chartHeight = MinMetricChartHeight
	}

	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.createMetricChart: creating chart with dimensions %dx%d for %s", chartWidth, chartHeight, baseKey))

	// Determine initial Y range
	minY := def.MinY
	maxY := def.MaxY

	// Create the chart
	now := time.Now()
	// TODO: make the display interval configurable.
	minTime := now.Add(-5 * time.Minute)

	// Use the first color for the default series
	firstColor := g.getNextColor()
	graphStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(firstColor))

	// Create full title with unit
	fullTitle := def.Title
	if def.Unit != "" {
		fullTitle = fmt.Sprintf("%s (%s)", def.Title, def.Unit)
	}

	chart := timeserieslinechart.New(chartWidth, chartHeight,
		timeserieslinechart.WithTimeRange(minTime, now),
		timeserieslinechart.WithYRange(minY, maxY),
		timeserieslinechart.WithAxesStyles(axisStyle, labelStyle),
		timeserieslinechart.WithStyle(graphStyle),
		timeserieslinechart.WithUpdateHandler(timeserieslinechart.SecondUpdateHandler(1)),
		timeserieslinechart.WithXLabelFormatter(timeserieslinechart.HourTimeLabelFormatter()),
		timeserieslinechart.WithYLabelFormatter(func(i int, v float64) string {
			return FormatYLabel(v, def.Unit)
		}),
		timeserieslinechart.WithXYSteps(2, 3),
	)

	// Create the metric chart wrapper
	metricChart := &SystemMetricChart{
		chart:        &chart,
		def:          def,
		baseKey:      baseKey,
		title:        def.Title,
		fullTitle:    fullTitle,
		series:       make(map[string]int),
		seriesColors: []string{firstColor},
		hasData:      false,
		lastUpdate:   now,
		minValue:     math.Inf(1),
		maxValue:     math.Inf(-1),
	}

	return metricChart
}

// AddDataPoint adds a new data point to the appropriate metric chart.
//
//gocyclo:ignore
func (g *SystemMetricsGrid) AddDataPoint(metricName string, timestamp int64, value float64) {
	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: metric=%s, timestamp=%d, value=%f", metricName, timestamp, value))

	// Match metric to definition
	def := MatchMetricDef(metricName)
	if def == nil {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: no definition found for metric=%s", metricName))
		return
	}

	// Extract base key and series name
	baseKey := ExtractBaseKey(metricName)
	seriesName := ExtractSeriesName(metricName)

	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: baseKey=%s, seriesName=%s, hasDef=%v", baseKey, seriesName, def != nil))

	gridRows, gridCols := g.config.GetSystemGrid()
	metricsPerPage := gridRows * gridCols

	// Get or create chart
	chart, exists := g.chartsByMetric[baseKey]
	if !exists {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: creating new chart for baseKey=%s", baseKey))

		// Create new chart for this metric
		chart = g.createMetricChart(def, baseKey)
		g.chartsByMetric[baseKey] = chart

		// Add to ordered list and sort alphabetically
		g.orderedCharts = append(g.orderedCharts, chart)
		sort.Slice(g.orderedCharts, func(i, j int) bool {
			return g.orderedCharts[i].title < g.orderedCharts[j].title
		})

		// Recalculate pages
		g.totalPages = (len(g.orderedCharts) + metricsPerPage - 1) / metricsPerPage
		g.LoadCurrentPage()

		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: chart created, total charts=%d, pages=%d", len(g.orderedCharts), g.totalPages))
	}

	// Check if this is a new series
	if _, seriesExists := chart.series[seriesName]; !seriesExists && seriesName != "Default" {
		// Assign a new color to this series
		newColor := g.getNextColor()
		colorIndex := len(chart.series)
		chart.series[seriesName] = colorIndex
		chart.seriesColors = append(chart.seriesColors, newColor)

		// Register the new dataset with the chart
		seriesStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(newColor))
		chart.chart.SetDataSetStyle(seriesName, seriesStyle)

		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: new series '%s' added with color %s", seriesName, newColor))
	}

	// Track min/max for auto-range
	if value < chart.minValue {
		chart.minValue = value
	}
	if value > chart.maxValue {
		chart.maxValue = value
	}

	// Add the data point
	timePoint := timeserieslinechart.TimePoint{
		Time:  time.Unix(timestamp, 0),
		Value: value,
	}

	if seriesName == "Default" {
		// Use the default dataset
		chart.chart.Push(timePoint)
	} else {
		// Use named dataset for multi-series
		chart.chart.PushDataSet(seriesName, timePoint)
	}

	// Update chart properties
	chart.hasData = true
	chart.lastUpdate = time.Unix(timestamp, 0)

	// Update time range to show last 5 minutes
	// TODO: make the display interval configurable.
	minTime := time.Unix(timestamp, 0).Add(-5 * time.Minute)
	maxTime := time.Unix(timestamp, 0).Add(10 * time.Second)
	chart.chart.SetTimeRange(minTime, maxTime)
	chart.chart.SetViewTimeRange(minTime, maxTime)

	// Auto-adjust Y range for non-percentage metrics
	if chart.def.AutoRange && !chart.def.Percentage {
		// Calculate range with 10% padding
		range_ := chart.maxValue - chart.minValue
		if range_ == 0 {
			range_ = math.Abs(chart.maxValue) * 0.1
			if range_ == 0 {
				range_ = 1
			}
		}
		padding := range_ * 0.1

		newMinY := chart.minValue - padding
		newMaxY := chart.maxValue + padding

		// Don't go negative for non-negative data
		if chart.minValue >= 0 && newMinY < 0 {
			newMinY = 0
		}

		chart.chart.SetYRange(newMinY, newMaxY)
		chart.chart.SetViewYRange(newMinY, newMaxY)
	}

	// Skip drawing if chart dimensions are invalid
	if chart.chart.Width() <= 0 || chart.chart.Height() <= 0 {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: skipping draw, invalid chart dimensions %dx%d",
			chart.chart.Width(), chart.chart.Height()))
		return
	}

	// Check grid dimensions
	if g.width <= 0 || g.height <= 0 {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: skipping draw, grid not visible %dx%d",
			g.width, g.height))
		return
	}

	// Check graph dimensions
	graphWidth := chart.chart.GraphWidth()
	graphHeight := chart.chart.GraphHeight()
	if graphWidth <= 0 || graphHeight <= 0 {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.AddDataPoint: skipping draw, invalid graph dimensions %dx%d",
			graphWidth, graphHeight))
		return
	}

	// Now safe to redraw the chart
	if seriesName == "Default" || len(chart.series) == 0 {
		chart.chart.DrawBraille()
	} else {
		chart.chart.DrawBrailleAll() // Draw all series
	}
}

// ChartDimensions for metric charts
type MetricChartDimensions struct {
	ChartWidth             int
	ChartHeight            int
	ChartWidthWithPadding  int
	ChartHeightWithPadding int
}

// calculateChartDimensions computes dimensions for metric charts
func (g *SystemMetricsGrid) calculateChartDimensions() MetricChartDimensions {
	gridRows, gridCols := g.config.GetSystemGrid()

	availableHeight := g.height - 2
	if availableHeight < 0 {
		availableHeight = 0
	}

	chartHeightWithPadding := availableHeight / gridRows
	if chartHeightWithPadding < 0 {
		chartHeightWithPadding = 0
	}

	chartWidthWithPadding := g.width / gridCols
	if chartWidthWithPadding < 0 {
		chartWidthWithPadding = 0
	}

	borderChars := 2
	titleLines := 1

	chartWidth := chartWidthWithPadding - borderChars
	chartHeight := chartHeightWithPadding - borderChars - titleLines

	// Ensure we never return negative dimensions
	if chartWidth < 0 {
		chartWidth = 0
	}
	if chartHeight < 0 {
		chartHeight = 0
	}

	// Apply minimum sizes only if dimensions are positive
	if chartWidth > 0 && chartWidth < MinMetricChartWidth {
		chartWidth = MinMetricChartWidth
	}
	if chartHeight > 0 && chartHeight < MinMetricChartHeight {
		chartHeight = MinMetricChartHeight
	}

	return MetricChartDimensions{
		ChartWidth:             chartWidth,
		ChartHeight:            chartHeight,
		ChartWidthWithPadding:  chartWidthWithPadding,
		ChartHeightWithPadding: chartHeightWithPadding,
	}
}

// LoadCurrentPage loads charts for the current page
func (g *SystemMetricsGrid) LoadCurrentPage() {
	gridRows, gridCols := g.config.GetSystemGrid()
	metricsPerPage := gridRows * gridCols

	// Clear current grid
	for row := 0; row < gridRows; row++ {
		for col := 0; col < gridCols; col++ {
			g.charts[row][col] = nil
		}
	}

	startIdx := g.currentPage * metricsPerPage
	endIdx := startIdx + metricsPerPage
	if endIdx > len(g.orderedCharts) {
		endIdx = len(g.orderedCharts)
	}

	idx := startIdx
	for row := 0; row < gridRows && idx < endIdx; row++ {
		for col := 0; col < gridCols && idx < endIdx; col++ {
			if g.orderedCharts[idx].hasData {
				g.charts[row][col] = g.orderedCharts[idx]
			}
			idx++
		}
	}
}

// Navigate changes pages
func (g *SystemMetricsGrid) Navigate(direction int) {
	if g.totalPages <= 1 {
		return
	}

	// Clear focus when changing pages
	g.clearFocus()

	g.currentPage += direction
	if g.currentPage < 0 {
		g.currentPage = g.totalPages - 1
	} else if g.currentPage >= g.totalPages {
		g.currentPage = 0
	}

	g.LoadCurrentPage()
}

// HandleMouseClick handles mouse clicks for chart selection
// Returns true if a chart was focused, false if unfocused
func (g *SystemMetricsGrid) HandleMouseClick(row, col int) bool {
	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: row=%d, col=%d", row, col))
	g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: BEFORE - focusedRow=%d, focusedCol=%d, focusedChart=%v",
		g.focusedRow, g.focusedCol, g.focusedChart != nil))

	// Check if clicking on the already focused chart (to unfocus)
	if row == g.focusedRow && col == g.focusedCol {
		g.logger.Debug("SystemMetricsGrid.HandleMouseClick: clicking on already focused chart - UNFOCUSING")
		g.clearFocus()
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: AFTER UNFOCUS - focusedRow=%d, focusedCol=%d, focusedChart=%v",
			g.focusedRow, g.focusedCol, g.focusedChart != nil))
		return false // Chart was unfocused
	}

	// Clear previous focus
	g.logger.Debug("SystemMetricsGrid.HandleMouseClick: clearing previous focus")
	g.clearFocus()

	gridRows, gridCols := g.config.GetSystemGrid()

	// Set new focus
	if row >= 0 && row < gridRows && col >= 0 && col < gridCols &&
		row < len(g.charts) && col < len(g.charts[row]) && g.charts[row][col] != nil {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: FOCUSING chart at row=%d, col=%d", row, col))
		g.focusedRow = row
		g.focusedCol = col
		g.focusedChart = g.charts[row][col]
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.HandleMouseClick: AFTER FOCUS - focusedRow=%d, focusedCol=%d, focusedChart.title='%s'",
			g.focusedRow, g.focusedCol, g.focusedChart.fullTitle))
		return true // Focus was set
	}

	g.logger.Debug("SystemMetricsGrid.HandleMouseClick: no valid chart at position, returning false")
	return false // No valid chart to focus
}

// clearFocus removes focus from all charts
func (g *SystemMetricsGrid) clearFocus() {
	g.focusedRow = -1
	g.focusedCol = -1
	g.focusedChart = nil
}

// GetFocusedChartTitle returns the title of the focused chart
func (g *SystemMetricsGrid) GetFocusedChartTitle() string {
	if g.focusedChart != nil {
		return g.focusedChart.fullTitle
	}
	return ""
}

// Resize updates dimensions and resizes all charts
func (g *SystemMetricsGrid) Resize(width, height int) {
	// Validate dimensions before resizing
	if width <= 0 || height <= 0 {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.Resize: invalid dimensions %dx%d, skipping", width, height))
		return
	}

	g.width = width
	g.height = height

	dims := g.calculateChartDimensions()

	// Validate calculated dimensions before using them
	if dims.ChartWidth <= 0 || dims.ChartHeight <= 0 {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.Resize: calculated dimensions invalid %dx%d, skipping",
			dims.ChartWidth, dims.ChartHeight))
		return
	}

	// Additional safety check
	if dims.ChartWidth < MinMetricChartWidth || dims.ChartHeight < MinMetricChartHeight {
		g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.Resize: dimensions %dx%d below minimum, skipping resize",
			dims.ChartWidth, dims.ChartHeight))
		return
	}

	for _, metricChart := range g.chartsByMetric {
		if metricChart != nil && metricChart.chart != nil {
			// Only resize if the new dimensions are valid
			if dims.ChartWidth > 0 && dims.ChartHeight > 0 {
				metricChart.chart.Resize(dims.ChartWidth, dims.ChartHeight)

				// Check the chart's actual dimensions after resize
				actualWidth := metricChart.chart.Width()
				actualHeight := metricChart.chart.Height()

				// Only redraw if dimensions are truly valid after resize
				if actualWidth > 0 && actualHeight > 0 && actualWidth >= MinMetricChartWidth && actualHeight >= MinMetricChartHeight {
					if len(metricChart.series) > 0 {
						metricChart.chart.DrawBrailleAll()
					} else {
						metricChart.chart.DrawBraille()
					}
				} else {
					g.logger.Debug(fmt.Sprintf("SystemMetricsGrid.Resize: skipping draw for chart %s, actual dimensions %dx%d",
						metricChart.baseKey, actualWidth, actualHeight))
				}
			}
		}
	}

	g.LoadCurrentPage()
}

// Reset clears all metrics data
func (g *SystemMetricsGrid) Reset() {
	// Clear all data
	g.chartsByMetric = make(map[string]*SystemMetricChart)
	g.orderedCharts = make([]*SystemMetricChart, 0)
	g.currentPage = 0
	g.nextColorIdx = 0
	g.clearFocus()

	gridRows, gridCols := g.config.GetSystemGrid()

	// Clear the grid
	for row := 0; row < gridRows; row++ {
		for col := 0; col < gridCols; col++ {
			g.charts[row][col] = nil
		}
	}

	g.totalPages = 0
}

// View renders the metrics grid
func (g *SystemMetricsGrid) View() string {
	dims := g.calculateChartDimensions()
	gridRows, gridCols := g.config.GetSystemGrid()
	metricsPerPage := gridRows * gridCols

	var rows []string
	for row := 0; row < gridRows; row++ {
		var cols []string
		for col := 0; col < gridCols; col++ {
			cellIdx := g.currentPage*metricsPerPage + row*gridCols + col

			if row < len(g.charts) && col < len(g.charts[row]) && g.charts[row][col] != nil && cellIdx < len(g.orderedCharts) {
				metricChart := g.charts[row][col]
				chart := metricChart.chart

				// Render chart
				chartView := chart.View()

				// Build title with series count and truncation
				titleText := metricChart.fullTitle
				if len(metricChart.series) > 1 {
					// Use secondary color for [N]
					countStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
					count := fmt.Sprintf(" [%d]", len(metricChart.series))

					// Calculate available width for title (account for count)
					availableWidth := dims.ChartWidthWithPadding - 4 - lipgloss.Width(count)
					if availableWidth < 10 {
						availableWidth = 10
					}

					// Truncate title if needed
					displayTitle := TruncateTitle(titleText, availableWidth)
					titleText = titleStyle.Render(displayTitle) + countStyle.Render(count)
				} else {
					// Single series - just truncate if needed
					availableWidth := dims.ChartWidthWithPadding - 4
					if availableWidth < 10 {
						availableWidth = 10
					}
					titleText = titleStyle.Render(TruncateTitle(titleText, availableWidth))
				}

				boxContent := lipgloss.JoinVertical(
					lipgloss.Left,
					titleText,
					chartView,
				)

				// Highlight if focused
				boxStyle := borderStyle
				if row == g.focusedRow && col == g.focusedCol {
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
				// Empty cell
				cols = append(cols, lipgloss.NewStyle().
					Width(dims.ChartWidthWithPadding).
					Height(dims.ChartHeightWithPadding).
					Render(""))
			}
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}

	return lipgloss.JoinVertical(lipgloss.Left, rows...)
}

// RebuildGrid rebuilds the grid structure with new dimensions
func (g *SystemMetricsGrid) RebuildGrid() {
	gridRows, gridCols := g.config.GetSystemGrid()
	metricsPerPage := gridRows * gridCols

	// Rebuild grid structure
	g.charts = make([][]*SystemMetricChart, gridRows)
	for row := 0; row < gridRows; row++ {
		g.charts[row] = make([]*SystemMetricChart, gridCols)
	}

	// Recalculate pages
	g.totalPages = (len(g.orderedCharts) + metricsPerPage - 1) / metricsPerPage

	// Ensure current page is valid
	if g.currentPage >= g.totalPages && g.totalPages > 0 {
		g.currentPage = g.totalPages - 1
	}

	// Clear focus since grid structure changed
	g.clearFocus()

	// Reload current page
	g.LoadCurrentPage()

	// Resize all charts
	dims := g.calculateChartDimensions()
	for _, metricChart := range g.chartsByMetric {
		metricChart.chart.Resize(dims.ChartWidth, dims.ChartHeight)
		if len(metricChart.series) > 0 {
			metricChart.chart.DrawBrailleAll()
		} else {
			metricChart.chart.DrawBraille()
		}
	}
}

func (g *SystemMetricsGrid) GetCharts() [][]*SystemMetricChart {
	return g.charts
}

// GetChartCount returns the number of charts with data
func (g *SystemMetricsGrid) GetChartCount() int {
	count := 0
	for _, chart := range g.orderedCharts {
		if chart.hasData {
			count++
		}
	}
	return count
}

// NewRightSidebar creates a new right sidebar instance
func NewRightSidebar(config *ConfigManager, logger *observability.CoreLogger) *RightSidebar {
	state := SidebarCollapsed
	currentWidth, targetWidth := 0, 0
	if config.GetRightSidebarVisible() {
		state = SidebarExpanded
		currentWidth = SidebarMinWidth
		targetWidth = SidebarMinWidth
	}
	rs := &RightSidebar{
		config:        config,
		state:         state,
		currentWidth:  currentWidth,
		targetWidth:   targetWidth,
		expandedWidth: SidebarMinWidth,
		logger:        logger,
	}
	return rs
}

// UpdateDimensions updates the right sidebar dimensions based on terminal width and left sidebar state
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	// Clamp to min/max
	switch {
	case calculatedWidth < SidebarMinWidth:
		rs.expandedWidth = SidebarMinWidth
	case calculatedWidth > SidebarMaxWidth:
		rs.expandedWidth = SidebarMaxWidth
	default:
		rs.expandedWidth = calculatedWidth
	}

	// Update current width based on state
	switch rs.state {
	case SidebarExpanded:
		// If expanded, immediately update to new width
		rs.targetWidth = rs.expandedWidth
		rs.currentWidth = rs.expandedWidth
	case SidebarCollapsed:
		// Keep at 0 if collapsed
		rs.currentWidth = 0
		rs.targetWidth = 0
	case SidebarExpanding:
		// If expanding, update target but let animation handle current
		rs.targetWidth = rs.expandedWidth
		// Don't change currentWidth - let animation handle it
	case SidebarCollapsing:
		// If collapsing, keep target at 0
		rs.targetWidth = 0
		// Don't change currentWidth - let animation handle it
	}

	// Only resize metricsGrid if we have it, are expanded, and have valid dimensions
	// Skip resize during animations or when collapsed
	if rs.metricsGrid != nil && rs.state == SidebarExpanded && rs.currentWidth > 3 {
		gridWidth := rs.currentWidth - 3
		// Use a reasonable height - will be properly set in View
		gridHeight := 40

		// Ensure minimum viable dimensions
		gridRows, gridCols := rs.config.GetSystemGrid()
		minViableWidth := MinMetricChartWidth * gridCols
		minViableHeight := MinMetricChartHeight * gridRows

		if gridWidth >= minViableWidth && gridHeight >= minViableHeight {
			rs.metricsGrid.Resize(gridWidth, gridHeight)
		} else {
			rs.logger.Debug(fmt.Sprintf("RightSidebar.UpdateDimensions: skipping resize, dimensions %dx%d below minimum",
				gridWidth, gridHeight))
		}
	}
}

// Toggle toggles the sidebar state between expanded and collapsed
func (rs *RightSidebar) Toggle() {
	switch rs.state {
	case SidebarCollapsed:
		rs.state = SidebarExpanding
		rs.targetWidth = rs.expandedWidth
		rs.animationStep = 0
		rs.animationTimer = time.Now()

		// Ensure we have a metrics grid ready when opening
		if rs.metricsGrid == nil {
			gridRows, gridCols := rs.config.GetSystemGrid()
			initialWidth := MinMetricChartWidth * gridCols
			initialHeight := MinMetricChartHeight * gridRows
			rs.metricsGrid = NewSystemMetricsGrid(initialWidth, initialHeight, rs.config, rs.logger)
			rs.logger.Debug("RightSidebar.Toggle: created grid on expansion")
		}

	case SidebarExpanded:
		rs.state = SidebarCollapsing
		rs.targetWidth = 0
		rs.animationStep = 0
		rs.animationTimer = time.Now()
	case SidebarExpanding, SidebarCollapsing:
		// Already animating, ignore toggle
		rs.logger.Debug("RightSidebar.Toggle: ignoring toggle during animation")
	}
}

// HandleMouseClick handles mouse clicks in the sidebar
// x and y are already adjusted relative to the sidebar's position
// Returns true if a chart was focused, false if unfocused or no chart clicked
func (rs *RightSidebar) HandleMouseClick(x, y int) bool {
	rs.logger.Debug(fmt.Sprintf("RightSidebar.HandleMouseClick: x=%d, y=%d, state=%v", x, y, rs.state))

	if rs.state != SidebarExpanded || rs.metricsGrid == nil {
		rs.logger.Debug("RightSidebar.HandleMouseClick: sidebar not expanded or no grid, returning false")
		return false
	}

	// x is already adjusted relative to sidebar, but we need to account for padding
	// Account for sidebar padding (0 vertical, 1 horizontal on each side)
	adjustedX := x - 1
	if adjustedX < 0 {
		rs.logger.Debug(fmt.Sprintf("RightSidebar.HandleMouseClick: adjustedX=%d < 0, returning false", adjustedX))
		return false
	}

	// Calculate which chart was clicked
	// Account for header (1 line)
	adjustedY := y - 1
	if adjustedY < 0 {
		rs.logger.Debug(fmt.Sprintf("RightSidebar.HandleMouseClick: adjustedY=%d < 0, returning false", adjustedY))
		return false
	}

	dims := rs.metricsGrid.calculateChartDimensions()

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	rs.logger.Debug(fmt.Sprintf("RightSidebar.HandleMouseClick: calculated row=%d, col=%d from dims(w=%d,h=%d)",
		row, col, dims.ChartWidthWithPadding, dims.ChartHeightWithPadding))

	// This will return true if a chart was focused, false if unfocused
	result := rs.metricsGrid.HandleMouseClick(row, col)
	rs.logger.Debug(fmt.Sprintf("RightSidebar.HandleMouseClick: metricsGrid.HandleMouseClick returned %v", result))
	rs.logger.Debug(fmt.Sprintf("RightSidebar.HandleMouseClick: GetFocusedChartTitle='%s'", rs.GetFocusedChartTitle()))

	return result
}

// GetFocusedChartTitle returns the title of the focused chart
func (rs *RightSidebar) GetFocusedChartTitle() string {
	if rs.metricsGrid != nil {
		return rs.metricsGrid.GetFocusedChartTitle()
	}
	return ""
}

// ClearFocus clears focus from the currently focused system chart.
func (rs *RightSidebar) ClearFocus() {
	if rs.metricsGrid != nil {
		rs.metricsGrid.clearFocus()
	}
}

// Update handles animation updates and forwards system metrics data
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	var cmds []tea.Cmd

	// Handle system metrics data
	switch msg := msg.(type) {
	case StatsMsg:
		// Always process stats to store data, regardless of sidebar state
		// ProcessStatsMsg will handle creating the grid if needed
		// The actual drawing will be skipped in AddDataPoint if dimensions are invalid
		rs.ProcessStatsMsg(msg)

	case tea.KeyMsg:
		if rs.state == SidebarExpanded && rs.metricsGrid != nil {
			switch msg.String() {
			case "alt+N", "alt+pgup":
				rs.metricsGrid.Navigate(-1)
			case "alt+n", "alt+pgdown":
				rs.metricsGrid.Navigate(1)
			}
		}

		// Remove duplicate mouse handling - this is handled by the parent model in handlers.go
	}

	// Handle animation
	if rs.state == SidebarExpanding || rs.state == SidebarCollapsing {
		elapsed := time.Since(rs.animationTimer)
		progress := float64(elapsed) / float64(AnimationDuration)

		if progress >= 1.0 {
			rs.currentWidth = rs.targetWidth
			if rs.state == SidebarExpanding {
				rs.state = SidebarExpanded
				// Now that expansion is complete, ensure charts are properly sized
				if rs.metricsGrid != nil && rs.currentWidth > 3 {
					gridWidth := rs.currentWidth - 3
					gridHeight := 40 // This will be properly set in View
					rs.metricsGrid.Resize(gridWidth, gridHeight)
				}
			} else {
				rs.state = SidebarCollapsed
			}
		} else {
			if rs.state == SidebarExpanding {
				rs.currentWidth = int(easeOutCubic(progress) * float64(rs.expandedWidth))
			} else {
				rs.currentWidth = int((1 - easeOutCubic(progress)) * float64(rs.expandedWidth))
			}
			cmds = append(cmds, rs.animationCmd())
		}
	}

	return rs, tea.Batch(cmds...)
}

// View renders the right sidebar
func (rs *RightSidebar) View(height int) string {
	// Check if we have minimum width for rendering
	if rs.currentWidth <= 3 {
		return ""
	}

	gridRows, gridCols := rs.config.GetSystemGrid()
	metricsPerPage := gridRows * gridCols

	// During animation, don't try to resize - just show what we have or a placeholder
	if rs.IsAnimating() {
		// If we have a grid and it was previously drawn, show it without resizing
		if rs.metricsGrid != nil {
			// Just show the existing view without resizing during animation
			header := rightSidebarHeaderStyle.Render("System Metrics")

			// Add navigation info
			navInfo := ""
			chartCount := rs.metricsGrid.GetChartCount()
			if rs.metricsGrid.totalPages > 0 && chartCount > 0 {
				startIdx := rs.metricsGrid.currentPage*metricsPerPage + 1
				endIdx := startIdx + metricsPerPage - 1
				if endIdx > chartCount {
					endIdx = chartCount
				}
				navInfo = lipgloss.NewStyle().
					Foreground(lipgloss.Color("240")).
					Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
			}

			headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)
			metricsView := rs.metricsGrid.View()

			content := lipgloss.JoinVertical(
				lipgloss.Left,
				headerLine,
				metricsView,
			)

			// Apply styles with current dimensions
			styledContent := rightSidebarStyle.
				Width(rs.currentWidth - 1).
				Height(height).
				MaxWidth(rs.currentWidth - 1).
				MaxHeight(height).
				Render(content)

			bordered := rightSidebarBorderStyle.
				Width(rs.currentWidth).
				Height(height).
				MaxHeight(height).
				Render(styledContent)

			return bordered
		}

		// No grid yet, show placeholder during animation
		header := rightSidebarHeaderStyle.Render("System Metrics")
		message := lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			Render("\n  [Loading...]")

		content := header + message

		styledContent := rightSidebarStyle.
			Width(rs.currentWidth - 1).
			Height(height).
			MaxWidth(rs.currentWidth - 1).
			MaxHeight(height).
			Render(content)

		bordered := rightSidebarBorderStyle.
			Width(rs.currentWidth).
			Height(height).
			MaxHeight(height).
			Render(styledContent)

		return bordered
	}

	// Not animating - safe to create/resize grid

	// Calculate available dimensions for the grid
	gridWidth := rs.currentWidth - 3
	gridHeight := height - 1

	// Safety check
	if gridWidth <= 0 || gridHeight <= 0 {
		rs.logger.Debug(fmt.Sprintf("RightSidebar.View: invalid grid dimensions %dx%d from currentWidth=%d",
			gridWidth, gridHeight, rs.currentWidth))
		return ""
	}

	// Ensure minimum viable dimensions
	minViableWidth := MinMetricChartWidth * gridCols
	minViableHeight := MinMetricChartHeight * gridRows

	// Check if we have enough space
	if gridWidth < minViableWidth || gridHeight < minViableHeight {
		// Not enough space to display charts properly
		header := rightSidebarHeaderStyle.Render("System Metrics")
		message := lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			Render(fmt.Sprintf("\n  [Need %dx%d, have %dx%d]",
				minViableWidth, minViableHeight, gridWidth, gridHeight))

		content := header + message

		styledContent := rightSidebarStyle.
			Width(rs.currentWidth - 1).
			Height(height).
			MaxWidth(rs.currentWidth - 1).
			MaxHeight(height).
			Render(content)

		bordered := rightSidebarBorderStyle.
			Width(rs.currentWidth).
			Height(height).
			MaxHeight(height).
			Render(styledContent)

		return bordered
	}

	// We have sufficient space - create or resize grid
	if rs.metricsGrid == nil {
		// Create new grid
		rs.metricsGrid = NewSystemMetricsGrid(gridWidth, gridHeight, rs.config, rs.logger)
	} else {
		// Resize existing grid
		rs.metricsGrid.Resize(gridWidth, gridHeight)
	}

	// Build header with navigation info
	header := rightSidebarHeaderStyle.Render("System Metrics")

	// Add navigation info
	navInfo := ""
	chartCount := rs.metricsGrid.GetChartCount()
	if rs.metricsGrid.totalPages > 0 && chartCount > 0 {
		startIdx := rs.metricsGrid.currentPage*metricsPerPage + 1
		endIdx := startIdx + metricsPerPage - 1
		if endIdx > chartCount {
			endIdx = chartCount
		}
		navInfo = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
	}

	headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)
	metricsView := rs.metricsGrid.View()

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		headerLine,
		metricsView,
	)

	// Apply styles with exact dimensions
	styledContent := rightSidebarStyle.
		Width(rs.currentWidth - 1).
		Height(height).
		MaxWidth(rs.currentWidth - 1).
		MaxHeight(height).
		Render(content)

	// Apply border
	bordered := rightSidebarBorderStyle.
		Width(rs.currentWidth).
		Height(height).
		MaxHeight(height).
		Render(styledContent)

	return bordered
}

// Width returns the current width of the sidebar
func (rs *RightSidebar) Width() int {
	return rs.currentWidth
}

// IsVisible returns true if the sidebar is visible
func (rs *RightSidebar) IsVisible() bool {
	return rs.state != SidebarCollapsed
}

// IsAnimating returns true if the sidebar is currently animating
func (rs *RightSidebar) IsAnimating() bool {
	return rs.state == SidebarExpanding || rs.state == SidebarCollapsing
}

// animationCmd returns a command to continue the animation
func (rs *RightSidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return RightSidebarAnimationMsg{}
	})
}

// RightSidebarAnimationMsg is sent during right sidebar animations
type RightSidebarAnimationMsg struct{}

// ProcessStatsMsg processes a stats message and updates the metrics
func (rs *RightSidebar) ProcessStatsMsg(msg StatsMsg) {
	rs.logger.Debug(fmt.Sprintf("RightSidebar.ProcessStatsMsg: processing %d metrics (state=%v, width=%d)",
		len(msg.Metrics), rs.state, rs.currentWidth))

	// We should always store data, but only create/draw charts when visible
	// This ensures data is available when the sidebar opens

	// Create metricsGrid if it doesn't exist yet
	if rs.metricsGrid == nil {
		// Use a reasonable initial size for storing data
		// The actual display size will be set when the sidebar opens
		gridRows, gridCols := rs.config.GetSystemGrid()
		initialWidth := MinMetricChartWidth * gridCols
		initialHeight := MinMetricChartHeight * gridRows
		rs.metricsGrid = NewSystemMetricsGrid(initialWidth, initialHeight, rs.config, rs.logger)
		rs.logger.Debug(fmt.Sprintf("RightSidebar.ProcessStatsMsg: created grid with initial dimensions %dx%d",
			initialWidth, initialHeight))
	}

	// Always add data points, but drawing will be skipped if sidebar is collapsed
	for metricName, value := range msg.Metrics {
		rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
	}
}

// Reset clears all system metrics data
func (rs *RightSidebar) Reset() {
	if rs.metricsGrid != nil {
		rs.metricsGrid.Reset()
	}
}
