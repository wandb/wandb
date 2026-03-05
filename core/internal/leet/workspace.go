package leet

import (
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	RunMark         = "○"
	SelectedRunMark = "●"
	PinnedRunMark   = "▶" // ✪ ◎ ▲ ▶ ◉ ▬ ◆ ▣ ■ → ○ ●
)

// Workspace is the multi‑run view.
//
// Implements tea.Model.
type Workspace struct {
	wandbDir string

	// Configuration and key bindings.
	config *ConfigManager
	keyMap map[string]func(*Workspace, tea.KeyMsg) tea.Cmd

	// Runs sidebar animation state.
	runsAnimState *AnimatedValue

	// runs is the run selector.
	runs         PagedList
	selectedRuns map[string]bool // runDirName -> selected
	pinnedRun    string          // runDirName or ""

	// hasLiveRuns caches whether any selected run is in RunStateRunning.
	hasLiveRuns atomic.Bool

	// Run overview for each run keyed by run path.
	runOverview        map[string]*RunOverview
	runOverviewSidebar *RunOverviewSidebar

	// Run overview preload pipeline for unselected runs.
	overviewPreloader runOverviewPreloader

	// autoSelectLatestRunOnLoad is triggered when at least one run
	// appears in the workspace.
	autoSelectLatestRunOnLoad sync.Once

	// TODO: mark live runs upon selection.

	// TODO: filter for the run selector.
	// TODO: allow filtering by run properties, e.g. projects or tags.
	filter *Filter

	// Multi‑run metrics state.
	focus       *Focus
	metricsGrid *MetricsGrid

	// System metrics
	systemMetrics       map[string]*SystemMetricsGrid
	systemMetricsPane   *SystemMetricsPane
	systemMetricsFocus  *Focus
	systemMetricsFilter *Filter

	// Run console logs keyed by run path.
	consoleLogs     map[string]*RunConsoleLogs
	consoleLogsPane *ConsoleLogsPane

	// Per‑run streaming state keyed by runDirName.
	runsByKey map[string]*workspaceRun

	// Heartbeat for live runs.
	liveChan     chan tea.Msg
	heartbeatMgr *HeartbeatManager

	logger *observability.CoreLogger

	width, height int
}

// workspaceRun holds per‑run state for the workspace multi‑run view.
type workspaceRun struct {
	key       string
	wandbPath string
	reader    *WandbReader
	watcher   *WatcherManager
	state     RunState
}

func NewWorkspace(
	wandbDir string,
	cfg *ConfigManager,
	logger *observability.CoreLogger,
) *Workspace {
	logger.Info(fmt.Sprintf("workspace: creating new workspace for wandbDir: %s", wandbDir))

	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	// TODO: refactor to allow non-KeyValue items + make filtered ones pointers
	runs := PagedList{
		Title:  "Runs",
		Active: true,
	}
	runs.SetItemsPerPage(1)

	focus := NewFocus()

	smf := NewFilter()

	// Heartbeat for all live workspace runs shares a single channel.
	ch := make(chan tea.Msg, 4096)
	hbInterval := cfg.HeartbeatInterval()
	logger.Info(fmt.Sprintf("workspace: heartbeat interval set to %v", hbInterval))

	runOverviewAnimState := NewAnimatedValue(true, SidebarMinWidth)

	// TODO: make sidebar visibility configurable.
	return &Workspace{
		runsAnimState: NewAnimatedValue(true, SidebarMinWidth),
		wandbDir:      wandbDir,
		config:        cfg,
		keyMap:        buildKeyMap(WorkspaceKeyBindings()),
		logger:        logger,
		runs:          runs,
		runOverview:   make(map[string]*RunOverview),
		runOverviewSidebar: NewRunOverviewSidebar(
			runOverviewAnimState, NewRunOverview(), SidebarSideRight),
		overviewPreloader:   newRunOverviewPreloader(maxConcurrentPreloads),
		selectedRuns:        make(map[string]bool),
		focus:               focus,
		metricsGrid:         NewMetricsGrid(cfg, cfg.WorkspaceMetricsGrid, focus, logger),
		systemMetrics:       make(map[string]*SystemMetricsGrid),
		systemMetricsPane:   NewSystemMetricsPane(),
		systemMetricsFocus:  focus,
		systemMetricsFilter: smf,
		consoleLogs:         make(map[string]*RunConsoleLogs),
		consoleLogsPane:     NewConsoleLogsPane(),
		runsByKey:           make(map[string]*workspaceRun),
		liveChan:            ch,
		heartbeatMgr:        NewHeartbeatManager(hbInterval, ch, logger),
		filter:              NewFilter(),
	}
}

