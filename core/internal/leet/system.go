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

const systemMetricsHeader = "System Metrics"

// RightSidebar represents a collapsible right sidebar panel.
type RightSidebar struct {
	config         *ConfigManager
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int
	animationStep  int
	animationTimer time.Time

	metricsGrid *SystemMetricsGrid
	focusState  *FocusState
	logger      *observability.CoreLogger
}

// SystemMetricChart represents a single metric chart with multiple series.
type SystemMetricChart struct {
	chart        *timeserieslinechart.Model
	def          *MetricDef
	baseKey      string
	title        string
	fullTitle    string
	series       map[string]int
	seriesColors []string
	hasData      bool
	lastUpdate   time.Time
	minValue     float64
	maxValue     float64
}

// SystemMetricsGrid manages the grid of system metric charts.
type SystemMetricsGrid struct {
	config *ConfigManager

	chartsByMetric map[string]*SystemMetricChart
	orderedCharts  []*SystemMetricChart

	charts    [][]*SystemMetricChart
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
	size := effectiveSystemGridSize(width, height, config)

	grid := &SystemMetricsGrid{
		config:         config,
		chartsByMetric: make(map[string]*SystemMetricChart),
		orderedCharts:  make([]*SystemMetricChart, 0),
		charts:         make([][]*SystemMetricChart, size.Rows),
		focusState:     focusState,
		width:          width,
		height:         height,
		logger:         logger,
	}

	for row := 0; row < size.Rows; row++ {
		grid.charts[row] = make([]*SystemMetricChart, size.Cols)
	}

	logger.Debug(fmt.Sprintf("SystemMetricsGrid: created with dimensions %dx%d",
		width, height))

	return grid
}

// effectiveSystemGridSize returns the grid size that can fit in the current viewport.
func effectiveSystemGridSize(availW, availH int, config *ConfigManager) GridSize {
	cfgRows, cfgCols := config.SystemGrid()
	spec := GridSpec{
		Rows:        cfgRows,
		Cols:        cfgCols,
		MinCellW:    MinMetricChartWidth,
		MinCellH:    MinMetricChartHeight,
		HeaderLines: 0, // RightSidebar passes header-less height
	}
	return EffectiveGridSize(availW, availH, spec)
}

// effectiveGridSize returns the grid size that can fit in the current viewport.
func (g *SystemMetricsGrid) effectiveGridSize() GridSize {
	return effectiveSystemGridSize(g.width, g.height, g.config)
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
		HeaderLines: 0, // right sidebar accounts for its 1-line header outside
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
	// TODO: make this configurable.
	colors := colorSchemes["wandb-vibe-10"]
	color := colors[g.nextColorIdx%len(colors)]
	g.nextColorIdx++
	return color
}

// createMetricChart creates a time series chart for a system metric.
func (g *SystemMetricsGrid) createMetricChart(
	def *MetricDef,
	baseKey string,
) *SystemMetricChart {
	dims := g.calculateChartDimensions()

	chartWidth := max(dims.ChartWidth, MinMetricChartWidth)
	chartHeight := max(dims.ChartHeight, MinMetricChartHeight)

	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.createMetricChart: creating chart %dx%d for %s",
		chartWidth, chartHeight, baseKey))

	minY, maxY := def.MinY, def.MaxY
	now := time.Now()
	// TODO: make the display interval configurable.
	minTime := now.Add(-10 * time.Minute)

	firstColor := g.getNextColor()
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

	return &SystemMetricChart{
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
}

