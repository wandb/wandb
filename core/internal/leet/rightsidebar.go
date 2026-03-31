package leet

import (
	"fmt"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	rightSidebarHeader      = "System Metrics"
	rightSidebarHeaderLines = 1
	// rightSidebarGridXOffset is the X offset from the sidebar's left edge
	// to the start of the grid content (border + left padding).
	rightSidebarGridXOffset = SidebarBorderCols + ContentPadding
)

// RightSidebar represents a collapsible right sidebar displaying system metrics.
type RightSidebar struct {
	config      *ConfigManager
	animState   *AnimatedValue
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
		config:    config,
		animState: NewAnimatedValue(config.RightSidebarVisible(), SidebarMinWidth),
		metricsGrid: NewSystemMetricsGrid(
			initW, initH, config, config.SystemGrid, focusState, NewFilter(), logger),
		logger:     logger,
		focusState: focusState,
	}
}

// UpdateDimensions updates the right sidebar dimensions based on terminal width
// and the visibility of the left sidebar.
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	rs.animState.SetExpanded(expandedSidebarWidth(terminalWidth, leftSidebarVisible))

	if gridWidth := sidebarContentWidth(rs.animState.Value()); gridWidth > 0 {
		rs.metricsGrid.Resize(gridWidth, defaultSystemMetricsGridHeight)
	}
}

// Toggle toggles the sidebar between expanded and collapsed states.
func (rs *RightSidebar) Toggle() {
	rs.animState.Toggle()
}

type systemGridMouseTarget struct {
	adjustedX int
	adjustedY int
	row       int
	col       int
	dims      GridDims
}

func (rs *RightSidebar) gridMouseTarget(x, y int) (systemGridMouseTarget, bool) {
	if !rs.animState.IsVisible() {
		return systemGridMouseTarget{}, false
	}

	target := systemGridMouseTarget{
		adjustedX: x - rightSidebarGridXOffset,
		adjustedY: y - rightSidebarHeaderLines,
	}
	if target.adjustedX < 0 || target.adjustedY < 0 {
		return systemGridMouseTarget{}, false
	}

	target.dims = rs.metricsGrid.calculateChartDimensions()
	target.row = target.adjustedY / target.dims.CellHWithPadding
	target.col = target.adjustedX / target.dims.CellWWithPadding
	return target, true
}

// HandleMouseClick handles mouse clicks in the sidebar and returns true if focus changed.
func (rs *RightSidebar) HandleMouseClick(x, y int) bool {
	rs.logger.Debug(fmt.Sprintf(
		"rightsidebar: HandleMouseClick: x=%d, y=%d, state=%v",
		x, y, rs.animState))

	target, ok := rs.gridMouseTarget(x, y)
	if !ok {
		return false
	}

	return rs.metricsGrid.HandleMouseClick(target.row, target.col)
}

// HandleWheel zooms the chart under the mouse cursor.
func (rs *RightSidebar) HandleWheel(x, y int, wheelUp bool) {
	target, ok := rs.gridMouseTarget(x, y)
	if !ok {
		return
	}
	rs.metricsGrid.HandleWheel(
		target.adjustedX, target.row, target.col, target.dims, wheelUp)
}

// StartInspection begins chart inspection under the mouse cursor.
func (rs *RightSidebar) StartInspection(x, y int, synced bool) {
	target, ok := rs.gridMouseTarget(x, y)
	if !ok {
		return
	}
	rs.metricsGrid.StartInspection(
		target.adjustedX,
		target.adjustedY,
		target.row,
		target.col,
		target.dims,
		synced,
	)
}

// UpdateInspection moves the inspection cursor.
func (rs *RightSidebar) UpdateInspection(x, y int) {
	target, ok := rs.gridMouseTarget(x, y)
	if !ok {
		return
	}
	rs.metricsGrid.UpdateInspection(
		target.adjustedX,
		target.adjustedY,
		target.row,
		target.col,
		target.dims,
	)
}

// EndInspection clears inspection mode.
func (rs *RightSidebar) EndInspection() {
	rs.metricsGrid.EndInspection()
}

// FocusedChartTitle returns the title of the focused chart, or empty string if none.
func (rs *RightSidebar) FocusedChartTitle() string {
	return rs.metricsGrid.FocusedChartTitle()
}

