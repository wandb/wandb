package leet

import (
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"

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

	// focusMgr is the single source of truth for UI focus state.
	focusMgr *FocusManager

	// Configuration and key bindings.
	config *ConfigManager
	keyMap map[string]func(*Workspace, tea.KeyPressMsg) tea.Cmd

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

	// filter drives the runs sidebar search box.
	filter *Filter
	// runsFilterIndex caches searchable per-run metadata (name, project, config)
	// for the runs sidebar so metadata filtering stays fast during live preview.
	runsFilterIndex map[string]WorkspaceRunFilterData

	// Multi‑run metrics state.
	metricsGridAnimState *AnimatedValue
	focus                *Focus
	metricsGrid          *MetricsGrid
	runColors            *workspaceRunColors

	// System metrics
	systemMetrics       map[string]*SystemMetricsGrid
	systemMetricsPane   *SystemMetricsPane
	systemMetricsFocus  *Focus
	systemMetricsFilter *Filter

	// Run console logs keyed by run path.
	consoleLogs     map[string]*RunConsoleLogs
	consoleLogsPane *ConsoleLogsPane

	// Run media keyed by run path.
	media              map[string]*MediaStore
	mediaPane          *MediaPane
	mediaPaneStates    map[string]*MediaPaneViewState
	currentMediaRunKey string

	// Per‑run streaming state keyed by runDirName.
	runsByKey map[string]*WorkspaceRun

	// Heartbeat for live runs.
	liveChan     chan tea.Msg
	heartbeatMgr *HeartbeatManager

	logger *observability.CoreLogger

	width, height int
}

// WorkspaceRun holds per‑run state for the workspace multi‑run view.
type WorkspaceRun struct {
	Key       string
	Reader    HistorySource
	wandbPath string
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
	metricsGrid := NewMetricsGrid(cfg, cfg.WorkspaceMetricsGrid, focus, logger)
	runColors := newWorkspaceRunColors(GraphColors(cfg.ColorScheme()))
	metricsGrid.SetSeriesColorProvider(runColors.Assign)

	smf := NewFilter()

	// Heartbeat for all live workspace runs shares a single channel.
	ch := make(chan tea.Msg, 4096)
	hbInterval := cfg.HeartbeatInterval()
	logger.Info(fmt.Sprintf("workspace: heartbeat interval set to %v", hbInterval))

	runOverviewAnimState := NewAnimatedValue(
		cfg.WorkspaceOverviewVisible(), SidebarMinWidth)
	metricsGridAnimState := NewAnimatedValue(cfg.WorkspaceMetricsGridVisible(), 1)

	systemMetricsPaneAnimState := NewAnimatedValue(
		cfg.WorkspaceSystemMetricsVisible(), systemMetricsPaneMinHeight)
	mediaPaneAnimState := NewAnimatedValue(
		cfg.WorkspaceMediaVisible(), mediaPaneMinHeight)
	consoleLogsPaneAnimState := NewAnimatedValue(
		cfg.WorkspaceConsoleLogsVisible(), ConsoleLogsPaneMinHeight)

	w := &Workspace{
		runsAnimState:        NewAnimatedValue(true, SidebarMinWidth),
		metricsGridAnimState: metricsGridAnimState,
		wandbDir:             wandbDir,
		config:               cfg,
		keyMap:               buildKeyMap(WorkspaceKeyBindings()),
		logger:               logger,
		runs:                 runs,
		runOverview:          make(map[string]*RunOverview),
		runOverviewSidebar: NewRunOverviewSidebar(
			cfg, runOverviewAnimState, NewRunOverview(), SidebarSideRight),
		overviewPreloader:   newRunOverviewPreloader(maxConcurrentPreloads),
		selectedRuns:        make(map[string]bool),
		focus:               focus,
		metricsGrid:         metricsGrid,
		runColors:           runColors,
		systemMetrics:       make(map[string]*SystemMetricsGrid),
		systemMetricsPane:   NewSystemMetricsPane(systemMetricsPaneAnimState),
		systemMetricsFocus:  focus,
		systemMetricsFilter: smf,
		consoleLogs:         make(map[string]*RunConsoleLogs),
		consoleLogsPane:     NewConsoleLogsPane(consoleLogsPaneAnimState),
		media:               make(map[string]*MediaStore),
		mediaPane:           NewMediaPane(mediaPaneAnimState, cfg.WorkspaceMediaGrid),
		runsByKey:           make(map[string]*WorkspaceRun),
		liveChan:            ch,
		heartbeatMgr:        NewHeartbeatManager(hbInterval, ch, logger),
		filter:              NewFilter(),
		runsFilterIndex:     make(map[string]WorkspaceRunFilterData),
	}
	w.focusMgr = w.buildWorkspaceFocusManager()
	// The runs list starts focused by default.
	w.focusMgr.SetTarget(FocusTargetRunsList, 1)
	return w
}