// AddDataPoint adds a new data point to the appropriate metric chart.
//
//gocyclo:ignore
func (g *SystemMetricsGrid) AddDataPoint(
	metricName string,
	timestamp int64,
	value float64,
) {
	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.AddDataPoint: metric=%s, timestamp=%d, value=%f",
		metricName, timestamp, value))

	def := MatchMetricDef(metricName)
	if def == nil {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.AddDataPoint: no definition for metric=%s",
			metricName))
		return
	}

	baseKey := ExtractBaseKey(metricName)
	seriesName := ExtractSeriesName(metricName)

	size := g.effectiveGridSize()

	chart, exists := g.chartsByMetric[baseKey]
	if !exists {
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.AddDataPoint: creating new chart for baseKey=%s",
			baseKey))

		chart = g.createMetricChart(def, baseKey)
		g.chartsByMetric[baseKey] = chart

		g.orderedCharts = append(g.orderedCharts, chart)
		sort.Slice(g.orderedCharts, func(i, j int) bool {
			return g.orderedCharts[i].title < g.orderedCharts[j].title
		})

		g.navigator.UpdateTotalPages(len(g.orderedCharts), ItemsPerPage(size))
		g.LoadCurrentPage()

		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.AddDataPoint: chart created, total=%d, pages=%d",
			len(g.orderedCharts), g.navigator.TotalPages()))
	}

	if _, seriesExists := chart.series[seriesName]; !seriesExists && seriesName != "Default" {
		newColor := g.getNextColor()
		colorIndex := len(chart.series)
		chart.series[seriesName] = colorIndex
		chart.seriesColors = append(chart.seriesColors, newColor)

		seriesStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(newColor))
		chart.chart.SetDataSetStyle(seriesName, seriesStyle)

		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.AddDataPoint: new series '%s' with color %s",
			seriesName, newColor))
	}

	if value < chart.minValue {
		chart.minValue = value
	}
	if value > chart.maxValue {
		chart.maxValue = value
	}

	timePoint := timeserieslinechart.TimePoint{
		Time:  time.Unix(timestamp, 0),
		Value: value,
	}

	if seriesName == "Default" {
		chart.chart.Push(timePoint)
	} else {
		chart.chart.PushDataSet(seriesName, timePoint)
	}

	chart.hasData = true
	chart.lastUpdate = time.Unix(timestamp, 0)

	minTime := time.Unix(timestamp, 0).Add(-10 * time.Minute)
	maxTime := time.Unix(timestamp, 0).Add(10 * time.Second)
	chart.chart.SetTimeRange(minTime, maxTime)
	chart.chart.SetViewTimeRange(minTime, maxTime)

	if chart.def.AutoRange && !chart.def.Percentage {
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

		if chart.minValue >= 0 && newMinY < 0 {
			newMinY = 0
		}

		chart.chart.SetYRange(newMinY, newMaxY)
		chart.chart.SetViewYRange(newMinY, newMaxY)
	}

	if chart.chart.Width() <= 0 || chart.chart.Height() <= 0 ||
		g.width <= 0 || g.height <= 0 ||
		chart.chart.GraphWidth() <= 0 || chart.chart.GraphHeight() <= 0 {
		return
	}

	if seriesName == "Default" || len(chart.series) == 0 {
		chart.chart.DrawBraille()
	} else {
		chart.chart.DrawBrailleAll()
	}
}

// LoadCurrentPage loads charts for the current page.
func (g *SystemMetricsGrid) LoadCurrentPage() {
	size := g.effectiveGridSize()

	if len(g.charts) != size.Rows ||
		(len(g.charts) > 0 && len(g.charts[0]) != size.Cols) {
		g.charts = make([][]*SystemMetricChart, size.Rows)
		for row := range size.Rows {
			g.charts[row] = make([]*SystemMetricChart, size.Cols)
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

	g.clearFocus()
	g.LoadCurrentPage()
}

// HandleMouseClick handles mouse clicks for chart selection.
func (g *SystemMetricsGrid) HandleMouseClick(row, col int) bool {
	g.logger.Debug(fmt.Sprintf(
		"SystemMetricsGrid.HandleMouseClick: row=%d, col=%d", row, col))

	if g.focusState.Type == FocusSystemChart &&
		row == g.focusState.Row && col == g.focusState.Col {
		g.logger.Debug(
			"SystemMetricsGrid.HandleMouseClick: clicking on focused chart - unfocusing")
		g.clearFocus()
		return false
	}

	g.clearFocus()

	size := g.effectiveGridSize()

	if row >= 0 && row < size.Rows && col >= 0 && col < size.Cols &&
		row < len(g.charts) && col < len(g.charts[row]) &&
		g.charts[row][col] != nil {
		chart := g.charts[row][col]
		g.logger.Debug(fmt.Sprintf(
			"SystemMetricsGrid.HandleMouseClick: focusing chart at row=%d, col=%d",
			row, col))

		g.focusState.Type = FocusSystemChart
		g.focusState.Row = row
		g.focusState.Col = col
		g.focusState.Title = chart.fullTitle

		return true
	}

	return false
}

// clearFocus removes focus from all charts.
func (g *SystemMetricsGrid) clearFocus() {
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
			"SystemMetricsGrid.Resize: invalid dimensions %dx%d, skipping",
			width, height))
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

				boxContent := lipgloss.JoinVertical(
					lipgloss.Left,
					titleText,
					chartView,
				)

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

	// Bottom filler for visual tightness
	used := size.Rows * dims.ChartHeightWithPadding
	if extra := g.height - used; extra > 0 {
		filler := lipgloss.NewStyle().Height(extra).Render("")
		grid = lipgloss.JoinVertical(lipgloss.Left, grid, filler)
	}

	return grid
}