// FocusedChartViewModeLabel returns a short description of the focused chart view mode.
func (rs *RightSidebar) FocusedChartViewModeLabel() string {
	return rs.metricsGrid.FocusedChartViewModeLabel()
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
		cmd := rs.animationCmd()
		return rs, cmd
	}

	return rs, nil
}

// View renders the right sidebar.
func (rs *RightSidebar) View(height int) string {
	width := rs.animState.Value()
	if height <= 0 || width <= SidebarOverhead {
		return ""
	}

	contentW := sidebarContentWidth(width)
	innerW := sidebarInnerWidth(width)
	gridHeight := rs.calculateGridHeight(height)
	if contentW <= 0 || innerW <= 0 || gridHeight <= 0 {
		return ""
	}

	rs.metricsGrid.Resize(contentW, gridHeight)

	head := lipgloss.Place(
		contentW,
		rightSidebarHeaderLines,
		lipgloss.Left,
		lipgloss.Top,
		rs.renderHeader(),
	)
	body := lipgloss.JoinVertical(lipgloss.Left, head, rs.metricsGrid.View())
	styled := rightSidebarStyle.
		Width(innerW).
		MaxWidth(innerW).
		Height(height).
		MaxHeight(height).
		Render(body)
	bordered := rightSidebarBorderStyle.
		Height(height).
		MaxHeight(height).
		Render(styled)
	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, bordered)
}

// Width returns the current width of the sidebar.
func (rs *RightSidebar) Width() int {
	return rs.animState.Value()
}

// IsVisible returns true if the sidebar is visible.
func (rs *RightSidebar) IsVisible() bool {
	return rs.animState.IsVisible()
}

// IsAnimating returns true if the sidebar is currently animating.
func (rs *RightSidebar) IsAnimating() bool {
	return rs.animState.IsAnimating()
}

// HandleFilterKey delegates filter key handling to the inner metrics grid.
func (rs *RightSidebar) HandleFilterKey(msg tea.KeyPressMsg) {
	rs.metricsGrid.handleFilterKey(msg)
}

// IsFilterMode returns true if the metrics grid is currently in filter input mode.
func (rs *RightSidebar) IsFilterMode() bool {
	return rs.metricsGrid.filter.IsActive()
}

// IsFiltering returns true if the metrics grid has an applied filter.
func (rs *RightSidebar) IsFiltering() bool {
	return !rs.metricsGrid.filter.IsActive() && rs.metricsGrid.filter.Query() != ""
}

// ProcessStatsMsg processes a stats message and updates the metrics.
func (rs *RightSidebar) ProcessStatsMsg(msg StatsMsg) {
	rs.logger.Debug(fmt.Sprintf(
		"rightsidebar: ProcessStatsMsg: processing %d metrics (state=%v, width=%d)",
		len(msg.Metrics), rs.animState, rs.animState.Value()))

	// Add all data points to the grid.
	for metricName, value := range msg.Metrics {
		rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
	}
}

// calculateGridHeight returns the available height for the metrics grid.
func (rs *RightSidebar) calculateGridHeight(sidebarHeight int) int {
	return sidebarHeight - rightSidebarHeaderLines
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
	totalCount := rs.metricsGrid.ChartCount()
	filteredCount := rs.metricsGrid.FilteredChartCount()
	size := rs.metricsGrid.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)

	// Only show navigation if we have charts and pagination.
	if rs.metricsGrid.nav.TotalPages() == 0 || filteredCount == 0 || itemsPerPage == 0 {
		return ""
	}

	startIdx, endIdx := rs.metricsGrid.nav.PageBounds(filteredCount, itemsPerPage)
	startIdx++ // Display as 1-indexed

	if filteredCount != totalCount {
		return navInfoStyle.Render(fmt.Sprintf(
			" [%d-%d of %d filtered from %d total]",
			startIdx,
			endIdx,
			filteredCount,
			totalCount,
		))
	}

	return navInfoStyle.Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, filteredCount))
}

// animationCmd returns a command to continue the animation.
func (rs *RightSidebar) animationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return RightSidebarAnimationMsg{}
	})
}
