//go:build !wandb_core

package leet

import (
	"fmt"
	"time"

	"github.com/NimbleMarkets/ntcharts/linechart/timeserieslinechart"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// RightSidebar represents a collapsible right sidebar panel.
type RightSidebar struct {
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int
	animationStep  int
	animationTimer time.Time

	// System metrics grid
	metricsGrid *SystemMetricsGrid
}

// Metric definitions - which metrics to display and their configuration
var systemMetrics = []MetricConfig{
	{Name: "cpu.ecpu_percent", Title: "E-CPU (%)", MinY: 0, MaxY: 100, Unit: "%"},
	{Name: "cpu.pcpu_percent", Title: "P-CPU (%)", MinY: 0, MaxY: 100, Unit: "%"},
	{Name: "memory.used_percent", Title: "Memory (%)", MinY: 0, MaxY: 100, Unit: "%"},
	{Name: "cpu.avg_temp", Title: "CPU Temp (°C)", MinY: 0, MaxY: 100, Unit: "°C"},
	{Name: "gpu.0.gpu", Title: "GPU (%)", MinY: 0, MaxY: 100, Unit: "%"},
	{Name: "gpu.0.temp", Title: "GPU Temp (°C)", MinY: 0, MaxY: 100, Unit: "°C"},
	{Name: "system.powerWatts", Title: "Power (W)", MinY: 0, MaxY: 50, Unit: "W"},
}

// MetricConfig defines configuration for a system metric
type MetricConfig struct {
	Name  string
	Title string
	MinY  float64
	MaxY  float64
	Unit  string
}

// SystemMetricsGrid manages the grid of system metric charts
type SystemMetricsGrid struct {
	charts       [][]*timeserieslinechart.Model
	allCharts    []*timeserieslinechart.Model
	chartConfigs []MetricConfig
	currentPage  int
	totalPages   int
	focusedRow   int
	focusedCol   int
	width        int
	height       int
}

// NewSystemMetricsGrid creates a new system metrics grid
func NewSystemMetricsGrid(width, height int) *SystemMetricsGrid {
	grid := &SystemMetricsGrid{
		charts:       make([][]*timeserieslinechart.Model, MetricsGridRows),
		allCharts:    make([]*timeserieslinechart.Model, 0),
		chartConfigs: make([]MetricConfig, 0),
		currentPage:  0,
		focusedRow:   -1,
		focusedCol:   -1,
		width:        width,
		height:       height,
	}

	// Initialize grid rows
	for row := 0; row < MetricsGridRows; row++ {
		grid.charts[row] = make([]*timeserieslinechart.Model, MetricsGridCols)
	}

	// Create charts for each metric
	for i, metric := range systemMetrics {
		dims := grid.calculateChartDimensions()
		chart := grid.createMetricChart(metric, dims.ChartWidth, dims.ChartHeight, i)
		grid.allCharts = append(grid.allCharts, &chart)
		grid.chartConfigs = append(grid.chartConfigs, metric)
	}

	grid.totalPages = (len(grid.allCharts) + MetricsPerPage - 1) / MetricsPerPage
	grid.loadCurrentPage()

	return grid
}

// createMetricChart creates a time series chart for a system metric
func (g *SystemMetricsGrid) createMetricChart(config MetricConfig, width, height, colorIndex int) timeserieslinechart.Model {
	// Use different colors for different metrics
	// colors := []string{"4", "10", "5", "6", "3", "2"}
	colors := []string{
		"#E281FE",
		"#E78DE3",
		"#E993D5",
		"#ED9FBB",
		"#F0A5AD",
		"#F2AB9F",
		"#F6B784",
		"#F8BD78",
		"#FBC36B",
		"#FFCF4F",
	}
	color := colors[colorIndex%len(colors)]

	graphStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(color))

	now := time.Now()
	minTime := now.Add(-5 * time.Minute) // Show last 5 minutes

	chart := timeserieslinechart.New(width, height,
		timeserieslinechart.WithTimeRange(minTime, now),
		timeserieslinechart.WithYRange(config.MinY, config.MaxY),
		timeserieslinechart.WithAxesStyles(axisStyle, labelStyle),
		timeserieslinechart.WithStyle(graphStyle),
		timeserieslinechart.WithUpdateHandler(timeserieslinechart.SecondUpdateHandler(1)),
		timeserieslinechart.WithXLabelFormatter(timeserieslinechart.HourTimeLabelFormatter()),
		timeserieslinechart.WithYLabelFormatter(func(i int, v float64) string {
			return fmt.Sprintf("%.0f%s", v, config.Unit)
		}),
		timeserieslinechart.WithXYSteps(2, 3), // Fewer steps for smaller charts
	)

	return chart
}

