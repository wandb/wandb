// Test<API> provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// TestFocusState returns the current focus state
func (r *Run) TestFocusState() *Focus {
	return r.focus
}

func (r *Run) TestRunID() string {
	return r.leftSidebar.runOverview.runID
}

func (r *Run) TestRunDisplayName() string {
	return r.leftSidebar.runOverview.displayName
}

func (r *Run) TestRunProject() string {
	return r.leftSidebar.runOverview.project
}

// TestRunState returns the current run state
func (r *Run) TestRunState() RunState {
	return r.runState
}

// TestLeftSidebarVisible returns true if the left sidebar is visible
func (r *Run) TestLeftSidebarVisible() bool {
	return r.leftSidebar.IsVisible()
}

// TestSidebarIsFiltering returns true if the sidebar has an active filter
func (r *Run) TestSidebarIsFiltering() bool {
	return r.leftSidebar.IsFiltering()
}

// TestSidebarFilterQuery returns the current sidebar filter query
func (r *Run) TestSidebarFilterQuery() string {
	return r.leftSidebar.FilterQuery()
}

// TestGetLeftSidebar returns the left sidebar for testing
func (r *Run) TestGetLeftSidebar() *RunOverviewSidebar {
	return r.leftSidebar
}

// TestHandleRecordMsg processes a record message
func (r *Run) TestHandleRecordMsg(msg tea.Msg) (*Run, tea.Cmd) {
	return r.handleRecordMsg(msg)
}

// TestHandleChartGridClick handles a click on the main chart grid
func (r *Run) TestHandleChartGridClick(row, col int) {
	r.metricsGrid.HandleClick(row, col)
}

// TestSetMainChartFocus sets focus to a main chart
func (r *Run) TestSetMainChartFocus(row, col int) {
	r.metricsGrid.setFocus(row, col)
}

// TestClearMainChartFocus clears focus from main charts
func (r *Run) TestClearMainChartFocus() {
	r.metricsGrid.clearFocus()
}

// TestForceExpand forces the sidebar to expanded state without animation
func (s *RunOverviewSidebar) TestForceExpand() {
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

// ---- Workspace test helpers ----

func (w *Workspace) TestSelectedRunCount() int {
	return len(w.selectedRuns)
}

func (w *Workspace) TestIsRunSelected(runKey string) bool {
	return w.selectedRuns[runKey]
}

func (w *Workspace) TestPinnedRun() string {
	return w.pinnedRun
}

func (w *Workspace) TestCurrentRunKey() string {
	cur, ok := w.runs.CurrentItem()
	if !ok {
		return ""
	}
	return cur.Key
}

func (w *Workspace) TestRunOverviewPreloadsInFlight() int {
	return len(w.overviewPreloader.inFlight)
}

func (w *Workspace) TestRunOverviewPreloadQueueLen() int {
	return len(w.overviewPreloader.queue)
}

func (w *Workspace) TestRunOverviewID(runKey string) string {
	ro := w.runOverview[runKey]
	if ro == nil {
		return ""
	}
	return ro.runID
}
