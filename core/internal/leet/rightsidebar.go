package leet

import (
	"fmt"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/wandb/wandb/core/internal/observability"
)

const rightSidebarHeader = "System Metrics"

// RightSidebar represents a collapsible right sidebar displaying system metrics.
type RightSidebar struct {
	config      *ConfigManager
	animState   *AnimationState
	metricsGrid *SystemMetricsGrid
	focusState  *Focus
	logger      *observability.CoreLogger
}

func NewRightSidebar(
	config *ConfigManager,
	focusState *Focus,
	logger *observability.CoreLogger,
) *RightSidebar {
	rows, cols := config.SystemGrid()
	initW := MinMetricChartWidth * cols
	initH := MinMetricChartHeight * rows

	return &RightSidebar{
		config:      config,
		animState:   NewAnimationState(config.RightSidebarVisible(), SidebarMinWidth),
		metricsGrid: NewSystemMetricsGrid(initW, initH, config, focusState, logger),
		logger:      logger,
		focusState:  focusState,
	}
}

// UpdateDimensions updates the right sidebar dimensions based on terminal width
// and the visibility of the left sidebar.
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	expandedWidth := clamp(calculatedWidth, SidebarMinWidth, SidebarMaxWidth)
	rs.animState.SetExpandedWidth(expandedWidth)

	if gridWidth := rs.calculateGridWidth(); gridWidth > 0 {
		rs.metricsGrid.Resize(gridWidth, defaultSystemMetricsGridHeight)
	}
}

// Toggle toggles the sidebar between expanded and collapsed states.
func (rs *RightSidebar) Toggle() {
	rs.animState.Toggle()
}

// HandleMouseClick handles mouse clicks in the sidebar and returns true if focus changed.
func (rs *RightSidebar) HandleMouseClick(x, y int) bool {
	rs.logger.Debug(fmt.Sprintf(
		"rightsidebar: HandleMouseClick: x=%d, y=%d, state=%v",
		x, y, rs.animState))

	if !rs.animState.IsVisible() {
		return false
	}

	// Adjust coordinates for border/padding.
	adjustedX := x - rightSidebarMouseClickPaddingOffset
	adjustedY := y - rightSidebarMouseClickPaddingOffset

	if adjustedX < 0 || adjustedY < 0 {
		return false
	}

	dims := rs.metricsGrid.calculateChartDimensions()

	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	return rs.metricsGrid.HandleMouseClick(row, col)
}

// FocusedChartTitle returns the title of the focused chart, or empty string if none.
func (rs *RightSidebar) FocusedChartTitle() string {
	return rs.metricsGrid.FocusedChartTitle()
}

// ClearFocus clears focus from the currently focused system chart.
func (rs *RightSidebar) ClearFocus() {
	rs.metricsGrid.ClearFocus()
}

// Update handles animation updates and stats processing.
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	if statsMsg, ok := msg.(StatsMsg); ok {
		rs.ProcessStatsMsg(statsMsg)
	}

	if rs.animState.IsAnimating() && !rs.animState.Update(time.Now()) {
		return rs, rs.animationCmd()
	}

	return rs, nil
}

// View renders the right sidebar.
func (rs *RightSidebar) View(height int) string {
	if rs.animState.Width() <= rightSidebarContentPadding {
		return ""
	}

	gridWidth := rs.calculateGridWidth()
	gridHeight := rs.calculateGridHeight(height)

	if gridWidth <= 0 || gridHeight <= 0 {
		return ""
	}

	rs.metricsGrid.Resize(gridWidth, gridHeight)

	header := rs.renderHeader()
	metricsView := rs.metricsGrid.View()

	content := lipgloss.JoinVertical(lipgloss.Left, header, metricsView)

	styledContent := rightSidebarStyle.
		Width(rs.animState.Width() - 1).
		Height(height).
		MaxWidth(rs.animState.Width() - 1).
		MaxHeight(height).
		Render(content)

	return rightSidebarBorderStyle.
		Width(rs.animState.Width()).
		Height(height).
		MaxHeight(height).
		Render(styledContent)
}

// Width returns the current width of the sidebar.
func (rs *RightSidebar) Width() int {
	return rs.animState.Width()
}

// IsVisible returns true if the sidebar is visible.
func (rs *RightSidebar) IsVisible() bool {
	return rs.animState.IsVisible()
}

// IsAnimating returns true if the sidebar is currently animating.
func (rs *RightSidebar) IsAnimating() bool {
	return rs.animState.IsAnimating()
}

// ProcessStatsMsg processes a stats message and updates the metrics.
func (rs *RightSidebar) ProcessStatsMsg(msg StatsMsg) {
	rs.logger.Debug(fmt.Sprintf(
		"rightsidebar: ProcessStatsMsg: processing %d metrics (state=%v, width=%d)",
		len(msg.Metrics), rs.animState, rs.animState.Width()))

	// Add all data points to the grid.
	for metricName, value := range msg.Metrics {
		rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
	}
}

// calculateGridWidth returns the available width for the metrics grid.
func (rs *RightSidebar) calculateGridWidth() int {
	return rs.animState.Width() - rightSidebarContentPadding
}

// calculateGridHeight returns the available height for the metrics grid.
func (rs *RightSidebar) calculateGridHeight(sidebarHeight int) int {
	// Reserve one line for the header.
	const headerLines = 1
	return sidebarHeight - headerLines
}

// renderHeader renders the header line with title and navigation info.
func (rs *RightSidebar) renderHeader() string {
	header := rightSidebarHeaderStyle.Render(rightSidebarHeader)

	// Add navigation info if we have multiple pages.
	navInfo := rs.buildNavigationInfo()
	if navInfo != "" {
		return lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)
	}

	return header
}

// buildNavigationInfo builds the navigation info string for the header.
func (rs *RightSidebar) buildNavigationInfo() string {
	chartCount := rs.metricsGrid.ChartCount()
	size := rs.metricsGrid.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)

	// Only show navigation if we have charts and pagination.
	if rs.metricsGrid.nav.TotalPages() == 0 || chartCount == 0 || itemsPerPage == 0 {
		return ""
	}

	startIdx, endIdx := rs.metricsGrid.nav.PageBounds(chartCount, itemsPerPage)
	startIdx++ // Display as 1-indexed

	return navInfoStyle.Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
}

// animationCmd returns a command to continue the animation.
func (rs *RightSidebar) animationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return RightSidebarAnimationMsg{}
	})
}
