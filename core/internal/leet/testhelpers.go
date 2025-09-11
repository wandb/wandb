// TestAPI provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// TestFocusState returns the current focus state
func (m *Model) TestFocusState() FocusState {
	return m.focusState
}

// TestRunOverview returns the current run overview
func (m *Model) TestRunOverview() RunOverview {
	return m.runOverview
}

// TestRunState returns the current run state
func (m *Model) TestRunState() RunState {
	return m.runState
}

// TestLeftSidebarVisible returns true if the left sidebar is visible
func (m *Model) TestLeftSidebarVisible() bool {
	return m.sidebar.IsVisible()
}

// TestSidebarIsFiltering returns true if the sidebar has an active filter
func (m *Model) TestSidebarIsFiltering() bool {
	return m.sidebar.IsFiltering()
}

// TestSidebarFilterQuery returns the current sidebar filter query
func (m *Model) TestSidebarFilterQuery() string {
	return m.sidebar.GetFilterQuery()
}

// TestGetLeftSidebar returns the left sidebar for testing
func (m *Model) TestGetLeftSidebar() *Sidebar {
	return m.sidebar
}

// TestProcessRecordMsg processes a record message
func (m *Model) TestProcessRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	return m.processRecordMsg(msg)
}

// TestHandleChartGridClick handles a click on the main chart grid
func (m *Model) TestHandleChartGridClick(row, col int) {
	m.handleChartGridClick(row, col)
}

// TestSetMainChartFocus sets focus to a main chart
func (m *Model) TestSetMainChartFocus(row, col int) {
	m.setMainChartFocus(row, col)
}

// TestClearMainChartFocus clears focus from main charts
func (m *Model) TestClearMainChartFocus() {
	m.clearMainChartFocus()
}

// TestClearAllFocus clears all focus
func (m *Model) TestClearAllFocus() {
	m.clearAllFocus()
}

// TestForceExpand forces the sidebar to expanded state without animation
func (s *Sidebar) TestForceExpand() {
	s.state = SidebarExpanded
	s.currentWidth = s.expandedWidth
	s.targetWidth = s.expandedWidth
	s.animationTimer = time.Now().Add(-AnimationDuration)
}

// TestGetChartCount returns the number of charts in the grid
func (rs *RightSidebar) TestGetChartCount() int {
	if rs.metricsGrid == nil {
		return 0
	}
	return rs.metricsGrid.GetChartCount()
}

// TestMetricsChart returns a chart by base key for testing
func (rs *RightSidebar) TestMetricsChart(baseKey string) *SystemMetricChart {
	if rs.metricsGrid == nil {
		return nil
	}
	return rs.metricsGrid.chartsByMetric[baseKey]
}

// TestSeriesCount returns the number of series in the chart
func (c *SystemMetricChart) TestSeriesCount() int {
	return len(c.series)
}

// Add test helper to Model for getting active filter
func (m *Model) TestGetActiveFilter() string {
	return m.activeFilter
}