// SetSize updates the workspace dimensions and recomputes pagination capacity.
func (w *Workspace) SetSize(width, height int) {
	w.width, w.height = width, height

	// The runs list lives in the main content area (above the status bar).
	contentHeight := max(height-StatusBarHeight, 0)
	available := max(contentHeight-workspaceTopMarginLines-workspaceHeaderLines, 1)

	w.runs.SetItemsPerPage(available)
}

// Init wires up long‑running commands for the workspace.
func (w *Workspace) Init() tea.Cmd {
	var cmds []tea.Cmd

	// Start polling immediately; subsequent polls are scheduled by the handler.
	cmds = append(cmds, w.pollWandbDirCmd(0))

	// Start listening; the heartbeat manager will decide when to emit.
	if w.heartbeatMgr != nil && w.liveChan != nil {
		cmds = append(cmds, w.waitForLiveMsg)
	}

	return tea.Batch(cmds...)
}

func (w *Workspace) Update(msg tea.Msg) tea.Cmd {
	switch t := msg.(type) {
	case tea.WindowSizeMsg:
		w.handleWindowResize(t.Width, t.Height)

	case tea.KeyMsg:
		return w.handleKeyMsg(t)

	case tea.MouseMsg:
		return w.handleMouse(t)

	case WorkspaceRunsAnimationMsg:
		return w.handleRunsAnimation()

	case WorkspaceRunOverviewAnimationMsg:
		return w.handleRunOverviewAnimation()

	case WorkspaceConsoleLogsPaneAnimationMsg:
		return w.handleConsoleLogsPaneAnimation()

	case WorkspaceSystemMetricsPaneAnimationMsg:
		return w.handleSystemMetricsPaneAnimation(time.Now())

	case WorkspaceRunInitMsg:
		return w.handleWorkspaceRunInit(t)

	case WorkspaceInitErrMsg:
		return w.handleWorkspaceInitErr(t)

	case WorkspaceRunDirsMsg:
		return w.handleWorkspaceRunDirs(t)

	case WorkspaceRunOverviewPreloadedMsg:
		return w.handleWorkspaceRunOverviewPreloaded(t)

	case WorkspaceChunkedBatchMsg:
		return w.handleWorkspaceChunkedBatch(t)

	case WorkspaceBatchedRecordsMsg:
		return w.handleWorkspaceBatchedRecords(t)

	case WorkspaceFileChangedMsg:
		return w.handleWorkspaceFileChanged(t)

	case HeartbeatMsg:
		return w.handleHeartbeat()
	}

	return nil
}

// View renders the runs section: header + paginated list with zebra rows.
func (w *Workspace) View() string {
	var cols []string

	if w.runsAnimState.IsVisible() {
		cols = append(cols, w.renderRunsList())
	}

	centralColumn := w.renderMetrics()

	contentWidth := max(w.width-w.runsAnimState.Value()-w.runOverviewSidebar.Width(), 0)
	var runLabel string
	var hint string

	if w.systemMetricsPane.IsVisible() {
		var grid *SystemMetricsGrid

		if cur, ok := w.runs.CurrentItem(); ok {
			runLabel = cur.Key
			grid = w.systemMetrics[cur.Key]
			if _, selected := w.selectedRuns[cur.Key]; !selected {
				hint = "Select this run (Space) to load system metrics."
			}
		}

		smView := w.systemMetricsPane.View(contentWidth, runLabel, grid, hint)
		centralColumn = lipgloss.JoinVertical(lipgloss.Left, centralColumn, smView)
	}

	if w.consoleLogsPane.IsVisible() {
		if cur, ok := w.runs.CurrentItem(); ok {
			runLabel = cur.Key
			if cl := w.consoleLogs[cur.Key]; cl != nil {
				w.consoleLogsPane.SetConsoleLogs(cl.Items())
			} else {
				w.consoleLogsPane.SetConsoleLogs(nil)
			}
			if _, selected := w.selectedRuns[cur.Key]; !selected {
				hint = "Select this run (Space) to load console logs."
			}
		}
		bbView := w.consoleLogsPane.View(contentWidth, runLabel, hint)
		centralColumn = lipgloss.JoinVertical(lipgloss.Left, centralColumn, bbView)
	}
	cols = append(cols, centralColumn)

	if w.runOverviewSidebar.IsVisible() {
		cols = append(cols, w.renderRunOverview())
	}

	mainView := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	statusBar := w.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(w.width, w.height, lipgloss.Left, lipgloss.Top, fullView)
}

