package leet

import (
	"fmt"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

const (
	systemMetricsHeader = "System Metrics"

	// Sidebar content padding (accounts for borders and internal spacing).
	sidebarContentPadding = 3

	// Default grid height for system metrics when not calculated from terminal height.
	defaultSystemGridHeight = 40

	// Mouse click coordinate adjustments for border/padding.
	mouseClickPaddingOffset = 1
)

// RightSidebar represents a collapsible right sidebar panel displaying system metrics.
type RightSidebar struct {
	config      *ConfigManager
	animState   *AnimationState
	metricsGrid *SystemMetricsGrid
	focusState  *FocusState
	logger      *observability.CoreLogger
}

// NewRightSidebar creates a new right sidebar.
func NewRightSidebar(
	config *ConfigManager,
	focusState *FocusState,
	logger *observability.CoreLogger,
) *RightSidebar {
	animState := NewAnimationState(config.RightSidebarVisible(), SidebarMinWidth)

	return &RightSidebar{
		config:     config,
		animState:  animState,
		logger:     logger,
		focusState: focusState,
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

	// Resize existing grid if visible and dimensions are valid.
	if rs.metricsGrid != nil && rs.animState.IsVisible() {
		if gridWidth := rs.calculateGridWidth(); gridWidth > 0 {
			rs.metricsGrid.Resize(gridWidth, defaultSystemGridHeight)
		}
	}
}

// Toggle toggles the sidebar between expanded and collapsed states.
func (rs *RightSidebar) Toggle() {
	rs.animState.Toggle()

	// Initialize grid when starting to expand (if not already created).
	if rs.animState.State() == SidebarExpanding && rs.metricsGrid == nil {
		rs.initializeGrid()
	}
}

// HandleMouseClick handles mouse clicks in the sidebar and returns true if focus changed.
func (rs *RightSidebar) HandleMouseClick(x, y int) bool {
	rs.logger.Debug(fmt.Sprintf(
		"RightSidebar.HandleMouseClick: x=%d, y=%d, state=%v",
		x, y, rs.animState.State()))

	if !rs.canHandleInteraction() {
		return false
	}

	// Adjust coordinates for border/padding.
	adjustedX := x - mouseClickPaddingOffset
	adjustedY := y - mouseClickPaddingOffset

	if adjustedX < 0 || adjustedY < 0 {
		return false
	}

	dims := rs.metricsGrid.calculateChartDimensions()

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	return rs.metricsGrid.HandleMouseClick(row, col)
}

// GetFocusedChartTitle returns the title of the focused chart, or empty string if none.
func (rs *RightSidebar) GetFocusedChartTitle() string {
	if rs.metricsGrid != nil {
		return rs.metricsGrid.GetFocusedChartTitle()
	}
	return ""
}

// ClearFocus clears focus from the currently focused system chart.
func (rs *RightSidebar) ClearFocus() {
	if rs.metricsGrid != nil {
		rs.metricsGrid.ClearFocus()
	}
}

// Update handles animation updates and stats processing.
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	if statsMsg, ok := msg.(StatsMsg); ok {
		rs.ProcessStatsMsg(statsMsg)
	}

	if rs.animState.IsAnimating() {
		complete := rs.animState.Update()
		if complete {
			// Animation just completed - resize grid if needed.
			rs.onAnimationComplete()
		} else {
			return rs, rs.animationCmd()
		}
	}

	return rs, nil
}

// View renders the right sidebar.
func (rs *RightSidebar) View(height int) string {
	if rs.animState.Width() <= sidebarContentPadding {
		return ""
	}

	gridWidth := rs.calculateGridWidth()
	gridHeight := rs.calculateGridHeight(height)

	if gridWidth <= 0 || gridHeight <= 0 {
		return ""
	}

	rs.ensureGrid(gridWidth, gridHeight)

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
		"RightSidebar.ProcessStatsMsg: processing %d metrics (state=%v, width=%d)",
		len(msg.Metrics), rs.animState.State(), rs.animState.Width()))

	// Ensure grid exists before adding data.
	if rs.metricsGrid == nil {
		rs.initializeGrid()
	}

	// Add all data points to the grid.
	for metricName, value := range msg.Metrics {
		rs.metricsGrid.AddDataPoint(metricName, msg.Timestamp, value)
	}
}

