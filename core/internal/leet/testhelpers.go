// Test<API> provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// TestFocusState returns the current focus state
func (m *Run) TestFocusState() *Focus {
	return m.focus
}

func (m *Run) TestRunID() string {
	return m.leftSidebar.runOverview.runID
}

func (m *Run) TestRunDisplayName() string {
	return m.leftSidebar.runOverview.displayName
}

func (m *Run) TestRunProject() string {
	return m.leftSidebar.runOverview.project
}

// TestRunState returns the current run state
func (m *Run) TestRunState() RunState {
	return m.runState
}

// TestLeftSidebarVisible returns true if the left sidebar is visible
func (m *Run) TestLeftSidebarVisible() bool {
	return m.leftSidebar.IsVisible()
}

// TestSidebarIsFiltering returns true if the sidebar has an active filter
func (m *Run) TestSidebarIsFiltering() bool {
	return m.leftSidebar.IsFiltering()
}

// TestSidebarFilterQuery returns the current sidebar filter query
func (m *Run) TestSidebarFilterQuery() string {
	return m.leftSidebar.FilterQuery()
}

// TestGetLeftSidebar returns the left sidebar for testing
func (m *Run) TestGetLeftSidebar() *LeftSidebar {
	return m.leftSidebar
}

// TestHandleRecordMsg processes a record message
func (m *Run) TestHandleRecordMsg(msg tea.Msg) (*Run, tea.Cmd) {
	return m.handleRecordMsg(msg)
}

// TestHandleChartGridClick handles a click on the main chart grid
func (m *Run) TestHandleChartGridClick(row, col int) {
	m.metricsGrid.HandleClick(row, col)
}

// TestSetMainChartFocus sets focus to a main chart
func (m *Run) TestSetMainChartFocus(row, col int) {
	m.metricsGrid.setFocus(row, col)
}

// TestClearMainChartFocus clears focus from main charts
func (m *Run) TestClearMainChartFocus() {
	m.metricsGrid.clearFocus()
}

// TestForceExpand forces the sidebar to expanded state without animation
func (s *LeftSidebar) TestForceExpand() {
	s.animState.currentWidth = s.animState.expandedWidth
	s.animState.targetWidth = s.animState.expandedWidth
	s.animState.animationStartTime = time.Now().Add(-AnimationDuration)
}

// TestSeriesCount returns the number of series in the chart
func (c *TimeSeriesLineChart) TestSeriesCount() int {
	return len(c.series)
}

// TestCurrentPage returns the current grid of charts.
func (g *SystemMetricsGrid) TestCurrentPage() [][]*TimeSeriesLineChart {
	return g.currentPage
}

// TestInspectionMouseX exposes the current overlay pixel X for tests.
// This keeps production APIs clean while allowing focused assertions.
func (c *EpochLineChart) TestInspectionMouseX() (int, bool) {
	return c.inspection.MouseX, c.inspection.Active
}

// TestChartAt returns the chart at (row, col) on the current page (or nil).
func (mg *MetricsGrid) TestChartAt(row, col int) *EpochLineChart {
	mg.mu.RLock()
	defer mg.mu.RUnlock()
	if row < 0 || row >= len(mg.currentPage) ||
		col < 0 || col >= len(mg.currentPage[row]) {
		return nil
	}
	return mg.currentPage[row][col]
}

// TestSyncInspectActive exposes the synchronized inspection flag for tests.
func (mg *MetricsGrid) TestSyncInspectActive() bool {
	return mg.syncInspectActive
}