// IsFiltering reports whether any workspace-level filter UI is active.
func (w *Workspace) IsFiltering() bool {
	if w.metricsGrid.IsFilterMode() ||
		w.runOverviewSidebar.IsFilterMode() ||
		w.filter.IsActive() {
		return true
	}
	if g := w.activeSystemMetricsGrid(); g != nil && g.IsFilterMode() {
		return true
	}
	return false
}

// SelectedRunWandbFile returns the full path to the .wandb file for the selected run.
//
// Returns empty string if no run is selected.
func (w *Workspace) SelectedRunWandbFile() string {
	total := len(w.runs.FilteredItems)
	if total == 0 {
		return ""
	}

	startIdx := w.runs.CurrentPage() * w.runs.ItemsPerPage()
	idx := startIdx + w.runs.CurrentLine()
	if idx < 0 || idx >= total {
		return ""
	}

	return runWandbFile(w.wandbDir, w.runs.FilteredItems[idx].Key)
}

// ---- Layout & Sidebar Helpers ----

// recalculateLayout recomputes viewports and pushes dimensions to the metrics
// grid. Call after any change that affects available content area (sidebar
// toggle, window resize, animation tick).
func (w *Workspace) recalculateLayout() {
	layout := w.computeViewports()
	w.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)
}

// computeViewports returns the computed layout dimensions.
func (w *Workspace) computeViewports() Layout {
	leftW, rightW := w.runsAnimState.Value(), w.runOverviewSidebar.Width()

	contentW := max(w.width-leftW-rightW, 1)
	reserved := w.consoleLogsPane.Height() + w.systemMetricsPane.Height()
	contentH := max(w.height-StatusBarHeight-reserved, 1)

	return Layout{leftW, contentW, rightW, contentH}
}

// updateSidebarDimensions tells both sidebars to recalculate their expanded
// widths given the post-toggle visibility of each side.
func (w *Workspace) updateSidebarDimensions(leftVisible, rightVisible bool) {
	var leftWidth int
	if rightVisible {
		leftWidth = int(float64(w.width) * SidebarWidthRatioBoth)
	} else {
		leftWidth = int(float64(w.width) * SidebarWidthRatio)
	}
	w.runsAnimState.SetExpanded(clamp(leftWidth, SidebarMinWidth, SidebarMaxWidth))
	w.runOverviewSidebar.UpdateDimensions(w.width, leftVisible)
}

func (w *Workspace) updateMiddlePaneHeights(sysVisible, logsVisible bool) {
	maxH := max(w.height-StatusBarHeight, 0)

	if sysVisible && logsVisible {
		each := int(float64(maxH) * SidebarWidthRatioBoth) // 0.236
		w.systemMetricsPane.SetExpandedHeight(each)
		w.consoleLogsPane.SetExpandedHeight(each)
		return
	}

	h := int(float64(maxH) * ConsoleLogsPaneHeightRatio) // 0.382
	if sysVisible {
		w.systemMetricsPane.SetExpandedHeight(h)
	}
	if logsVisible {
		w.consoleLogsPane.SetExpandedHeight(h)
	}
}

