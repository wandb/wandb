package leet

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

const systemMetricsHeader = "System Metrics"

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

// UpdateDimensions updates the right sidebar dimensions.
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	expandedWidth := clamp(calculatedWidth, SidebarMinWidth, SidebarMaxWidth)
	rs.animState.SetExpandedWidth(expandedWidth)

	if rs.metricsGrid != nil && rs.animState.IsVisible() && rs.animState.Width() > 3 {
		gridWidth := rs.animState.Width() - 3
		gridHeight := 40
		rs.metricsGrid.Resize(gridWidth, gridHeight)
	}
}

// Toggle flips the sidebar state.
func (rs *RightSidebar) Toggle() {
	rs.animState.Toggle()

	// Create grid on expansion if not already created
	if rs.animState.State() == SidebarExpanding && rs.metricsGrid == nil {
		gridRows, gridCols := rs.config.SystemGrid()
		initialWidth := MinMetricChartWidth * gridCols
		initialHeight := MinMetricChartHeight * gridRows
		rs.metricsGrid = NewSystemMetricsGrid(
			initialWidth, initialHeight, rs.config, rs.focusState, rs.logger)
		rs.logger.Debug("RightSidebar.Toggle: created grid on expansion")
	}
}

// HandleMouseClick handles mouse clicks in the sidebar.
func (rs *RightSidebar) HandleMouseClick(x, y int) bool {
	rs.logger.Debug(fmt.Sprintf(
		"RightSidebar.HandleMouseClick: x=%d, y=%d, state=%v",
		x, y, rs.animState.State()))

	if !rs.animState.IsVisible() || rs.metricsGrid == nil {
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

// Update handles animation updates and stats processing.
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	// Process stats messages
	if msg, ok := msg.(StatsMsg); ok {
		rs.ProcessStatsMsg(msg)
	}

	// Handle animation
	cmd, complete := rs.animState.Update()
	if complete {
		// Animation just completed
		if rs.animState.State() == SidebarExpanded && rs.metricsGrid != nil {
			gridWidth := rs.animState.Width() - 3
			gridHeight := 40
			if gridWidth > 0 {
				rs.metricsGrid.Resize(gridWidth, gridHeight)
			}
		}
	}

	return rs, cmd
}

// View renders the right sidebar.
func (rs *RightSidebar) View(height int) string {
	if rs.animState.Width() <= 3 {
		return ""
	}

	header := rightSidebarHeaderStyle.Render(systemMetricsHeader)

	gridWidth := rs.animState.Width() - 3
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

func (m *RightSidebar) animationCmd() tea.Cmd {
	cmd, _ := m.animState.Update()
	return cmd
}

// ProcessStatsMsg processes a stats message and updates the metrics.
func (rs *RightSidebar) ProcessStatsMsg(msg StatsMsg) {
	rs.logger.Debug(fmt.Sprintf(
		"RightSidebar.ProcessStatsMsg: processing %d metrics (state=%v, width=%d)",
		len(msg.Metrics), rs.animState.State(), rs.animState.Width()))

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
