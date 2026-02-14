package leet

import (
	"fmt"
	"net/url"
	"runtime/debug"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// Run holds data/state related to a single W&B run.
//
// Implements tea.Model.
// It coordinates the main metrics grid, sidebars, help screen, and data loading.
type Run struct {
	// Serialize access to Update / broad model state.
	stateMu sync.RWMutex

	// Configuration and key bindings.
	config *ConfigManager
	keyMap map[string]func(*Run, tea.KeyPressMsg) tea.Cmd

	// Terminal dimensions.
	width, height int

	// Run file path.
	runPath string

	// Run state tracking.
	runState RunState

	// isLoading controls whether the loading screen is displayed.
	//
	// Defaults to true and is set to false once a RunRecord is
	// successfully loaded from the transaction log.
	isLoading bool

	// liveRunning caches whether the run is in RunStateRunning.
	//
	// Written on the main goroutine; read from the HeartbeatManager timer goroutine.
	liveRunning atomic.Bool

	// Data reader.
	historySource HistorySource

	// Transaction log (.wandb file) watch and heartbeat management.
	watcherMgr   *WatcherManager
	heartbeatMgr *HeartbeatManager

	// Focus management.
	focusMgr *FocusManager
	focus    *Focus

	// UI components.
	metricsGridAnimState *AnimatedValue
	metricsGrid          *MetricsGrid
	runOverview          *RunOverview
	leftSidebar          *RunOverviewSidebar
	rightSidebar         *RightSidebar
	consoleLogs          *RunConsoleLogs
	consoleLogsPane      *ConsoleLogsPane
	mediaStore           *MediaStore
	mediaPane            *MediaPane

	// Sidebar animation synchronization.
	animationMu sync.Mutex
	animating   bool

	// Loading progress.
	recordsLoaded int
	loadStartTime time.Time

	// Coalesce expensive redraws during batch processing.
	suppressDraw bool

	// Logger.
	logger *observability.CoreLogger
}

func NewRun(
	runPath string,
	cfg *ConfigManager,
	logger *observability.CoreLogger,
) *Run {
	logger.Info(fmt.Sprintf("run: creating new run model for runPath: %s", runPath))

	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	heartbeatInterval := cfg.HeartbeatInterval()
	logger.Info(fmt.Sprintf("run: heartbeat interval set to %v", heartbeatInterval))

	focus := NewFocus()
	ch := make(chan tea.Msg, 4096)

	ro := NewRunOverview()
	runOverviewAnimState := NewAnimatedValue(cfg.LeftSidebarVisible(), SidebarMinWidth)

	// The metrics grid AnimatedValue tracks a "maximum height" that the grid is allowed.
	// When collapsed (target=0), the grid renders nothing and bottom panes take all space.
	metricsGridAnimState := NewAnimatedValue(cfg.MetricsGridVisible(), 1)

	consoleLogsPaneAnimState := NewAnimatedValue(
		cfg.ConsoleLogsVisible(), ConsoleLogsPaneMinHeight)
	mediaPaneAnimState := NewAnimatedValue(
		cfg.MediaVisible(), mediaPaneMinHeight)

	metricsGrid := NewMetricsGrid(cfg, cfg.MetricsGrid, focus, logger)
	metricsGrid.SetSingleSeriesColorMode(cfg.SingleRunColorMode())

	mediaStore := NewMediaStore()

	run := &Run{
		config:               cfg,
		keyMap:               buildKeyMap(RunKeyBindings()),
		focus:                focus,
		isLoading:            true,
		runPath:              runPath,
		metricsGridAnimState: metricsGridAnimState,
		metricsGrid:          metricsGrid,
		runOverview:          ro,
		leftSidebar:          NewRunOverviewSidebar(cfg, runOverviewAnimState, ro, SidebarSideLeft),
		rightSidebar:         NewRightSidebar(cfg, focus, logger),
		consoleLogs:          NewRunConsoleLogs(),
		consoleLogsPane:      NewConsoleLogsPane(consoleLogsPaneAnimState),
		mediaStore:           mediaStore,
		mediaPane:            NewMediaPane(mediaPaneAnimState, cfg.MediaGrid),
		watcherMgr:           NewWatcherManager(ch, logger),
		heartbeatMgr:         NewHeartbeatManager(heartbeatInterval, ch, logger),
		logger:               logger,
	}
	run.focusMgr = run.buildRunFocusManager()
	return run
}

// SetMediaStore replaces the run's media store (e.g., to share with workspace).
func (r *Run) SetMediaStore(store *MediaStore) {
	r.mediaStore = store
	r.mediaPane.SetStore(store)
}

// Init initializes the model and returns the initial command.
//
// Implements tea.Model.Init.
func (r *Run) Init() tea.Cmd {
	r.logger.Debug("run: Init called")
	var source tea.Cmd

	runPath, err := url.Parse(r.runPath)
	if err != nil || !strings.HasPrefix(runPath.Scheme, "http") {
		source = InitializeLevelDBHistorySource(r.runPath, r.logger)
	} else {
		source = InitializeParquetHistorySource(
			runPath,
			r.logger,
		)
	}

	return tea.Batch(
		source,
		r.watcherMgr.WaitForMsg,
	)
}

// Update handles incoming events and updates the model accordingly.
//
// Implements tea.Model.Update.
func (r *Run) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	defer r.logPanic("Update")
	defer timeit(r.logger, "Model.Update")()
	r.stateMu.Lock()
	defer r.stateMu.Unlock()

	var cmds []tea.Cmd

	// Forward UI messages to children if not in filter mode.
	if isUIMsg(msg) && !r.metricsGrid.IsFilterMode() && !r.leftSidebar.IsFilterMode() {
		if _, ok := msg.(tea.KeyPressMsg); !ok {
			if _, cmd := r.leftSidebar.Update(msg); cmd != nil {
				cmds = append(cmds, cmd)
			}
			if _, cmd := r.rightSidebar.Update(msg); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
	}

	// Route message to appropriate handler.
	switch t := msg.(type) {
	case tea.KeyPressMsg:
		if c := r.handleKeyPressMsg(t); c != nil {
			cmds = append(cmds, c)
		}
		return r, tea.Batch(cmds...)

	case tea.MouseMsg:
		newM, c := r.handleMouseMsg(t)
		if c != nil {
			cmds = append(cmds, c)
		}
		return newM, tea.Batch(cmds...)

	case tea.WindowSizeMsg:
		r.handleWindowResize(t)
		return r, tea.Batch(cmds...)

	default:
		cmds = append(cmds, r.dispatch(msg)...)
		return r, tea.Batch(cmds...)
	}
}

// handleWindowResize handles window resize messages.
func (r *Run) handleWindowResize(msg tea.WindowSizeMsg) {
	r.width, r.height = msg.Width, msg.Height

	r.leftSidebar.UpdateDimensions(msg.Width, r.rightSidebar.animState.TargetVisible())
	r.rightSidebar.UpdateDimensions(msg.Width, r.leftSidebar.animState.TargetVisible())
	r.updateBottomPaneHeights(
		r.mediaPane.animState.TargetVisible(), r.consoleLogsPane.animState.TargetVisible())

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)
}