// resolveFocusAfterVisibilityChange ensures focus stays on a valid region
// after a panel visibility change.
//
// If the currently focused region will remain available, focus is left
// unchanged. Otherwise it advances to the next available region.
func (w *Workspace) resolveFocusAfterVisibilityChange(
	leftVisible, rightVisible, bottomVisible bool) {
	cur := w.currentFocusRegion()

	// Build the future availability map from the post-toggle state.
	firstSec, _ := w.runOverviewSidebar.focusableSectionBounds()
	avail := map[focusRegion]bool{
		focusRuns:     leftVisible,
		focusLogs:     bottomVisible,
		focusOverview: rightVisible && firstSec != -1,
	}

	if avail[cur] {
		return
	}

	// Current region is being collapsed — find the next available one.
	curIdx := 0
	for i, v := range focusOrder {
		if v == cur {
			curIdx = i
			break
		}
	}

	n := len(focusOrder)
	for step := 1; step <= n; step++ {
		nextIdx := ((curIdx + step) % n)
		next := focusOrder[nextIdx]
		if avail[next] {
			w.setFocusRegion(next, 1)
			return
		}
	}

	// Nothing available — default to runs (it will show inactive styling).
	w.setFocusRegion(focusRuns, 1)
}

// handleWindowResize handles window resize messages.
func (w *Workspace) handleWindowResize(width, height int) {
	w.SetSize(width, height)
	w.updateSidebarDimensions(w.runsAnimState.IsVisible(), w.runOverviewSidebar.IsVisible())
	w.updateMiddlePaneHeights(w.systemMetricsPane.IsVisible(), w.consoleLogsPane.IsVisible())
	w.recalculateLayout()
}

// runsAnimationCmd returns a command to continue the animation on section toggle.
func (w *Workspace) runsAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return WorkspaceRunsAnimationMsg{}
	})
}

// runOverviewAnimationCmd returns a command to continue the animation on section toggle.
func (w *Workspace) runOverviewAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return WorkspaceRunOverviewAnimationMsg{}
	})
}

func (w *Workspace) consoleLogsPaneAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return WorkspaceConsoleLogsPaneAnimationMsg{}
	})
}

func (w *Workspace) systemMetricsPaneAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return WorkspaceSystemMetricsPaneAnimationMsg{}
	})
}

// ---- Run State Helpers ----

// anyRunRunning reports whether any selected run is currently live.
func (w *Workspace) anyRunRunning() bool {
	for key, run := range w.runsByKey {
		if run != nil && run.state == RunStateRunning && w.selectedRuns[key] {
			return true
		}
	}
	return false
}

// syncLiveRunState updates the atomic liveness flag from the authoritative map state.
//
// Must be called on the main (Update) goroutine after any change to:
//   - runsByKey entries (add/remove/state change)
//   - selectedRuns entries (add/remove)
//
// The stored value is read by the HeartbeatManager's timer goroutine.
func (w *Workspace) syncLiveRunState() {
	w.hasLiveRuns.Store(w.anyRunRunning())
}

func (w *Workspace) dropRun(runKey string) {
	delete(w.selectedRuns, runKey)

	// If we removed the pinned run, unpin it.
	if w.pinnedRun == runKey {
		w.pinnedRun = ""
	}

	run, ok := w.runsByKey[runKey]
	if ok && run != nil {
		if run.wandbPath != "" {
			w.metricsGrid.RemoveSeries(run.wandbPath)
		}
		w.stopWatcher(run)
		if run.reader != nil {
			run.reader.Close()
		}
		delete(w.runsByKey, runKey)
		delete(w.consoleLogs, runKey)
		delete(w.systemMetrics, runKey)
	}

	w.syncLiveRunState()

	if w.heartbeatMgr != nil && !w.anyRunRunning() {
		w.heartbeatMgr.Stop()
	}
}

// getOrCreateRunOverview returns the RunOverview for the given key, creating one if needed.
func (w *Workspace) getOrCreateRunOverview(runKey string) *RunOverview {
	ro := w.runOverview[runKey]
	if ro != nil {
		return ro
	}
	ro = NewRunOverview()
	w.runOverview[runKey] = ro
	return ro
}

// getOrCreateConsoleLogs returns the RunConsoleLogs for the given key,
// creating one if needed.
func (w *Workspace) getOrCreateConsoleLogs(runKey string) *RunConsoleLogs {
	cl := w.consoleLogs[runKey]
	if cl != nil {
		return cl
	}
	cl = NewRunConsoleLogs()
	w.consoleLogs[runKey] = cl
	return cl
}