// SetSize updates the workspace dimensions and recomputes pagination capacity.
func (w *Workspace) SetSize(width, height int) {
	w.width, w.height = width, height

	// The runs list lives in the main content area (above the status bar).
	contentHeight := max(height-StatusBarHeight, 0)
	available := max(contentHeight-workspaceHeaderLines-SidebarBottomPadding, 1)

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

	case tea.KeyPressMsg:
		return w.handleKeyPressMsg(t)

	case tea.MouseMsg:
		return w.handleMouse(t)

	case WorkspaceRunsAnimationMsg:
		return w.handleRunsAnimation()

	case WorkspaceRunOverviewAnimationMsg:
		return w.handleRunOverviewAnimation()

	case WorkspaceConsoleLogsPaneAnimationMsg:
		return w.handleConsoleLogsPaneAnimation()

	case WorkspaceMediaPaneAnimationMsg:
		return w.handleMediaPaneAnimation()

	case WorkspaceMetricsGridAnimationMsg:
		return w.handleMetricsGridAnimation()

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
func (w *Workspace) View() tea.View {
	layout := w.computeViewports()
	runLabel, systemGrid, systemHint, mediaHint, logsHint := w.syncCurrentRunContext()

	var cols []string
	if w.runsAnimState.IsVisible() {
		cols = append(cols, w.renderRunsList())
	}

	contentWidth := layout.mainContentAreaWidth
	centralColumn := ""
	if w.mediaPane.IsFullscreen() {
		centralColumn = w.mediaPane.View(
			contentWidth, layout.totalContentAreaHeight, runLabel, mediaHint)
	} else {
		var sections []string

		if w.metricsGridAnimState.IsVisible() {
			sections = append(sections, w.renderMetrics(layout))
		}

		if layout.systemMetricsHeight > 0 {
			sections = append(sections,
				w.systemMetricsPane.View(contentWidth, runLabel, systemGrid, systemHint))
		}

		if layout.mediaHeight > 0 {
			sections = append(sections,
				w.mediaPane.View(contentWidth, layout.mediaHeight, runLabel, mediaHint))
		}

		if layout.consoleLogsHeight > 0 {
			sections = append(sections,
				w.consoleLogsPane.View(contentWidth, runLabel, logsHint))
		}

		sections = filterNonEmptySections(sections)
		if len(sections) == 0 {
			centralColumn = renderLogoArt(contentWidth, layout.totalContentAreaHeight)
		} else {
			centralColumn = joinWithSeparators(sections, contentWidth)
		}
	}
	centralColumn = placeMainColumn(contentWidth, layout.totalContentAreaHeight, centralColumn)
	cols = append(cols, centralColumn)

	if w.runOverviewSidebar.IsVisible() {
		cols = append(cols, w.renderRunOverview())
	}

	mainView := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	statusBar := w.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return tea.NewView(
		lipgloss.Place(
			w.width, w.height,
			lipgloss.Left, lipgloss.Top,
			fullView,
		),
	)
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

// SelectedRunKey returns the run key (directory name) of the currently selected run.
func (w *Workspace) SelectedRunKey() string {
	total := len(w.runs.FilteredItems)
	if total == 0 {
		return ""
	}
	startIdx := w.runs.CurrentPage() * w.runs.ItemsPerPage()
	idx := startIdx + w.runs.CurrentLine()
	if idx < 0 || idx >= total {
		return ""
	}
	return w.runs.FilteredItems[idx].Key
}

// MediaStoreForRun returns the workspace's MediaStore for a given run key.
func (w *Workspace) MediaStoreForRun(runKey string) *MediaStore {
	return w.media[runKey]
}

// SaveMediaPaneState stores the media pane's view state for a run.
func (w *Workspace) SaveMediaPaneState(runKey string, state MediaPaneViewState) {
	if w.mediaPaneStates == nil {
		w.mediaPaneStates = make(map[string]*MediaPaneViewState)
	}
	w.mediaPaneStates[runKey] = &state
}

// LoadMediaPaneState returns saved media pane view state for a run.
func (w *Workspace) LoadMediaPaneState(runKey string) *MediaPaneViewState {
	if w.mediaPaneStates == nil {
		return nil
	}
	return w.mediaPaneStates[runKey]
}

func (w *Workspace) syncCurrentRunContext() (
	runLabel string,
	systemGrid *SystemMetricsGrid,
	systemHint string,
	mediaHint string,
	logsHint string,
) {
	cur, ok := w.runs.CurrentItem()
	currentRunKey := ""
	if ok {
		currentRunKey = cur.Key
		runLabel = cur.Key
		systemGrid = w.systemMetrics[cur.Key]
	}

	currentStore := w.media[currentRunKey]
	if currentRunKey != w.currentMediaRunKey {
		if w.currentMediaRunKey != "" {
			w.SaveMediaPaneState(w.currentMediaRunKey, w.mediaPane.SaveViewState())
		}

		w.currentMediaRunKey = currentRunKey
		w.mediaPane.SetStore(currentStore)
		if currentStore != nil {
			if state := w.LoadMediaPaneState(currentRunKey); state != nil {
				w.mediaPane.RestoreViewState(*state)
			} else {
				w.mediaPane.ResetViewState()
			}
		} else {
			w.mediaPane.ResetViewState()
		}
	} else {
		previousStore := w.mediaPane.store
		w.mediaPane.SetStore(currentStore)
		if previousStore == nil && currentStore != nil {
			if state := w.LoadMediaPaneState(currentRunKey); state != nil {
				w.mediaPane.RestoreViewState(*state)
			}
		}
	}

	if currentRunKey == "" {
		w.consoleLogsPane.SetConsoleLogs(nil)
		return runLabel, systemGrid, systemHint, mediaHint, logsHint
	}

	if cl := w.consoleLogs[currentRunKey]; cl != nil {
		w.consoleLogsPane.SetConsoleLogs(cl.Items())
	} else {
		w.consoleLogsPane.SetConsoleLogs(nil)
	}

	if _, selected := w.selectedRuns[currentRunKey]; !selected {
		systemHint = "Select this run (Space) to load system metrics."
		mediaHint = "Select this run (Space) to load media."
		logsHint = "Select this run (Space) to load console logs."
	}

	return runLabel, systemGrid, systemHint, mediaHint, logsHint
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
//
// Separator lines between visible sections are subtracted from available height
// to prevent the status bar from being pushed off screen.
func (w *Workspace) computeViewports() Layout {
	leftW, rightW := w.runsAnimState.Value(), w.runOverviewSidebar.Width()
	contentW := max(w.width-leftW-rightW, 1)
	totalH := max(w.height-StatusBarHeight, 0)

	stack := computeVerticalStackLayout(
		totalH,
		stackSectionSpec{
			ID:      stackSectionMetrics,
			Visible: w.metricsGridAnimState.IsVisible(),
			Flex:    true},
		stackSectionSpec{
			ID:      stackSectionSystemMetrics,
			Visible: w.systemMetricsPane.IsVisible(),
			Height:  w.systemMetricsPane.Height()},
		stackSectionSpec{
			ID:      stackSectionMedia,
			Visible: w.mediaPane.IsVisible(),
			Height:  w.mediaPane.Height()},
		stackSectionSpec{
			ID:      stackSectionConsoleLogs,
			Visible: w.consoleLogsPane.IsVisible(),
			Height:  w.consoleLogsPane.Height()},
	)

	return Layout{
		leftSidebarWidth:       leftW,
		mainContentAreaWidth:   contentW,
		rightSidebarWidth:      rightW,
		totalContentAreaHeight: totalH,
		height:                 stack.Height(stackSectionMetrics),
		systemMetricsY:         stack.Y(stackSectionSystemMetrics),
		systemMetricsHeight:    stack.Height(stackSectionSystemMetrics),
		mediaY:                 stack.Y(stackSectionMedia),
		mediaHeight:            stack.Height(stackSectionMedia),
		consoleLogsY:           stack.Y(stackSectionConsoleLogs),
		consoleLogsHeight:      stack.Height(stackSectionConsoleLogs),
	}
}

// updateSidebarDimensions tells both sidebars to recalculate their expanded
// widths given the post-toggle visibility of each side.
func (w *Workspace) updateSidebarDimensions(leftVisible, rightVisible bool) {
	w.runsAnimState.SetExpanded(expandedSidebarWidth(w.width, rightVisible))
	w.runOverviewSidebar.UpdateDimensions(w.width, leftVisible)
}

func (w *Workspace) updateBottomPaneHeights(sysVisible, mediaVisible, logsVisible bool) {
	metricsVisible := w.metricsGridAnimState.TargetVisible()

	// Compute separator count from the visibility state we're configuring toward.
	sectionCount := 0
	if metricsVisible {
		sectionCount++
	}
	if sysVisible {
		sectionCount++
	}
	if mediaVisible {
		sectionCount++
	}
	if logsVisible {
		sectionCount++
	}
	sepLines := max(sectionCount-1, 0)

	maxH := max(w.height-StatusBarHeight-sepLines, 0)
	lowerCount := 0
	if sysVisible {
		lowerCount++
	}
	if mediaVisible {
		lowerCount++
	}
	if logsVisible {
		lowerCount++
	}
	if lowerCount == 0 {
		return
	}

	var lowerTierH int
	if metricsVisible {
		lowerTierH = int(float64(maxH) * LowerTierRatio)
	} else {
		lowerTierH = maxH
	}

	each := lowerTierH / lowerCount
	if sysVisible {
		w.systemMetricsPane.SetExpandedHeight(each)
	}
	if mediaVisible {
		w.mediaPane.SetExpandedHeight(each)
	}
	if logsVisible {
		w.consoleLogsPane.SetExpandedHeight(each)
	}
}

// ---- FocusManager wiring ----

func (w *Workspace) buildWorkspaceFocusManager() *FocusManager {
	return NewFocusManager([]FocusRegionDef{
		{
			FocusTargetRunsList,
			w.runsFocusAvailable,
			w.activateRunsFocus,
			w.deactivateRunsFocus,
		},
		{
			FocusTargetMetricsGrid,
			w.metricsGridFocusAvailable,
			w.activateMetricsGridFocus,
			w.deactivateMetricsGridFocus,
		},
		{
			FocusTargetSystemMetrics,
			w.sysMetricsFocusAvailable,
			w.activateSysMetricsFocus,
			w.deactivateSysMetricsFocus,
		},
		{
			FocusTargetMedia,
			w.mediaFocusAvailable,
			w.activateMediaFocus,
			w.deactivateMediaFocus,
		},
		{
			FocusTargetConsoleLogs,
			w.logsFocusAvailable,
			w.activateLogsFocus,
			w.deactivateLogsFocus,
		},
		{
			FocusTargetOverview,
			w.overviewFocusAvailable,
			w.activateOverviewFocus,
			w.deactivateOverviewFocus,
		},
	})
}

// ---- Focus availability ----

func (w *Workspace) runsFocusAvailable() bool {
	return w.runsAnimState.IsVisible() && len(w.runs.FilteredItems) > 0
}
func (w *Workspace) metricsGridFocusAvailable() bool {
	return w.metricsGridAnimState.IsExpanded() && len(w.selectedRuns) > 0
}
func (w *Workspace) sysMetricsFocusAvailable() bool { return w.systemMetricsPane.IsExpanded() }
func (w *Workspace) mediaFocusAvailable() bool {
	return w.mediaPane.IsExpanded() && w.mediaPane.HasData()
}
func (w *Workspace) logsFocusAvailable() bool { return w.consoleLogsPane.IsExpanded() }
func (w *Workspace) overviewFocusAvailable() bool {
	firstSec, _ := w.runOverviewSidebar.focusableSectionBounds()
	return w.runOverviewSidebar.animState.IsExpanded() && firstSec != -1
}

// ---- Focus activate ----

func (w *Workspace) activateRunsFocus(_ int) { w.runs.Active = true }
func (w *Workspace) activateMetricsGridFocus(_ int) {
	w.focus.Type = FocusMainChart
	if w.focus.Row < 0 {
		w.focus.Row = 0
		w.focus.Col = 0
	}
	w.metricsGrid.NavigateFocus(0, 0)
}
func (w *Workspace) activateSysMetricsFocus(_ int) {
	if w.systemMetricsFocus != nil {
		w.systemMetricsFocus.Type = FocusSystemChart
		if w.systemMetricsFocus.Row < 0 {
			w.systemMetricsFocus.Row = 0
			w.systemMetricsFocus.Col = 0
		}
	}
	if g := w.activeSystemMetricsGrid(); g != nil {
		g.NavigateFocus(0, 0)
	}
}
func (w *Workspace) activateMediaFocus(_ int) { w.mediaPane.SetActive(true) }
func (w *Workspace) activateLogsFocus(_ int)  { w.consoleLogsPane.SetActive(true) }
func (w *Workspace) activateOverviewFocus(direction int) {
	firstSec, lastSec := w.runOverviewSidebar.focusableSectionBounds()
	if direction >= 0 {
		w.runOverviewSidebar.setActiveSection(firstSec)
	} else {
		w.runOverviewSidebar.setActiveSection(lastSec)
	}
}

// ---- Focus deactivate ----

func (w *Workspace) deactivateRunsFocus() { w.runs.Active = false }
func (w *Workspace) deactivateMetricsGridFocus() {
	if w.focus.Type == FocusMainChart {
		w.focus.Reset()
	}
}
func (w *Workspace) deactivateSysMetricsFocus() {
	if w.systemMetricsFocus != nil && w.systemMetricsFocus.Type == FocusSystemChart {
		w.systemMetricsFocus.Reset()
	}
}
func (w *Workspace) deactivateMediaFocus()    { w.mediaPane.SetActive(false) }
func (w *Workspace) deactivateLogsFocus()     { w.consoleLogsPane.SetActive(false) }
func (w *Workspace) deactivateOverviewFocus() { w.runOverviewSidebar.deactivateAllSections() }

// cycleOverviewSection tries to move within overview sections.
//
// Returns true if the navigation was handled (i.e. we're not at a boundary).
func (w *Workspace) cycleOverviewSection(direction int) bool {
	firstSec, lastSec := w.runOverviewSidebar.focusableSectionBounds()
	if !w.runOverviewSidebar.animState.IsExpanded() || firstSec == -1 {
		return false
	}

	atBoundary := (direction == 1 && w.runOverviewSidebar.activeSection == lastSec) ||
		(direction == -1 && w.runOverviewSidebar.activeSection == firstSec)
	if atBoundary {
		return false
	}

	w.runOverviewSidebar.navigateSection(direction)
	return true
}

// handleWindowResize handles window resize messages.
func (w *Workspace) handleWindowResize(width, height int) {
	w.SetSize(width, height)
	w.updateSidebarDimensions(w.runsAnimState.TargetVisible(), w.runOverviewSidebar.animState.TargetVisible())
	w.updateBottomPaneHeights(
		w.systemMetricsPane.animState.TargetVisible(),
		w.mediaPane.animState.TargetVisible(),
		w.consoleLogsPane.animState.TargetVisible(),
	)
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

func (w *Workspace) mediaPaneAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return WorkspaceMediaPaneAnimationMsg{}
	})
}

func (w *Workspace) metricsGridAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return WorkspaceMetricsGridAnimationMsg{}
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
		if run.Reader != nil {
			run.Reader.Close()
		}
		delete(w.runsByKey, runKey)
		delete(w.consoleLogs, runKey)
		delete(w.systemMetrics, runKey)
		delete(w.media, runKey)
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

func (w *Workspace) getOrCreateMediaStore(runKey string) *MediaStore {
	store := w.media[runKey]
	if store != nil {
		return store
	}
	store = NewMediaStore()
	w.media[runKey] = store
	return store
}

func (w *Workspace) getOrCreateSystemMetricsGrid(runKey string) *SystemMetricsGrid {
	if g := w.systemMetrics[runKey]; g != nil {
		return g
	}

	rows, cols := w.config.WorkspaceSystemGrid()
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
	return w.focusMgr.IsTarget(FocusTargetRunsList) &&
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
	return w.focusMgr.IsTarget(FocusTargetOverview) && w.runOverviewSidebar.IsVisible()
}

// ---- Rendering ----

func (w *Workspace) renderRunsList() string {
	startIdx, endIdx := w.syncRunsPage()

	totalW := w.runsAnimState.Value()
	totalH := max(w.height-StatusBarHeight, 0)
	if totalW <= SidebarOverhead || totalH <= 0 {
		return ""
	}

	contentWidth := sidebarContentWidth(totalW)
	lines := w.renderRunLines(contentWidth)

	if len(lines) == 0 {
		lines = []string{navInfoStyle.Render("No runs found.")}
	}

	contentLines := make([]string, 0, 1+len(lines))
	contentLines = append(contentLines, w.renderRunsListHeader(startIdx, endIdx))
	contentLines = append(contentLines, lines...)
	content := strings.Join(contentLines, "\n")

	innerW := sidebarInnerWidth(totalW)

	styledContent := leftSidebarStyle.
		PaddingBottom(SidebarBottomPadding).
		Width(innerW).
		Height(totalH).
		MaxWidth(innerW).
		MaxHeight(totalH).
		Render(content)

	boxed := leftSidebarBorderStyle.
		Height(totalH).
		MaxHeight(totalH).
		Render(styledContent)
	return lipgloss.Place(totalW, totalH, lipgloss.Left, lipgloss.Top, boxed)
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

	contentH := max(w.height-StatusBarHeight, 0)
	return w.runOverviewSidebar.View(contentH).Content
}

func (w *Workspace) renderMetrics(layout Layout) string {
	contentWidth := layout.mainContentAreaWidth
	contentHeight := layout.height

	if contentWidth <= 0 || contentHeight <= 0 {
		return ""
	}

	// No runs selected: show empty state with hint.
	if len(w.selectedRuns) == 0 {
		return renderMetricsEmptyState(contentWidth, contentHeight, "Select a run to view charts.")
	}

	// Runs selected but no charts: show empty state.
	if w.metricsGrid.ChartCount() == 0 {
		return renderMetricsEmptyState(contentWidth, contentHeight, "No scalar metrics logged.")
	}

	// When we have selected runs, render the metrics grid.
	dims := w.metricsGrid.CalculateChartDimensions(contentWidth, contentHeight)
	return w.metricsGrid.View(dims)
}

// renderMetricsEmptyState renders a styled "Metrics" header with a hint message.
func renderMetricsEmptyState(width, height int, hint string) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	innerW := max(width-ContentPaddingCols, 0)
	header := mediaPaneHeaderStyle.Render("Metrics")
	hintText := mediaTilePlaceholderStyle.Render(hint)
	content := lipgloss.JoinVertical(lipgloss.Left, header, "", hintText)
	content = lipgloss.Place(innerW, height, lipgloss.Left, lipgloss.Top, content)
	return lipgloss.NewStyle().Padding(0, ContentPadding).Render(content)
}