// RebuildGrid rebuilds the grid structure.
func (g *SystemMetricsGrid) RebuildGrid() {
	size := g.effectiveGridSize()

	g.charts = make([][]*SystemMetricChart, size.Rows)
	for row := range size.Rows {
		g.charts[row] = make([]*SystemMetricChart, size.Cols)
	}

	g.navigator.UpdateTotalPages(len(g.orderedCharts), ItemsPerPage(size))

	g.clearFocus()
	g.LoadCurrentPage()

	dims := g.calculateChartDimensions()
	if dims.ChartWidth > 0 && dims.ChartHeight > 0 {
		for _, metricChart := range g.chartsByMetric {
			if metricChart != nil && metricChart.chart != nil {
				metricChart.chart.Resize(dims.ChartWidth, dims.ChartHeight)
				if len(metricChart.series) > 0 {
					metricChart.chart.DrawBrailleAll()
				} else {
					metricChart.chart.DrawBraille()
				}
			}
		}
	}
}

// GetCharts returns the current grid of charts.
func (g *SystemMetricsGrid) GetCharts() [][]*SystemMetricChart {
	return g.charts
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

func NewRightSidebar(
	config *ConfigManager,
	focusState *FocusState,
	logger *observability.CoreLogger,
) *RightSidebar {
	state := SidebarCollapsed
	currentWidth, targetWidth := 0, 0
	if config.RightSidebarVisible() {
		state = SidebarExpanded
		currentWidth = SidebarMinWidth
		targetWidth = SidebarMinWidth
	}
	return &RightSidebar{
		config:        config,
		state:         state,
		currentWidth:  currentWidth,
		targetWidth:   targetWidth,
		expandedWidth: SidebarMinWidth,
		logger:        logger,
		focusState:    focusState,
	}
}

// UpdateDimensions updates the right sidebar dimensions.
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	switch {
	case calculatedWidth < SidebarMinWidth:
		rs.expandedWidth = SidebarMinWidth
	case calculatedWidth > SidebarMaxWidth:
		rs.expandedWidth = SidebarMaxWidth
	default:
		rs.expandedWidth = calculatedWidth
	}

	switch rs.state {
	case SidebarExpanded:
		rs.targetWidth = rs.expandedWidth
		rs.currentWidth = rs.expandedWidth
	case SidebarCollapsed:
		rs.currentWidth = 0
		rs.targetWidth = 0
	case SidebarExpanding:
		rs.targetWidth = rs.expandedWidth
	case SidebarCollapsing:
		rs.targetWidth = 0
	}

	if rs.metricsGrid != nil && rs.state == SidebarExpanded &&
		rs.currentWidth > 3 {
		gridWidth := rs.currentWidth - 3
		gridHeight := 40
		rs.metricsGrid.Resize(gridWidth, gridHeight)
	}
}

// Toggle flips the sidebar state.
func (rs *RightSidebar) Toggle() {
	switch rs.state {
	case SidebarCollapsed:
		rs.state = SidebarExpanding
		rs.targetWidth = rs.expandedWidth
		rs.animationStep = 0
		rs.animationTimer = time.Now()

		if rs.metricsGrid == nil {
			gridRows, gridCols := rs.config.SystemGrid()
			initialWidth := MinMetricChartWidth * gridCols
			initialHeight := MinMetricChartHeight * gridRows
			rs.metricsGrid = NewSystemMetricsGrid(
				initialWidth, initialHeight, rs.config, rs.focusState, rs.logger)
			rs.logger.Debug("RightSidebar.Toggle: created grid on expansion")
		}

	case SidebarExpanded:
		rs.state = SidebarCollapsing
		rs.targetWidth = 0
		rs.animationStep = 0
		rs.animationTimer = time.Now()
	case SidebarExpanding, SidebarCollapsing:
		rs.logger.Debug("RightSidebar.Toggle: ignoring toggle during animation")
	}
}

// HandleMouseClick handles mouse clicks in the sidebar.
func (rs *RightSidebar) HandleMouseClick(x, y int) bool {
	rs.logger.Debug(fmt.Sprintf(
		"RightSidebar.HandleMouseClick: x=%d, y=%d, state=%v", x, y, rs.state))

	if rs.state != SidebarExpanded || rs.metricsGrid == nil {
		return false
	}

	adjustedX := x - 1
	if adjustedX < 0 {
		return false
	}

	adjustedY := y - 1
	if adjustedY < 0 {
		return false
	}

	dims := rs.metricsGrid.calculateChartDimensions()

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	return rs.metricsGrid.HandleMouseClick(row, col)
}