func (w *Workspace) getOrCreateSystemMetricsGrid(runKey string) *SystemMetricsGrid {
	if g := w.systemMetrics[runKey]; g != nil {
		return g
	}

	rows, cols := w.config.SystemGrid()
	initW := MinMetricChartWidth * cols
	initH := MinMetricChartHeight * rows

	g := NewSystemMetricsGrid(
		initW, initH,
		w.config, w.config.WorkspaceSystemGrid,
		w.systemMetricsFocus,
		w.systemMetricsFilter,
		w.logger)
	w.systemMetrics[runKey] = g
	return g
}

// refreshPinnedRun ensures the pinned run (if any) is drawn on top in all charts.
func (w *Workspace) refreshPinnedRun() {
	if w.pinnedRun == "" {
		return
	}
	run, ok := w.runsByKey[w.pinnedRun]
	if !ok || run == nil || run.wandbPath == "" {
		return
	}
	w.metricsGrid.PromoteSeriesToTop(run.wandbPath)
}

// ---- Focus Query Helpers ----

func (w *Workspace) runSelectorActive() bool {
	return w.runs.Active &&
		!w.consoleLogsPane.Active() &&
		w.runsAnimState.IsVisible() &&
		len(w.runs.FilteredItems) > 0
}

// RunSelectorActive reports whether the runs list sidebar is focused,
// visible, and has items. Used by the top-level Model to gate Enter
// (switch to single-run view) so it only fires when the run list owns focus.
func (w *Workspace) RunSelectorActive() bool {
	return w.runSelectorActive()
}

func (w *Workspace) runOverviewActive() bool {
	return !w.runs.Active && !w.consoleLogsPane.Active() && w.runOverviewSidebar.IsVisible()
}

// ---- Rendering ----

func (w *Workspace) renderRunsList() string {
	startIdx, endIdx := w.syncRunsPage()

	sidebarW := w.runsAnimState.Value()
	sidebarH := max(w.height-StatusBarHeight, 0)
	if sidebarW <= 1 || sidebarH <= 1 {
		return ""
	}
	contentWidth := max(sidebarW-leftSidebarContentPadding, 1)

	lines := w.renderRunLines(contentWidth)

	if len(lines) == 0 {
		lines = []string{"No runs found."}
	}

	contentLines := make([]string, 0, 1+len(lines))
	contentLines = append(contentLines, w.renderRunsListHeader(startIdx, endIdx))
	contentLines = append(contentLines, lines...)
	content := strings.Join(contentLines, "\n")

	// The runs sidebar border provides 1 blank line of padding at the top and bottom.
	innerW := max(sidebarW-runsSidebarBorderCols, 0)
	innerH := max(sidebarH-workspaceTopMarginLines, 0)

	styledContent := leftSidebarStyle.
		Width(innerW).
		Height(innerH).
		MaxWidth(innerW).
		MaxHeight(innerH).
		Render(content)

	boxed := leftSidebarBorderStyle.Height(innerH + 1).MaxHeight(innerH + 1).Render(styledContent)
	return lipgloss.Place(sidebarW, sidebarH, lipgloss.Left, lipgloss.Top, boxed)
}

func (w *Workspace) renderRunOverview() string {
	curKey := ""
	if cur, ok := w.runs.CurrentItem(); ok {
		curKey = cur.Key
	}

	ro := w.runOverview[curKey]
	w.runOverviewSidebar.SetRunOverview(ro)
	w.runOverviewSidebar.Sync()

	if w.runOverviewActive() {
		w.runOverviewSidebar.activateSelection()
	} else {
		w.runOverviewSidebar.deactivateAllSections()
	}

	sidebarH := max(w.height-StatusBarHeight, 0)
	innerH := max(sidebarH-workspaceTopMarginLines, 0)

	return w.runOverviewSidebar.View(innerH)
}

func (w *Workspace) renderMetrics() string {
	contentWidth := max(w.width-w.runsAnimState.Value()-w.runOverviewSidebar.Width(), 0)
	reserved := w.consoleLogsPane.Height() + w.systemMetricsPane.Height()
	contentHeight := max(w.height-StatusBarHeight-reserved, 1)

	if contentWidth <= 0 || contentHeight <= 0 {
		return ""
	}

	// No runs selected: show the logo + spherical cow without any header.
	if len(w.selectedRuns) == 0 {
		artStyle := lipgloss.NewStyle().
			Foreground(colorHeading).
			Bold(true)

		logoContent := lipgloss.JoinVertical(
			lipgloss.Center,
			artStyle.Render(wandbArt),
			artStyle.Render(leetArt),
		)

		return lipgloss.Place(
			contentWidth,
			contentHeight,
			lipgloss.Center,
			lipgloss.Center,
			logoContent,
		)
	}

	// When we have selected runs, render the metrics grid.
	dims := w.metricsGrid.CalculateChartDimensions(contentWidth, contentHeight)
	return w.metricsGrid.View(dims)
}