// isUIMsg returns true for messages that should flow to child view models.
func isUIMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case tea.KeyPressMsg, tea.MouseMsg, tea.WindowSizeMsg,
		LeftSidebarAnimationMsg, RightSidebarAnimationMsg,
		ConsoleLogsPaneAnimationMsg, MediaPaneAnimationMsg,
		MetricsGridAnimationMsg:
		return true
	default:
		return false
	}
}

// dispatch routes message types to appropriate handlers.
func (r *Run) dispatch(msg tea.Msg) []tea.Cmd {
	switch t := msg.(type) {
	case InitMsg:
		return r.handleInit(t)
	case ChunkedBatchMsg:
		return r.handleChunkedBatch(t)
	case BatchedRecordsMsg:
		return r.handleBatched(t)
	case HeartbeatMsg:
		return r.handleHeartbeat()
	case FileChangedMsg:
		return r.handleFileChange()
	case tea.WindowSizeMsg:
		r.handleWindowResize(t)
	case LeftSidebarAnimationMsg, RightSidebarAnimationMsg:
		return r.handleSidebarAnimation(msg)
	case ConsoleLogsPaneAnimationMsg:
		return r.handleConsoleLogsPaneAnimation()
	case MediaPaneAnimationMsg:
		return r.handleMediaPaneAnimation()
	case MetricsGridAnimationMsg:
		return r.handleMetricsGridAnimation()
	default:
		// History/Run/Summary/Stats/SystemInfo/FileComplete/Error
		if _, cmd := r.handleRecordMsg(msg); cmd != nil {
			return []tea.Cmd{cmd}
		}
	}
	return nil
}

// FocusedTitle returns the title of the currently focused chart.
func (r *Run) FocusedTitle() string {
	if r.focus.Type != FocusNone {
		return r.focus.Title
	}
	return ""
}

