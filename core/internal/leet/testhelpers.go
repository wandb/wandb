// Test<API> provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

import (
	"math"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observability"
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

// TestSeriesCount returns the number of named (non-default) series in the chart.
func (c *TimeSeriesLineChart) TestSeriesCount() int {
	return len(c.series)
}

// TestSeriesColor returns the configured color for a series key.
func (c *TimeSeriesLineChart) TestSeriesColor(key string) compat.AdaptiveColor {
	return c.seriesColors[key]
}

// TestViewRange returns the current X view range.
func (c *TimeSeriesLineChart) TestViewRange() (minX, maxX float64) {
	return c.ViewMinX(), c.ViewMaxX()
}

// TestAutoTrail reports whether the chart is currently auto-trailing live updates.
func (c *TimeSeriesLineChart) TestAutoTrail() bool {
	return c.autoTrail
}

// TestShowAll reports whether the chart is currently showing the full history.
func (c *TimeSeriesLineChart) TestShowAll() bool {
	return c.showAll
}

// TestFormatXAxisTick exposes system-metric X tick formatting for focused tests.
func (c *TimeSeriesLineChart) TestFormatXAxisTick(v float64, maxWidth int) string {
	return c.formatXAxisTick(v, maxWidth)
}

// TestSampleCount exposes the buffered sample-column count for focused tests.
func (c *FrenchFriesChart) TestSampleCount() int {
	return len(c.samples)
}

// TestVisibleSeries exposes the series currently rendered as rows.
func (c *FrenchFriesChart) TestVisibleSeries() []string {
	layout := c.layout()
	names := make([]string, 0, len(layout.bands))
	for _, band := range layout.bands {
		names = append(names, band.seriesName)
	}
	return names
}

// TestTitleDetail exposes the rendered title suffix for focused tests.
func (c *FrenchFriesChart) TestTitleDetail() string {
	return c.TitleDetail()
}

// TestColorForValue exposes the rendered cell selected for a value.
func (c *FrenchFriesChart) TestColorForValue(value float64) string {
	return c.colorForValue(value)
}

// TestBucketValues returns the averaged bucket value per column for a series.
// Missing buckets are returned as NaN.
func (c *FrenchFriesChart) TestBucketValues(seriesName string) []float64 {
	layout := c.layout()
	bucketed := c.bucketedSeries(layout)
	cells := bucketed[seriesName]
	out := make([]float64, len(cells))
	for i, cell := range cells {
		if cell.ok {
			out[i] = cell.value
		} else {
			out[i] = math.NaN()
		}
	}
	return out
}

// TestCurrentPage returns the current grid of charts.
func (g *SystemMetricsGrid) TestCurrentPage() [][]*TimeSeriesLineChart {
	out := make([][]*TimeSeriesLineChart, len(g.currentPage))
	for row := range g.currentPage {
		out[row] = make([]*TimeSeriesLineChart, len(g.currentPage[row]))
		for col := range g.currentPage[row] {
			if chart, ok := g.currentPage[row][col].(*TimeSeriesLineChart); ok {
				out[row][col] = chart
			}
		}
	}
	return out
}

// TestChartAt returns the underlying line chart at (row, col) on the current page (or nil).
func (g *SystemMetricsGrid) TestChartAt(row, col int) *TimeSeriesLineChart {
	if row < 0 || row >= len(g.currentPage) ||
		col < 0 || col >= len(g.currentPage[row]) {
		return nil
	}
	switch chart := g.currentPage[row][col].(type) {
	case *TimeSeriesLineChart:
		return chart
	case *frenchFriesToggleChart:
		return chart.line
	default:
		return nil
	}
}

// TestFrenchFriesChartAt returns the French Fries chart at (row, col) on the current page (or nil).
func (g *SystemMetricsGrid) TestFrenchFriesChartAt(row, col int) *FrenchFriesChart {
	if row < 0 || row >= len(g.currentPage) ||
		col < 0 || col >= len(g.currentPage[row]) {
		return nil
	}
	switch chart := g.currentPage[row][col].(type) {
	case *FrenchFriesChart:
		return chart
	case *frenchFriesToggleChart:
		return chart.frenchFries
	default:
		return nil
	}
}

// TestHeatmapModeAt reports whether the chart at (row, col) is in heatmap mode.
func (g *SystemMetricsGrid) TestHeatmapModeAt(row, col int) bool {
	if row < 0 || row >= len(g.currentPage) ||
		col < 0 || col >= len(g.currentPage[row]) {
		return false
	}
	chart := g.currentPage[row][col]
	if chart == nil {
		return false
	}
	return chart.IsHeatmapMode()
}

// TestToggleFocusedChartHeatmapMode toggles heatmap mode on the focused system chart.
func (g *SystemMetricsGrid) TestToggleFocusedChartHeatmapMode() bool {
	return g.toggleFocusedChartHeatmapMode()
}

// TestGridDims returns the current grid dimensions.
func (g *SystemMetricsGrid) TestGridDims() GridDims {
	return g.calculateChartDimensions()
}

// TestSyncInspectActive exposes the synchronized inspection flag for tests.
func (g *SystemMetricsGrid) TestSyncInspectActive() bool {
	return g.syncInspectActive
}

// TestToggleFocusedChartLogY toggles log Y on the focused system chart.
func (g *SystemMetricsGrid) TestToggleFocusedChartLogY() bool {
	return g.toggleFocusedChartLogY()
}

// TestCycleFocusedChartMode advances the focused system chart through its modes.
func (g *SystemMetricsGrid) TestCycleFocusedChartMode() bool {
	return g.cycleFocusedChartMode()
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

// TestIsLogY reports whether the chart is using logarithmic Y scaling.
func (c *EpochLineChart) TestIsLogY() bool {
	return c.IsLogY()
}

// TestFormatYTick exposes Y-axis label formatting for focused tests.
func (c *EpochLineChart) TestFormatYTick(v float64) string {
	return c.formatYTick(v)
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

// TestToggleFocusedChartLogY toggles log Y on the focused main chart.
func (mg *MetricsGrid) TestToggleFocusedChartLogY() bool {
	return mg.toggleFocusedChartLogY()
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

// TestExtractRunID exposes extractRunID for external tests.
func TestExtractRunID(runKey string) string {
	return extractRunID(runKey)
}

func (w *Workspace) TestRunOverviewID(runKey string) string {
	ro := w.runOverview[runKey]
	if ro == nil {
		return ""
	}
	return ro.runID
}

// TestRunOverviewProject returns the project for a given run key
func (w *Workspace) TestGetRunOverviewByRunKey(runKey string) *RunOverview {
	ro := w.runOverview[runKey]
	if ro == nil {
		return nil
	}
	return ro
}

// TestExecutePreloadCmd calls the preload command for a given run key
// and returns the resulting message.
func (w *Workspace) TestExecutePreloadCmd(runKey string) WorkspaceRunOverviewPreloadedMsg {
	cmd := w.backend.PreloadOverviewCmd(runKey)
	msg := cmd()
	return msg.(WorkspaceRunOverviewPreloadedMsg)
}

// ---- Run bottom bar / sidebar test helpers ----

// TestConsoleLogsPaneActive reports whether the bottom bar has focus.
func (r *Run) TestConsoleLogsPaneActive() bool {
	return r.consoleLogsPane.Active()
}

// TestConsoleLogsPaneExpanded reports whether the bottom bar is fully expanded.
func (r *Run) TestConsoleLogsPaneExpanded() bool {
	return r.consoleLogsPane.IsExpanded()
}

// TestLeftSidebarActiveSectionIdx returns the active section index.
func (r *Run) TestLeftSidebarActiveSectionIdx() int {
	return r.leftSidebar.activeSection
}

// TestLeftSidebarHasActiveSection reports whether any section has focus.
func (r *Run) TestLeftSidebarHasActiveSection() bool {
	return r.leftSidebar.hasActiveSection()
}

// TestForceExpandConsoleLogsPane instantly expands the bottom bar to height h.
func (r *Run) TestForceExpandConsoleLogsPane(h int) {
	r.consoleLogsPane.SetExpandedHeight(h)
	r.consoleLogsPane.animState.ForceExpand()
}

// TestForceExpandLeftSidebar instantly expands the left sidebar.
func (r *Run) TestForceExpandLeftSidebar() {
	r.leftSidebar.animState.ForceExpand()
}

// TestForceCollapseLeftSidebar instantly collapses the left sidebar.
func (r *Run) TestForceCollapseLeftSidebar() {
	r.leftSidebar.animState.ForceCollapse()
}

// TestSetFocusTarget sets the focus manager's current target for testing.
func (r *Run) TestSetFocusTarget(target int) {
	r.focusMgr.SetTarget(FocusTarget(target), 1)
}

// ---- Workspace bottom bar / focus test helpers ----

// TestConsoleLogsPaneActive reports whether the workspace bottom bar has focus.
func (w *Workspace) TestConsoleLogsPaneActive() bool {
	return w.consoleLogsPane.Active()
}

// TestConsoleLogsPaneExpanded reports whether the workspace bottom bar is expanded.
func (w *Workspace) TestConsoleLogsPaneExpanded() bool {
	return w.consoleLogsPane.IsExpanded()
}

// TestRunsActive reports whether the runs list has focus.
func (w *Workspace) TestRunsActive() bool {
	return w.runs.Active
}

// TestCurrentFocusRegion returns the current focus region as an int.
// Maps to the FocusTarget enum values from focusmanager.go.
func (w *Workspace) TestCurrentFocusRegion() int {
	return int(w.focusMgr.Current())
}

// TestForceExpandConsoleLogsPane instantly expands the workspace bottom bar.
func (w *Workspace) TestForceExpandConsoleLogsPane(h int) {
	w.consoleLogsPane.SetExpandedHeight(h)
	w.consoleLogsPane.animState.ForceExpand()
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
	contentH := max(w.height-StatusBarHeight, 0)
	_ = w.runOverviewSidebar.View(contentH)
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

// TestOverviewFilterMode reports whether the overview sidebar is in filter input mode.
func (w *Workspace) TestOverviewFilterMode() bool {
	return w.runOverviewSidebar.IsFilterMode()
}

// TestOverviewFiltering reports whether an applied (non-empty) overview filter exists.
func (w *Workspace) TestOverviewFiltering() bool {
	return w.runOverviewSidebar.IsFiltering()
}

// TestOverviewFilterQuery returns the current overview filter query string.
func (w *Workspace) TestOverviewFilterQuery() string {
	return w.runOverviewSidebar.FilterQuery()
}

// TestOverviewFilterInfo returns the compact match summary for the overview filter.
func (w *Workspace) TestOverviewFilterInfo() string {
	return w.runOverviewSidebar.FilterInfo()
}

// TestRunsFilterMode reports whether the runs sidebar filter is in input mode.
func (w *Workspace) TestRunsFilterMode() bool {
	return w.filter.IsActive()
}

// TestRunsFiltering reports whether an applied runs filter exists.
func (w *Workspace) TestRunsFiltering() bool {
	return !w.filter.IsActive() && w.filter.Query() != ""
}

// TestRunsFilterQuery returns the current runs filter query.
func (w *Workspace) TestRunsFilterQuery() string {
	return w.filter.Query()
}

// TestFilteredRunKeys returns the currently visible run keys in sidebar order.
func (w *Workspace) TestFilteredRunKeys() []string {
	keys := make([]string, len(w.runs.FilteredItems))
	for i, item := range w.runs.FilteredItems {
		keys[i] = item.Key
	}
	return keys
}

// TestRemoteWorkspaceBackend creates a RemoteWorkspaceBackend for testing.
func TestRemoteWorkspaceBackend(
	baseURL, entity, project string,
	graphqlClient graphql.Client,
	httpClient api.RetryableClient,
	logger *observability.CoreLogger,
) *RemoteWorkspaceBackend {
	return &RemoteWorkspaceBackend{
		baseURL:       baseURL,
		entity:        entity,
		project:       project,
		runInfos:      make(map[string]*RunInfo),
		logger:        logger,
		graphqlClient: graphqlClient,
		httpClient:    httpClient,
	}
}