func (w *Workspace) renderStatusBar() string {
	statusText := w.buildStatusText()
	helpText := w.buildHelpText()

	innerWidth := max(w.width-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(w.width).
		MaxWidth(w.width).
		Render(fullStatus)
}

func (w *Workspace) buildStatusText() string {
	// Metrics filter input mode has top priority.
	if w.metricsGrid.IsFilterMode() {
		return w.buildMetricsFilterStatus()
	}
	if g := w.activeSystemMetricsGrid(); g != nil && g.IsFilterMode() {
		return w.buildSystemMetricsFilterStatus(g)
	}
	if w.runOverviewSidebar.IsFilterMode() {
		return w.buildOverviewFilterStatus()
	}

	// Grid layout prompt (rows/cols) for metrics/system grids.
	if w.config != nil && w.config.IsAwaitingGridConfig() {
		return w.config.GridConfigStatus()
	}

	// When we add a run-filter input, it can be handled here similarly.
	return w.buildActiveStatus()
}

func (w *Workspace) buildMetricsFilterStatus() string {
	return fmt.Sprintf(
		"Filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		w.metricsGrid.FilterMode().String(),
		w.metricsGrid.FilterQuery(),
		string(mediumShadeBlock),
		w.metricsGrid.FilteredChartCount(),
		w.metricsGrid.ChartCount(),
	)
}

func (w *Workspace) buildSystemMetricsFilterStatus(grid *SystemMetricsGrid) string {
	if grid == nil || !w.systemMetricsPane.IsVisible() {
		return ""
	}
	return fmt.Sprintf(
		"System filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		grid.FilterMode().String(),
		grid.FilterQuery(),
		string(mediumShadeBlock),
		grid.FilteredChartCount(),
		grid.ChartCount(),
	)
}

func (w *Workspace) buildOverviewFilterStatus() string {
	filterInfo := w.runOverviewSidebar.FilterInfo()
	if filterInfo == "" {
		filterInfo = "no matches"
	}
	return fmt.Sprintf(
		"Overview filter (%s): %s%s [%s] (Enter to apply • Tab to toggle mode)",
		w.runOverviewSidebar.FilterMode().String(),
		w.runOverviewSidebar.FilterQuery(),
		string(mediumShadeBlock),
		filterInfo,
	)
}

// buildActiveStatus summarizes the active filters and selection when no
// dedicated input mode (filter / grid config) is active.
func (w *Workspace) buildActiveStatus() string {
	var parts []string

	if w.metricsGrid.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"Filter (%s): %q [%d/%d] (/ to change, ctrl+l to clear)",
			w.metricsGrid.FilterMode().String(),
			w.metricsGrid.FilterQuery(),
			w.metricsGrid.FilteredChartCount(),
			w.metricsGrid.ChartCount(),
		))
	}

	if g := w.activeSystemMetricsGrid(); g != nil &&
		g.IsFiltering() &&
		w.systemMetricsPane.IsVisible() {
		parts = append(parts, fmt.Sprintf(
			"System filter (%s): %q [%d/%d] (\\ to change, ctrl+\\ to clear)",
			g.FilterMode().String(),
			g.FilterQuery(),
			g.FilteredChartCount(),
			g.ChartCount(),
		))
	}

	if w.runOverviewSidebar.IsVisible() && w.runOverviewSidebar.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"Overview: %q [%s] (o to change, ctrl+k to clear)",
			w.runOverviewSidebar.FilterQuery(),
			w.runOverviewSidebar.FilterInfo(),
		))
	}

	if w.focus.Type != FocusNone {
		parts = append(parts, w.focus.Title)
	}

	if len(parts) == 0 {
		return w.wandbDir
	}
	return w.wandbDir + " • " + strings.Join(parts, " • ")
}

