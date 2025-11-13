// Test<API> provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// TestFocusState returns the current focus state
func (m *Model) TestFocusState() *Focus {
	return m.focus
}

func (m *Model) TestRunID() string {
	return m.leftSidebar.runOverview.runID
}

func (m *Model) TestRunDisplayName() string {
	return m.leftSidebar.runOverview.displayName
}

func (m *Model) TestRunProject() string {
	return m.leftSidebar.runOverview.project
}

// TestRunState returns the current run state
func (m *Model) TestRunState() RunState {
	return m.runState
}

// TestLeftSidebarVisible returns true if the left sidebar is visible
func (m *Model) TestLeftSidebarVisible() bool {
	return m.leftSidebar.IsVisible()
}

// TestSidebarIsFiltering returns true if the sidebar has an active filter
func (m *Model) TestSidebarIsFiltering() bool {
	return m.leftSidebar.IsFiltering()
}

// TestSidebarFilterQuery returns the current sidebar filter query
func (m *Model) TestSidebarFilterQuery() string {
	return m.leftSidebar.FilterQuery()
}

// TestGetLeftSidebar returns the left sidebar for testing
func (m *Model) TestGetLeftSidebar() *LeftSidebar {
	return m.leftSidebar
}

// TestProcessRecordMsg processes a record message
func (m *Model) TestProcessRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	return m.processRecordMsg(msg)
}

// TestHandleChartGridClick handles a click on the main chart grid
func (m *Model) TestHandleChartGridClick(row, col int) {
	m.metricsGrid.HandleClick(row, col)
}

// TestSetMainChartFocus sets focus to a main chart
func (m *Model) TestSetMainChartFocus(row, col int) {
	m.metricsGrid.setFocus(row, col)
}

// TestClearMainChartFocus clears focus from main charts
func (m *Model) TestClearMainChartFocus() {
	m.metricsGrid.clearFocus()
}

// TestForceExpand forces the sidebar to expanded state without animation
func (s *LeftSidebar) TestForceExpand() {
	s.animState.currentWidth = s.animState.expandedWidth
	s.animState.targetWidth = s.animState.expandedWidth
	s.animState.animationStartTime = time.Now().Add(-AnimationDuration)
}

// TestGetChartCount returns the number of charts in the grid
func (rs *RightSidebar) TestGetChartCount() int {
	if rs.metricsGrid == nil {
		return 0
	}
	return rs.metricsGrid.ChartCount()
}

// TestMetricsChart returns a chart by base key for testing
func (rs *RightSidebar) TestMetricsChart(baseKey string) *TimeSeriesLineChart {
	if rs.metricsGrid == nil {
		return nil
	}
	return rs.metricsGrid.byBaseKey[baseKey]
}

// TestSeriesCount returns the number of series in the chart
func (c *TimeSeriesLineChart) TestSeriesCount() int {
	return len(c.series)
}

// CurrentPage returns the current grid of charts.
func (g *SystemMetricsGrid) CurrentPage() [][]*TimeSeriesLineChart {
	return g.currentPage
}

// Add test helper to Model for getting active filter
func (m *Model) TestAppliedFilter() string {
	return m.metricsGrid.filter.applied
}