// renderLogoArt renders the wandb/leet ASCII art centered in the given area.
func renderLogoArt(width, height int) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	artStyle := lipgloss.NewStyle().
		Foreground(colorHeading).
		Bold(true)

	logoContent := lipgloss.JoinVertical(
		lipgloss.Center,
		artStyle.Render(wandbArt),
		artStyle.Render(leetArt),
	)

	return lipgloss.Place(
		width,
		height,
		lipgloss.Center,
		lipgloss.Center,
		logoContent,
	)
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
	// Filter input mode has top priority.
	if w.filter.IsActive() {
		return w.buildRunsFilterStatus()
	}
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

	if w.filter.Query() != "" && !w.filter.IsActive() {
		parts = append(parts, fmt.Sprintf(
			"Runs (%s): %q [%d/%d] (f to change, ctrl+f to clear)",
			w.filter.Mode().String(),
			w.filter.Query(),
			len(w.runs.FilteredItems),
			len(w.runs.Items),
		))
	}

	if w.metricsGrid.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"Filter (%s): %q [%d/%d] (/ to change, ctrl+/ to clear)",
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
			"Overview: %q [%s] (o to change, ctrl+o to clear)",
			w.runOverviewSidebar.FilterQuery(),
			w.runOverviewSidebar.FilterInfo(),
		))
	}

	// Show the highlighted overview key/value when the sidebar is visible.
	if w.runOverviewActive() {
		key, value := w.runOverviewSidebar.SelectedItem()
		if key != "" {
			parts = append(parts, fmt.Sprintf("%s: %s", key, value))
		}
	}

	if w.mediaPane.Active() {
		if label := w.mediaPane.StatusLabel(); label != "" {
			parts = append(parts, label)
		}
	}

	if w.focus.Type != FocusNone {
		parts = append(parts, w.focus.Title)
		switch w.focus.Type {
		case FocusMainChart:
			if scaleLabel := w.metricsGrid.focusedChartScaleLabel(); scaleLabel != "" {
				parts = append(parts, scaleLabel)
			}
		case FocusSystemChart:
			if g := w.activeSystemMetricsGrid(); g != nil {
				if detail := g.FocusedChartTitleDetail(); detail != "" {
					parts = append(parts, detail)
				}
				if viewMode := g.FocusedChartViewModeLabel(); viewMode != "" {
					parts = append(parts, viewMode)
				}
				if scaleLabel := g.FocusedChartScaleLabel(); scaleLabel != "" {
					parts = append(parts, scaleLabel)
				}
			}
		}
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

// renderRunsListHeader renders the runs list title and counts.
func (w *Workspace) renderRunsListHeader(startIdx, endIdx int) string {
	title := runOverviewSidebarSectionHeaderStyle.Render("Runs")

	filteredCount := len(w.runs.FilteredItems)
	totalCount := len(w.runs.Items)
	info := ""

	switch {
	case w.filter.Query() != "" && totalCount > 0:
		ipp := w.runs.ItemsPerPage()
		switch {
		case filteredCount == 0:
			info = fmt.Sprintf(" [0 of %d filtered]", totalCount)
		case ipp > 0 && filteredCount > ipp:
			info = fmt.Sprintf(
				" [%d-%d of %d filtered from %d total]",
				startIdx+1,
				endIdx,
				filteredCount,
				totalCount,
			)
		default:
			info = fmt.Sprintf(" [%d filtered from %d total]", filteredCount, totalCount)
		}
	case filteredCount > 0:
		ipp := w.runs.ItemsPerPage()
		if ipp > 0 && filteredCount > ipp {
			info = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, filteredCount)
		} else {
			info = fmt.Sprintf(" [%d items]", filteredCount)
		}
	}

	return title + navInfoStyle.Render(info)
}

func (w *Workspace) runPathForKey(runKey string) string {
	if runKey == "" {
		return ""
	}
	return runWandbFile(w.wandbDir, runKey)
}

func (w *Workspace) runColorForKey(runKey string) compat.AdaptiveColor {
	runPath := w.runPathForKey(runKey)
	if w.runColors == nil {
		colors := GraphColors(w.config.ColorScheme())
		if len(colors) == 0 {
			return compat.AdaptiveColor{}
		}
		return colors[colorIndex(runPath, len(colors))]
	}
	return w.runColors.Assign(runPath)
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

		runKey := item.Key
		runColor := w.runColorForKey(runKey)

		isSelected := w.selectedRuns[runKey]
		isPinned := w.pinnedRun == runKey

		mark := RunMark
		if isSelected {
			mark = SelectedRunMark
		}
		if isPinned {
			mark = PinnedRunMark
		}

		// Render prefix without background.
		prefix := lipgloss.NewStyle().Foreground(runColor).Render(mark + " ")
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