// buildHelpText builds the help text for the status bar.
func (w *Workspace) buildHelpText() string {
	// Hide help hint while any workspace-level filter / grid config is active.
	if w.IsFiltering() || w.config.IsAwaitingGridConfig() {
		return ""
	}
	return "h: help"
}

// syncRunsPage clamps the SectionView page/line against the current item set
// and returns the bounds of the visible slice [startIdx, endIdx).
func (w *Workspace) syncRunsPage() (startIdx, endIdx int) {
	total := len(w.runs.FilteredItems)
	itemsPerPage := w.runs.ItemsPerPage()

	if total == 0 || itemsPerPage <= 0 {
		w.runs.Home()
		return 0, 0
	}

	totalPages := (total + itemsPerPage - 1) / itemsPerPage
	if totalPages <= 0 {
		totalPages = 1
	}
	page := max(w.runs.CurrentPage(), 0)
	if page >= totalPages {
		page = totalPages - 1
	}

	startIdx = page * itemsPerPage
	endIdx = min(startIdx+itemsPerPage, total)

	maxLine := max(endIdx-startIdx-1, 0)
	line := min(max(w.runs.CurrentLine(), 0), maxLine)

	w.runs.SetPageAndLine(page, line)
	return startIdx, endIdx
}

// renderRunsListHeader renders "Runs [X‑Y of N]" (or "[N items]" for single‑page).
func (w *Workspace) renderRunsListHeader(startIdx, endIdx int) string {
	title := runOverviewSidebarSectionHeaderStyle.Render("Runs")

	total := len(w.runs.FilteredItems)
	info := ""

	if total > 0 {
		ipp := w.runs.ItemsPerPage()
		if ipp > 0 && total > ipp {
			// X‑Y are 1‑based indices for the current page.
			info = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total)
		} else {
			info = fmt.Sprintf(" [%d items]", total)
		}
	}

	return title + navInfoStyle.Render(info)
}

// renderRunLines renders the visible slice with zebra background and selection.
func (w *Workspace) renderRunLines(contentWidth int) []string {
	itemsPerPage := w.runs.ItemsPerPage()
	startIdx := w.runs.CurrentPage() * itemsPerPage
	endIdx := min(startIdx+itemsPerPage, len(w.runs.FilteredItems))

	lines := make([]string, 0, endIdx-startIdx)
	selectedLine := w.runs.CurrentLine()

	for i := startIdx; i < endIdx; i++ {
		idxOnPage := i - startIdx
		item := w.runs.FilteredItems[i]

		// Determine row style.
		style := evenRunStyle
		if idxOnPage%2 == 1 {
			style = oddRunStyle
		}
		if idxOnPage == selectedLine {
			if w.runs.Active {
				style = selectedRunStyle
			} else {
				style = selectedRunInactiveStyle
			}
		}

		// TODO: Stable mapping for consistent colors: refactor and clean up.
		runKey := item.Key
		runID := extractRunID(runKey)
		runPath := filepath.Join(w.wandbDir, runKey, "run-"+runID+".wandb")

		graphColors := GraphColors(w.config.ColorScheme())
		colorIdx := colorIndex(runPath, len(graphColors))

		isSelected := w.selectedRuns[runKey]
		isPinned := w.pinnedRun == runKey

		mark := RunMark
		if isSelected {
			mark = SelectedRunMark
		}
		if isPinned {
			mark = PinnedRunMark
		}

		// Render prefix without background
		prefix := lipgloss.NewStyle().Foreground(graphColors[colorIdx]).Render(mark + " ")
		prefixWidth := lipgloss.Width(prefix)

		// Apply subtle muting to unselected/unpinned runs
		nameStyle := style.Foreground(colorItemValue)
		if idxOnPage == selectedLine {
			nameStyle = nameStyle.Foreground(colorDark)
		}
		if !isSelected && !isPinned {
			nameStyle = nameStyle.Foreground(colorText)
		}

		// Render name with background and optional muting
		nameWidth := max(contentWidth-prefixWidth, 1)
		name := nameStyle.Render(truncateValue(runKey, nameWidth))

		// Pad the styled name to fill remaining width
		paddingNeeded := contentWidth - prefixWidth - lipgloss.Width(name)
		padding := style.Render(strings.Repeat(" ", max(paddingNeeded, 0)))

		lines = append(lines, prefix+name+padding)
	}

	return lines
}