// GetFocusedChartTitle returns the title of the focused chart.
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

// Update handles animation updates.
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	var cmds []tea.Cmd

	if msg, ok := msg.(StatsMsg); ok {
		rs.ProcessStatsMsg(msg)
	}

	if rs.state == SidebarExpanding || rs.state == SidebarCollapsing {
		elapsed := time.Since(rs.animationTimer)
		progress := float64(elapsed) / float64(AnimationDuration)

		if progress >= 1.0 {
			rs.currentWidth = rs.targetWidth
			if rs.state == SidebarExpanding {
				rs.state = SidebarExpanded
				if rs.metricsGrid != nil && rs.currentWidth > 3 {
					gridWidth := rs.currentWidth - 3
					gridHeight := 40
					rs.metricsGrid.Resize(gridWidth, gridHeight)
				}
			} else {
				rs.state = SidebarCollapsed
			}
		} else {
			if rs.state == SidebarExpanding {
				rs.currentWidth = int(
					easeOutCubic(progress) * float64(rs.expandedWidth))
			} else {
				rs.currentWidth = int(
					(1 - easeOutCubic(progress)) * float64(rs.expandedWidth))
			}
			cmds = append(cmds, rs.animationCmd())
		}
	}

	return rs, tea.Batch(cmds...)
}

// View renders the right sidebar.
func (rs *RightSidebar) View(height int) string {
	if rs.currentWidth <= 3 {
		return ""
	}

	header := rightSidebarHeaderStyle.Render(systemMetricsHeader)

	gridWidth := rs.currentWidth - 3
	gridHeight := height - 1

	if gridWidth <= 0 || gridHeight <= 0 {
		return ""
	}

	if rs.metricsGrid == nil {
		rs.metricsGrid = NewSystemMetricsGrid(
			gridWidth, gridHeight, rs.config, rs.focusState, rs.logger)
	} else {
		rs.metricsGrid.Resize(gridWidth, gridHeight)
	}

	navInfo := ""
	chartCount := rs.metricsGrid.GetChartCount()
	size := rs.metricsGrid.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)

	if rs.metricsGrid.navigator.TotalPages() > 0 &&
		chartCount > 0 && itemsPerPage > 0 {
		startIdx, endIdx := rs.metricsGrid.navigator.GetPageBounds(
			chartCount, itemsPerPage)
		startIdx++
		navInfo = navInfoStyle.
			Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
	}

	headerLine := lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)
	metricsView := rs.metricsGrid.View()

	content := lipgloss.JoinVertical(lipgloss.Left, headerLine, metricsView)

	styledContent := rightSidebarStyle.
		Width(rs.currentWidth - 1).
		Height(height).
		MaxWidth(rs.currentWidth - 1).
		MaxHeight(height).
		Render(content)

	return rightSidebarBorderStyle.
		Width(rs.currentWidth).
		Height(height).
		MaxHeight(height).
		Render(styledContent)
}

// Width returns the current width of the sidebar.
func (rs *RightSidebar) Width() int {
	return rs.currentWidth
}

// IsVisible returns true if the sidebar is visible.
func (rs *RightSidebar) IsVisible() bool {
	return rs.state != SidebarCollapsed
}

// IsAnimating returns true if the sidebar is currently animating.
func (rs *RightSidebar) IsAnimating() bool {
	return rs.state == SidebarExpanding || rs.state == SidebarCollapsing
}

// animationCmd returns a command to continue the animation.
func (rs *RightSidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return RightSidebarAnimationMsg{}
	})
}

// RightSidebarAnimationMsg is sent during right sidebar animations.
type RightSidebarAnimationMsg struct{}

// ProcessStatsMsg processes a stats message and updates the metrics.
func (rs *RightSidebar) ProcessStatsMsg(msg StatsMsg) {
	rs.logger.Debug(fmt.Sprintf(
		"RightSidebar.ProcessStatsMsg: processing %d metrics (state=%v, width=%d)",
		len(msg.Metrics), rs.state, rs.currentWidth))

	if rs.metricsGrid == nil {
		gridRows, gridCols := rs.config.SystemGrid()
		initialWidth := MinMetricChartWidth * gridCols
		initialHeight := MinMetricChartHeight * gridRows
		rs.metricsGrid = NewSystemMetricsGrid(
			initialWidth, initialHeight, rs.config, rs.focusState, rs.logger)
		rs.logger.Debug(fmt.Sprintf(
			"RightSidebar.ProcessStatsMsg: created grid with initial dimensions %dx%d",
			initialWidth, initialHeight))
	}

	for metricName, value := range msg.Metrics {
		rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
	}
}