// View renders the UI based on the data in the model.
//
// Implements tea.Model.View.
func (r *Run) View() tea.View {
	defer r.logPanic("View")

	r.stateMu.RLock()
	defer r.stateMu.RUnlock()

	if r.width == 0 || r.height == 0 {
		return tea.NewView("Loading...")
	}

	if r.isLoading {
		return tea.NewView(r.renderLoadingScreen())
	}

	return tea.NewView(r.renderMainView())
}

// renderMainView renders the main application view.
func (r *Run) renderMainView() string {
	layout := r.computeViewports()
	r.mediaPane.SetStore(r.mediaStore)

	w := layout.mainContentAreaWidth
	centralColumn := ""
	if r.mediaPane.IsFullscreen() {
		centralColumn = r.mediaPane.View(w, layout.totalContentAreaHeight, "", "")
	} else {
		var sections []string

		if r.metricsGridAnimState.IsVisible() && layout.height > 0 {
			if r.metricsGrid.ChartCount() == 0 {
				sections = append(sections,
					renderMetricsEmptyState(w, layout.height, "No scalar metrics logged."))
			} else {
				dims := r.metricsGrid.CalculateChartDimensions(w, layout.height)
				sections = append(sections, r.metricsGrid.View(dims))
			}
		}

		if layout.mediaHeight > 0 {
			sections = append(sections, r.mediaPane.View(w, layout.mediaHeight, "", ""))
		}
		if layout.consoleLogsHeight > 0 {
			r.consoleLogsPane.SetConsoleLogs(r.consoleLogs.Items())
			sections = append(sections, r.consoleLogsPane.View(w, "", ""))
		}

		sections = filterNonEmptySections(sections)
		if len(sections) == 0 {
			centralColumn = renderLogoArt(w, layout.totalContentAreaHeight)
		} else {
			centralColumn = joinWithSeparators(sections, w)
		}
	}
	centralColumn = placeMainColumn(w, layout.totalContentAreaHeight, centralColumn)

	mainView := r.buildMainViewWithSidebars(
		centralColumn,
		layout.totalContentAreaHeight,
		layout.leftSidebarWidth,
		layout.rightSidebarWidth,
	)
	statusBar := r.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(r.width, r.height, lipgloss.Left, lipgloss.Top, fullView)
}

// buildMainViewWithSidebars builds the main view with sidebars.
func (r *Run) buildMainViewWithSidebars(
	gridView string,
	contentHeight int,
	leftWidth, rightWidth int,
) string {
	if leftWidth == 0 && rightWidth == 0 {
		return gridView
	}

	var parts []string

	if leftWidth > 0 {
		leftView := r.leftSidebar.View(contentHeight).Content
		parts = append(parts, leftView)
	}

	parts = append(parts, gridView)

	if rightWidth > 0 {
		rightView := r.rightSidebar.View(contentHeight)
		parts = append(parts, rightView)
	}

	return lipgloss.JoinHorizontal(lipgloss.Top, parts...)
}

// logPanic logs panics to the logger before re-panicking.
func (m *Run) logPanic(context string) {
	if r := recover(); r != nil {
		stackTrace := string(debug.Stack())
		m.logger.CaptureError(
			fmt.Errorf("PANIC in %s: %v\nStack trace:\n%s", context, r, stackTrace),
		)
		panic(r)
	}
}

// isRunning reports whether the run is live.
//
// Safe to call from any goroutine (reads an atomic.Bool).
func (r *Run) isRunning() bool {
	return r.liveRunning.Load()
}