// AddDataPoint adds a new data point to the appropriate metric chart
func (g *SystemMetricsGrid) AddDataPoint(metricName string, timestamp int64, value float64) {
	for i, config := range g.chartConfigs {
		if config.Name == metricName && i < len(g.allCharts) {
			timePoint := timeserieslinechart.TimePoint{
				Time:  time.Unix(timestamp, 0),
				Value: value,
			}
			g.allCharts[i].Push(timePoint)

			// Update the time range to show from start to latest data point
			chart := g.allCharts[i]
			minTime := time.Unix(timestamp, 0).Add(-5 * time.Minute)
			maxTime := time.Unix(timestamp, 0).Add(10 * time.Second) // Small buffer for visibility
			chart.SetTimeRange(minTime, maxTime)
			chart.SetViewTimeRange(minTime, maxTime)

			chart.DrawBraille() // Use braille for higher resolution
			break
		}
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
	availableHeight := g.height - 2 // Just header and minimal padding
	chartHeightWithPadding := availableHeight / MetricsGridRows
	chartWidthWithPadding := g.width / MetricsGridCols

	borderChars := 2
	titleLines := 1

	chartWidth := chartWidthWithPadding - borderChars
	chartHeight := chartHeightWithPadding - borderChars - titleLines

	// Ensure minimum size
	if chartHeight < MinMetricChartHeight {
		chartHeight = MinMetricChartHeight
	}
	if chartWidth < MinMetricChartWidth {
		chartWidth = MinMetricChartWidth
	}

	return MetricChartDimensions{
		ChartWidth:             chartWidth,
		ChartHeight:            chartHeight,
		ChartWidthWithPadding:  chartWidthWithPadding,
		ChartHeightWithPadding: chartHeightWithPadding,
	}
}

// loadCurrentPage loads charts for the current page
func (g *SystemMetricsGrid) loadCurrentPage() {
	// Clear current grid
	for row := 0; row < MetricsGridRows; row++ {
		for col := 0; col < MetricsGridCols; col++ {
			g.charts[row][col] = nil
		}
	}

	startIdx := g.currentPage * MetricsPerPage
	endIdx := startIdx + MetricsPerPage
	if endIdx > len(g.allCharts) {
		endIdx = len(g.allCharts)
	}

	idx := startIdx
	for row := 0; row < MetricsGridRows && idx < endIdx; row++ {
		for col := 0; col < MetricsGridCols && idx < endIdx; col++ {
			g.charts[row][col] = g.allCharts[idx]
			idx++
		}
	}
}

// Navigate changes pages
func (g *SystemMetricsGrid) Navigate(direction int) {
	if g.totalPages <= 1 {
		return
	}

	g.currentPage += direction
	if g.currentPage < 0 {
		g.currentPage = g.totalPages - 1
	} else if g.currentPage >= g.totalPages {
		g.currentPage = 0
	}

	g.loadCurrentPage()
}

// Resize updates dimensions and resizes all charts
func (g *SystemMetricsGrid) Resize(width, height int) {
	g.width = width
	g.height = height

	dims := g.calculateChartDimensions()
	for _, chart := range g.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.DrawBraille()
	}

	g.loadCurrentPage()
}

// Reset clears all metrics data and recreates charts
func (g *SystemMetricsGrid) Reset() {
	// Clear all existing charts
	g.allCharts = make([]*timeserieslinechart.Model, 0)
	g.chartConfigs = make([]MetricConfig, 0)
	g.currentPage = 0

	// Clear the grid
	for row := 0; row < MetricsGridRows; row++ {
		for col := 0; col < MetricsGridCols; col++ {
			g.charts[row][col] = nil
		}
	}

	// Recreate charts for each metric
	for i, metric := range systemMetrics {
		dims := g.calculateChartDimensions()
		chart := g.createMetricChart(metric, dims.ChartWidth, dims.ChartHeight, i)
		g.allCharts = append(g.allCharts, &chart)
		g.chartConfigs = append(g.chartConfigs, metric)
	}

	g.totalPages = (len(g.allCharts) + MetricsPerPage - 1) / MetricsPerPage
	g.loadCurrentPage()
}