// initializeGrid creates a new metrics grid with initial dimensions.
func (rs *RightSidebar) initializeGrid() {
	gridRows, gridCols := rs.config.SystemGrid()
	initialWidth := MinMetricChartWidth * gridCols
	initialHeight := MinMetricChartHeight * gridRows

	rs.metricsGrid = NewSystemMetricsGrid(
		initialWidth, initialHeight, rs.config, rs.focusState, rs.logger)

	rs.logger.Debug(fmt.Sprintf(
		"RightSidebar.initializeGrid: created grid with dimensions %dx%d",
		initialWidth, initialHeight))
}

// ensureGrid ensures the grid exists and is properly sized.
//
// This should only be called from View() to maintain proper lifecycle.
func (rs *RightSidebar) ensureGrid(width, height int) {
	if rs.metricsGrid == nil {
		rs.metricsGrid = NewSystemMetricsGrid(
			width, height, rs.config, rs.focusState, rs.logger)
		rs.logger.Debug(fmt.Sprintf(
			"RightSidebar.ensureGrid: created grid in View with dimensions %dx%d",
			width, height))
	} else {
		rs.metricsGrid.Resize(width, height)
	}
}

// onAnimationComplete handles actions after animation completes.
func (rs *RightSidebar) onAnimationComplete() {
	if rs.animState.State() == SidebarExpanded && rs.metricsGrid != nil {
		if gridWidth := rs.calculateGridWidth(); gridWidth > 0 {
			rs.metricsGrid.Resize(gridWidth, defaultSystemGridHeight)
		}
	}
}

// calculateGridWidth returns the available width for the metrics grid.
func (rs *RightSidebar) calculateGridWidth() int {
	return rs.animState.Width() - sidebarContentPadding
}

// calculateGridHeight returns the available height for the metrics grid.
func (rs *RightSidebar) calculateGridHeight(sidebarHeight int) int {
	// Reserve one line for the header.
	const headerLines = 1
	return sidebarHeight - headerLines
}

// canHandleInteraction returns true if the sidebar can handle mouse interactions.
func (rs *RightSidebar) canHandleInteraction() bool {
	return rs.animState.IsVisible() && rs.metricsGrid != nil
}

// renderHeader renders the header line with title and navigation info.
func (rs *RightSidebar) renderHeader() string {
	header := rightSidebarHeaderStyle.Render(systemMetricsHeader)

	// Add navigation info if we have multiple pages.
	navInfo := rs.buildNavigationInfo()
	if navInfo != "" {
		return lipgloss.JoinHorizontal(lipgloss.Left, header, navInfo)
	}

	return header
}

// buildNavigationInfo builds the navigation info string for the header.
func (rs *RightSidebar) buildNavigationInfo() string {
	if rs.metricsGrid == nil {
		return ""
	}

	chartCount := rs.metricsGrid.GetChartCount()
	size := rs.metricsGrid.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)

	// Only show navigation if we have charts and pagination.
	if rs.metricsGrid.navigator.TotalPages() == 0 || chartCount == 0 || itemsPerPage == 0 {
		return ""
	}

	startIdx, endIdx := rs.metricsGrid.navigator.GetPageBounds(chartCount, itemsPerPage)
	startIdx++ // Display as 1-indexed

	return navInfoStyle.Render(fmt.Sprintf(" [%d-%d of %d]", startIdx, endIdx, chartCount))
}

// animationCmd returns a command to continue the animation.
func (rs *RightSidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return RightSidebarAnimationMsg{}
	})
}