// syncLiveRunning updates the atomic liveness flag from the authoritative state.
func (r *Run) syncLiveRunning() {
	r.liveRunning.Store(r.runState == RunStateRunning)
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen.
func (r *Run) renderLoadingScreen() string {
	centeredLogo := renderLogoArt(r.width, r.height-StatusBarHeight)

	statusBar := r.renderStatusBar()
	return lipgloss.JoinVertical(lipgloss.Left, centeredLogo, statusBar)
}

// renderStatusBar creates the status bar.
func (r *Run) renderStatusBar() string {
	statusText := r.buildStatusText()
	helpText := r.buildHelpText()

	innerWidth := max(r.width-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(r.width).
		MaxWidth(r.width).
		Render(fullStatus)
}

// buildStatusText builds the main status text.
func (r *Run) buildStatusText() string {
	if r.leftSidebar.IsFilterMode() {
		return r.buildOverviewFilterStatus()
	}
	if r.metricsGrid.IsFilterMode() {
		return r.buildMetricsFilterStatus()
	}
	if r.rightSidebar.IsFilterMode() {
		return r.buildSystemMetricsFilterStatus()
	}
	if r.config.IsAwaitingGridConfig() {
		return r.config.GridConfigStatus()
	}
	if r.isLoading {
		return r.buildLoadingStatus()
	}
	return r.buildActiveStatus()
}

// buildOverviewFilterStatus builds status for overview filter mode.
func (r *Run) buildOverviewFilterStatus() string {
	filterInfo := r.leftSidebar.FilterInfo()
	if filterInfo == "" {
		filterInfo = "no matches"
	}
	return fmt.Sprintf(
		"Overview filter (%s): %s%s [%s] (Enter to apply • Tab to toggle mode)",
		r.leftSidebar.FilterMode().String(),
		r.leftSidebar.FilterQuery(),
		string(mediumShadeBlock),
		filterInfo,
	)
}

// buildMetricsFilterStatus builds status for metrics filter mode.
//
// Should be guarded by the caller's check that filter input is active.
func (r *Run) buildMetricsFilterStatus() string {
	return fmt.Sprintf(
		"Filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		r.metricsGrid.FilterMode().String(),
		r.metricsGrid.FilterQuery(),
		string(mediumShadeBlock),
		r.metricsGrid.FilteredChartCount(), r.metricsGrid.ChartCount())
}

func (r *Run) buildSystemMetricsFilterStatus() string {
	if r.rightSidebar == nil || r.rightSidebar.metricsGrid == nil {
		return ""
	}
	grid := r.rightSidebar.metricsGrid
	return fmt.Sprintf(
		"System filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		grid.FilterMode().String(),
		grid.FilterQuery(),
		string(mediumShadeBlock),
		grid.FilteredChartCount(),
		grid.ChartCount(),
	)
}

// buildLoadingStatus builds status for loading mode.
func (r *Run) buildLoadingStatus() string {
	if r.recordsLoaded > 0 {
		return fmt.Sprintf("Loading data... [%d records, %d metrics]",
			r.recordsLoaded, r.metricsGrid.ChartCount())
	}
	return "Loading data..."
}

// buildActiveStatus builds status for active (non-loading, non-filter) mode.
func (r *Run) buildActiveStatus() string {
	var parts []string

	// Add filter info if active.
	if r.metricsGrid.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"Filter (%s): %q [%d/%d] (/ to change, Ctrl+L to clear)",
			r.metricsGrid.FilterMode().String(),
			r.metricsGrid.FilterQuery(),
			r.metricsGrid.FilteredChartCount(), r.metricsGrid.ChartCount()))
	}

	// Add overview filter info if active.
	if r.leftSidebar.IsFiltering() {
		parts = append(parts, fmt.Sprintf("Overview: %q [%s] (o to change, Ctrl+K to clear)",
			r.leftSidebar.FilterQuery(),
			r.leftSidebar.FilterInfo(),
		))
	}

	if r.rightSidebar.IsFiltering() {
		grid := r.rightSidebar.metricsGrid
		parts = append(parts, fmt.Sprintf(
			"System filter (%s): %q [%d/%d] (\\ to change, Ctrl+\\ to clear)",
			grid.FilterMode().String(),
			grid.FilterQuery(),
			grid.FilteredChartCount(),
			grid.ChartCount(),
		))
	}

	// Add selected overview item if sidebar is visible.
	if r.leftSidebar.IsVisible() {
		key, value := r.leftSidebar.SelectedItem()
		if key != "" {
			parts = append(parts, fmt.Sprintf("%s: %s", key, value))
		}
	}

	if r.mediaPane.Active() {
		if label := r.mediaPane.StatusLabel(); label != "" {
			parts = append(parts, label)
		}
	}

	// Add focused chart name if a chart is focused.
	focusedTitle := r.FocusedTitle()
	if focusedTitle != "" {
		parts = append(parts, focusedTitle)
		switch r.focus.Type {
		case FocusMainChart:
			if scaleLabel := r.metricsGrid.focusedChartScaleLabel(); scaleLabel != "" {
				parts = append(parts, scaleLabel)
			}
		case FocusSystemChart:
			if detail := r.rightSidebar.metricsGrid.FocusedChartTitleDetail(); detail != "" {
				parts = append(parts, detail)
			}
			if viewMode := r.rightSidebar.FocusedChartViewModeLabel(); viewMode != "" {
				parts = append(parts, viewMode)
			}
			if scaleLabel := r.rightSidebar.metricsGrid.FocusedChartScaleLabel(); scaleLabel != "" {
				parts = append(parts, scaleLabel)
			}
		}
	}

	if len(parts) == 0 {
		return ""
	}

	return strings.Join(parts, " • ")
}

