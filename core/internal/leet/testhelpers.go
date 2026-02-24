// Test<API> provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	s.animState.current = s.animState.expanded
	s.animState.target = s.animState.expanded
	s.animState.startTime = time.Now().Add(-AnimationDuration)
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

// TestBounds exposes the chart's current bounds for testing.
func (c *EpochLineChart) TestBounds() (xMin, xMax, yMin, yMax float64) {
	return c.xMin, c.xMax, c.yMin, c.yMax
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

// ---- Run bottom bar / sidebar test helpers ----

// TestBottomBarActive reports whether the bottom bar has focus.
func (r *Run) TestBottomBarActive() bool {
	return r.bottomBar.Active()
}

// TestBottomBarExpanded reports whether the bottom bar is fully expanded.
func (r *Run) TestBottomBarExpanded() bool {
	return r.bottomBar.IsExpanded()
}

// TestLeftSidebarActiveSectionIdx returns the active section index.
func (r *Run) TestLeftSidebarActiveSectionIdx() int {
	return r.leftSidebar.activeSection
}

// TestLeftSidebarHasActiveSection reports whether any section has focus.
func (r *Run) TestLeftSidebarHasActiveSection() bool {
	return r.leftSidebar.hasActiveSection()
}

// TestForceExpandBottomBar instantly expands the bottom bar to height h.
func (r *Run) TestForceExpandBottomBar(h int) {
	r.bottomBar.SetExpandedHeight(h)
	r.bottomBar.animState.ForceExpand()
}

// TestForceExpandLeftSidebar instantly expands the left sidebar.
func (r *Run) TestForceExpandLeftSidebar() {
	r.leftSidebar.animState.ForceExpand()
}

// TestForceCollapseLeftSidebar instantly collapses the left sidebar.
func (r *Run) TestForceCollapseLeftSidebar() {
	r.leftSidebar.animState.ForceCollapse()
}

// ---- Workspace bottom bar / focus test helpers ----

// TestBottomBarActive reports whether the workspace bottom bar has focus.
func (w *Workspace) TestBottomBarActive() bool {
	return w.bottomBar.Active()
}

// TestBottomBarExpanded reports whether the workspace bottom bar is expanded.
func (w *Workspace) TestBottomBarExpanded() bool {
	return w.bottomBar.IsExpanded()
}

// TestRunsActive reports whether the runs list has focus.
func (w *Workspace) TestRunsActive() bool {
	return w.runs.Active
}

// TestCurrentFocusRegion returns the current focus region as an int.
// Maps to the focusRegion enum: 0=focusRuns, 1=focusLogs, 2=focusOverview.
func (w *Workspace) TestCurrentFocusRegion() int {
	return int(w.currentFocusRegion())
}

// TestForceExpandBottomBar instantly expands the workspace bottom bar.
func (w *Workspace) TestForceExpandBottomBar(h int) {
	w.bottomBar.SetExpandedHeight(h)
	w.bottomBar.animState.ForceExpand()
}

// TestForceCollapseOverviewSidebar instantly collapses the overview sidebar.
func (w *Workspace) TestForceCollapseOverviewSidebar() {
	w.runOverviewSidebar.animState.ForceCollapse()
}

// TestForceExpandOverviewSidebar instantly expands the overview sidebar.
func (w *Workspace) TestForceExpandOverviewSidebar() {
	w.runOverviewSidebar.animState.ForceExpand()
}

// TestForceCollapseRunsSidebar instantly collapses the runs sidebar.
func (w *Workspace) TestForceCollapseRunsSidebar() {
	w.runsAnimState.ForceCollapse()
}

// TestForceExpandRunsSidebar instantly expands the runs sidebar.
func (w *Workspace) TestForceExpandRunsSidebar() {
	w.runsAnimState.ForceExpand()
}

// TestConsoleLogs returns the console logs map for assertion.
func (w *Workspace) TestConsoleLogs() map[string]*RunConsoleLogs {
	return w.consoleLogs
}

// TestRunOverviewSidebarHasActiveSection reports whether the overview sidebar
// has an active section.
func (w *Workspace) TestRunOverviewSidebarHasActiveSection() bool {
	return w.runOverviewSidebar.hasActiveSection()
}

// TestFocusableSectionBounds exposes the sidebar's focusable section range.
func (s *RunOverviewSidebar) TestFocusableSectionBounds() (first, last int) {
	return s.focusableSectionBounds()
}

// TestSeedRunOverview populates the workspace's overview data for the given
// run key with sample config, summary, and environment items, then syncs the
// sidebar so that overview sections become focusable.
//
// This mirrors the data-seeding pattern used by Run-level handler tests
// (e.g. newRunForHandlerTest) and is required whenever a test needs to Tab
// into the overview region.
func (w *Workspace) TestSeedRunOverview(runKey string) {
	ro := NewRunOverview()
	ro.ProcessRunMsg(RunMsg{
		ID:      "test-id",
		Project: "test-project",
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.01"},
				{NestedKey: []string{"epochs"}, ValueJson: "10"},
			},
		},
	})
	ro.ProcessSummaryMsg([]*spb.SummaryRecord{{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.42"},
		},
	}})
	ro.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "w1",
		Os:       "linux",
	})

	w.runOverview[runKey] = ro
	w.runOverviewSidebar.SetRunOverview(ro)
	w.runOverviewSidebar.Sync()

	// Trigger section height calculation so ItemsPerPage > 0.
	sidebarH := max(w.height-StatusBarHeight, 0)
	innerH := max(sidebarH-workspaceTopMarginLines, 0)
	_ = w.runOverviewSidebar.View(innerH)
}

// SystemMetricsPaneMinHeight returns the minimum pane height (for testing).
func SystemMetricsPaneMinHeight() int {
	return systemMetricsPaneMinHeight
}

// TestForceExpandSystemMetricsPane instantly expands the system metrics pane.
func (w *Workspace) TestForceExpandSystemMetricsPane(h int) {
	w.systemMetricsPane.SetExpandedHeight(h)
	w.systemMetricsPane.animState.ForceExpand()
}

// TestForceCollapseSystemMetricsPane instantly collapses the system metrics pane.
func (w *Workspace) TestForceCollapseSystemMetricsPane() {
	w.systemMetricsPane.animState.ForceCollapse()
}

// TestSystemMetricsPane returns the system metrics pane for testing.
func (w *Workspace) TestSystemMetricsPane() *SystemMetricsPane {
	return w.systemMetricsPane
}

// TestSystemMetrics returns the system metrics grids map for testing.
func (w *Workspace) TestSystemMetrics() map[string]*SystemMetricsGrid {
	return w.systemMetrics
}

// TestFocus returns the workspace focus state for testing.
func (w *Workspace) TestFocus() *Focus {
	return w.focus
}