// View renders the metrics grid
func (g *SystemMetricsGrid) View() string {
	dims := g.calculateChartDimensions()

	var rows []string
	for row := 0; row < MetricsGridRows; row++ {
		var cols []string
		for col := 0; col < MetricsGridCols; col++ {
			if row < len(g.charts) && col < len(g.charts[row]) && g.charts[row][col] != nil {
				chart := g.charts[row][col]
				config := g.chartConfigs[g.currentPage*MetricsPerPage+row*MetricsGridCols+col]

				// Render chart with title
				chartView := chart.View()
				boxContent := lipgloss.JoinVertical(
					lipgloss.Left,
					titleStyle.Render(config.Title),
					chartView,
				)

				box := borderStyle.Render(boxContent)
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
	// Update grid dimensions from config
	UpdateGridDimensions()

	// Rebuild grid structure
	g.charts = make([][]*timeserieslinechart.Model, MetricsGridRows)
	for row := 0; row < MetricsGridRows; row++ {
		g.charts[row] = make([]*timeserieslinechart.Model, MetricsGridCols)
	}

	// Recalculate pages
	MetricsPerPage = MetricsGridRows * MetricsGridCols
	g.totalPages = (len(g.allCharts) + MetricsPerPage - 1) / MetricsPerPage

	// Ensure current page is valid
	if g.currentPage >= g.totalPages && g.totalPages > 0 {
		g.currentPage = g.totalPages - 1
	}

	// Reload current page
	g.loadCurrentPage()

	// Resize all charts
	dims := g.calculateChartDimensions()
	for _, chart := range g.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.DrawBraille()
	}
}

// NewRightSidebar creates a new right sidebar instance
func NewRightSidebar() *RightSidebar {
	return &RightSidebar{
		state:         SidebarCollapsed,
		currentWidth:  0,
		targetWidth:   0,
		expandedWidth: SidebarMinWidth,
		metricsGrid:   NewSystemMetricsGrid(SidebarMinWidth-3, 20), // Will be resized
	}
}

// UpdateDimensions updates the right sidebar dimensions based on terminal width and left sidebar state
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		// When both sidebars are visible, use nested golden ratio
		// 0.382 * 0.618 ≈ 0.236
		calculatedWidth = int(float64(terminalWidth) * 0.236)
	} else {
		// When only right sidebar is visible, use standard golden ratio
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

	// Update target width if expanded
	if rs.state == SidebarExpanded {
		rs.targetWidth = rs.expandedWidth
		rs.currentWidth = rs.expandedWidth
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
	case SidebarExpanded:
		rs.state = SidebarCollapsing
		rs.targetWidth = 0
		rs.animationStep = 0
		rs.animationTimer = time.Now()
	}
}

// Update handles animation updates and forwards system metrics data
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	var cmds []tea.Cmd

	// Handle system metrics data
	switch msg := msg.(type) {
	case StatsMsg:
		// Forward data to metrics grid
		for metricName, value := range msg.Metrics {
			rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
		}
	case tea.KeyMsg:
		if rs.state == SidebarExpanded {
			switch msg.Type {
			case tea.KeyCtrlPgUp, tea.KeyCtrlShiftUp:
				rs.metricsGrid.Navigate(-1)
			case tea.KeyCtrlPgDown, tea.KeyCtrlShiftDown:
				rs.metricsGrid.Navigate(1)
			}
		}
	}

	// Handle animation
	if rs.state == SidebarExpanding || rs.state == SidebarCollapsing {
		elapsed := time.Since(rs.animationTimer)
		progress := float64(elapsed) / float64(AnimationDuration)

		if progress >= 1.0 {
			// Animation complete
			rs.currentWidth = rs.targetWidth
			if rs.state == SidebarExpanding {
				rs.state = SidebarExpanded
			} else {
				rs.state = SidebarCollapsed
			}
		} else {
			// Animate width using easing function
			if rs.state == SidebarExpanding {
				rs.currentWidth = int(easeOutCubic(progress) * float64(rs.expandedWidth))
			} else {
				rs.currentWidth = int((1 - easeOutCubic(progress)) * float64(rs.expandedWidth))
			}

			// Continue animation
			cmds = append(cmds, rs.animationCmd())
		}
	}

	return rs, tea.Batch(cmds...)
}

// View renders the right sidebar
func (rs *RightSidebar) View(height int) string {
	if rs.currentWidth <= 0 {
		return ""
	}

	// Update metrics grid dimensions
	rs.metricsGrid.Resize(rs.currentWidth-3, height-1)

	// Build header with navigation info
	header := rightSidebarHeaderStyle.Render("System Metrics")

	// Add navigation info
	navInfo := ""
	if rs.metricsGrid.totalPages > 0 {
		startIdx := rs.metricsGrid.currentPage*MetricsPerPage + 1
		endIdx := startIdx + MetricsPerPage - 1
		totalMetrics := len(rs.metricsGrid.allCharts)
		if endIdx > totalMetrics {
			endIdx = totalMetrics
		}
		navInfo = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")).
			Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, totalMetrics))
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
		Width(rs.currentWidth - 1). // Account for border
		Height(height).
		MaxWidth(rs.currentWidth - 1).
		MaxHeight(height).
		Render(content)

	// Apply border (only on the left side)
	bordered := rightSidebarBorderStyle.
		Width(rs.currentWidth).
		Height(height).
		MaxWidth(rs.currentWidth).
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

// UpdateExpandedWidth recalculates the expanded width based on the current terminal width
// and whether the other sidebar is visible. This ensures correct width when toggling.
func (rs *RightSidebar) UpdateExpandedWidth(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		// When both sidebars are visible, use nested golden ratio
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		// When only right sidebar is visible, use standard golden ratio
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
}

// ProcessStatsMsg processes a stats message and updates the metrics
func (rs *RightSidebar) ProcessStatsMsg(msg StatsMsg) {
	if rs.metricsGrid != nil {
		for metricName, value := range msg.Metrics {
			rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
		}
	}
}

// Reset clears all system metrics data
func (rs *RightSidebar) Reset() {
	// Reset the metrics grid
	if rs.metricsGrid != nil {
		rs.metricsGrid.Reset()
	}
}