// buildHelpText builds the help text for the status bar.
func (r *Run) buildHelpText() string {
	if r.metricsGrid.IsFilterMode() ||
		r.leftSidebar.IsFilterMode() ||
		r.rightSidebar.IsFilterMode() {
		return ""
	}
	return "h: help"
}

func (r *Run) IsFiltering() bool {
	return r.metricsGrid.IsFilterMode() ||
		r.leftSidebar.IsFilterMode() ||
		r.rightSidebar.IsFilterMode()
}

func (r *Run) MediaFullscreen() bool {
	r.stateMu.RLock()
	defer r.stateMu.RUnlock()
	return r.mediaPane != nil && r.mediaPane.IsFullscreen()
}

func (r *Run) updateBottomPaneHeights(mediaVisible, logsVisible bool) {
	metricsVisible := r.metricsGridAnimState.TargetVisible()

	// Compute separator count from the visibility state we're configuring toward.
	sectionCount := 0
	if metricsVisible {
		sectionCount++
	}
	if mediaVisible {
		sectionCount++
	}
	if logsVisible {
		sectionCount++
	}
	sepLines := max(sectionCount-1, 0)

	maxH := max(r.height-StatusBarHeight-sepLines, 0)
	lowerCount := 0
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
	if mediaVisible {
		r.mediaPane.SetExpandedHeight(each)
	}
	if logsVisible {
		r.consoleLogsPane.SetExpandedHeight(each)
	}
}

// Layout represents the computed layout dimensions for the main UI.
type Layout struct {
	leftSidebarWidth       int
	mainContentAreaWidth   int
	rightSidebarWidth      int
	totalContentAreaHeight int
	height                 int
	systemMetricsY         int
	systemMetricsHeight    int
	mediaY                 int
	mediaHeight            int
	consoleLogsY           int
	consoleLogsHeight      int
}

// effectiveSidebarWidths returns the widths that can actually be rendered
// without starving the main content area.
//
// The visibility preferences remain unchanged: this method only clamps the
// current render/layout pass and does not mutate animation state.
func (r *Run) effectiveSidebarWidths() (leftW, rightW int) {
	const minRunMainContentWidth = 10

	leftW = r.leftSidebar.Width()
	rightW = r.rightSidebar.Width()

	if leftW+rightW < r.width-minRunMainContentWidth {
		return leftW, rightW
	}
	if rightW > 0 {
		rightW = 0
	}
	if leftW+rightW < r.width-minRunMainContentWidth {
		return leftW, rightW
	}
	if leftW > 0 {
		leftW = 0
	}
	return leftW, rightW
}

// computeViewports returns (leftW, contentW, rightW, contentH).
func (r *Run) computeViewports() Layout {
	leftW, rightW := r.effectiveSidebarWidths()
	contentW := max(r.width-leftW-rightW, 1)
	totalH := max(r.height-StatusBarHeight, 0)

	stack := computeVerticalStackLayout(
		totalH,
		stackSectionSpec{
			ID:      stackSectionMetrics,
			Visible: r.metricsGridAnimState.IsVisible(),
			Flex:    true},
		stackSectionSpec{
			ID:      stackSectionMedia,
			Visible: r.mediaPane.IsVisible(),
			Height:  r.mediaPane.Height()},
		stackSectionSpec{
			ID:      stackSectionConsoleLogs,
			Visible: r.consoleLogsPane.IsVisible(),
			Height:  r.consoleLogsPane.Height()},
	)

	return Layout{
		leftSidebarWidth:       leftW,
		mainContentAreaWidth:   contentW,
		rightSidebarWidth:      rightW,
		totalContentAreaHeight: totalH,
		height:                 stack.Height(stackSectionMetrics),
		mediaY:                 stack.Y(stackSectionMedia),
		mediaHeight:            stack.Height(stackSectionMedia),
		consoleLogsY:           stack.Y(stackSectionConsoleLogs),
		consoleLogsHeight:      stack.Height(stackSectionConsoleLogs),
	}
}

// Cleanup releases resources held by the RunModel.
//
// Called when switching to workspace view.
func (r *Run) Cleanup() {
	r.stateMu.Lock()
	defer r.stateMu.Unlock()

	if r.heartbeatMgr != nil {
		r.heartbeatMgr.Stop()
	}
	if r.watcherMgr != nil {
		r.watcherMgr.Finish()
	}
	if r.historySource != nil {
		r.historySource.Close()
	}
}

// timeit logs a debug timing line on exit for the given scope.
func timeit(logger *observability.CoreLogger, scope string) func() {
	start := time.Now()
	return func() {
		logger.Debug(fmt.Sprintf("perf: %s took %s", scope, time.Since(start)))
	}
}
