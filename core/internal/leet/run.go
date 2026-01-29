package leet

import (
	"fmt"
	"runtime/debug"
	"strings"
	"sync"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

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
	keyMap map[string]func(*Run, tea.KeyMsg) tea.Cmd

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

	// Data reader.
	reader *WandbReader

	// Transaction log (.wandb file) watch and heartbeat management.
	watcherMgr   *WatcherManager
	heartbeatMgr *HeartbeatManager

	// Chart focus state.
	focus *Focus

	// UI components.
	metricsGrid  *MetricsGrid
	runOverview  *RunOverview
	leftSidebar  *RunOverviewSidebar
	rightSidebar *RightSidebar

	// Sidebar animation synchronization.
	animationMu sync.Mutex
	animating   bool

	// Loading progress.
	recordsLoaded int
	loadStartTime time.Time

	// Restart flag.
	shouldRestart bool

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
	runOverviewAnimState := NewAnimationState(cfg.LeftSidebarVisible(), SidebarMinWidth)

	metricsGrid := NewMetricsGrid(cfg, focus, logger)
	metricsGrid.SetSingleSeriesColorMode(cfg.SingleRunColorMode())

	return &Run{
		config:       cfg,
		keyMap:       buildKeyMap(RunKeyBindings()),
		focus:        focus,
		isLoading:    true,
		runPath:      runPath,
		metricsGrid:  metricsGrid,
		runOverview:  ro,
		leftSidebar:  NewRunOverviewSidebar(runOverviewAnimState, ro, SidebarSideLeft),
		rightSidebar: NewRightSidebar(cfg, focus, logger),
		watcherMgr:   NewWatcherManager(ch, logger),
		heartbeatMgr: NewHeartbeatManager(heartbeatInterval, ch, logger),
		logger:       logger,
	}
}

// Init initializes the model and returns the initial command.
//
// Implements tea.Model.Init.
func (r *Run) Init() tea.Cmd {
	r.logger.Debug("run: Init called")
	return tea.Batch(
		windowTitleCmd(),
		InitializeReader(r.runPath, r.logger),
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
		if s, c := r.leftSidebar.Update(msg); c != nil {
			r.leftSidebar = s
			cmds = append(cmds, c)
		}
		if rs, c := r.rightSidebar.Update(msg); c != nil {
			r.rightSidebar = rs
			cmds = append(cmds, c)
		}
	}

	// Route message to appropriate handler.
	switch t := msg.(type) {
	case tea.KeyMsg:
		if c := r.handleKeyMsg(t); c != nil {
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

	r.leftSidebar.UpdateDimensions(msg.Width, r.rightSidebar.IsVisible())
	r.rightSidebar.UpdateDimensions(msg.Width, r.leftSidebar.IsVisible())

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)
}

// isUIMsg returns true for messages that should flow to child view models.
func isUIMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case tea.KeyMsg, tea.MouseMsg, tea.WindowSizeMsg,
		LeftSidebarAnimationMsg, RightSidebarAnimationMsg:
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
func (r *Run) View() string {
	defer r.logPanic("View")

	r.stateMu.RLock()
	defer r.stateMu.RUnlock()

	if r.width == 0 || r.height == 0 {
		return "Loading..."
	}

	if r.isLoading {
		return r.renderLoadingScreen()
	}

	return r.renderMainView()
}

// renderMainView renders the main application view.
func (r *Run) renderMainView() string {
	layout := r.computeViewports()
	dims := r.metricsGrid.CalculateChartDimensions(layout.mainContentAreaWidth, layout.height)
	gridView := r.metricsGrid.View(dims)

	leftWidth := r.leftSidebar.Width()
	rightWidth := r.rightSidebar.Width()

	const minMainContentWidth = 10

	// Ensure sidebars don't take up too much space.
	totalSidebarWidth := leftWidth + rightWidth
	if totalSidebarWidth >= r.width-minMainContentWidth {
		if rightWidth > 0 {
			r.rightSidebar.animState.currentWidth = 0
			rightWidth = 0
		}
		if leftWidth+minMainContentWidth >= r.width {
			r.leftSidebar.animState.currentWidth = 0
			leftWidth = 0
		}
	}

	mainView := r.buildMainViewWithSidebars(gridView, leftWidth, rightWidth)
	statusBar := r.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(r.width, r.height, lipgloss.Left, lipgloss.Top, fullView)
}

// buildMainViewWithSidebars builds the main view with sidebars.
func (r *Run) buildMainViewWithSidebars(gridView string, leftWidth, rightWidth int) string {
	if leftWidth == 0 && rightWidth == 0 {
		return gridView
	}

	var parts []string

	if leftWidth > 0 {
		leftView := r.leftSidebar.View(r.height - StatusBarHeight - 2)
		parts = append(parts, leftView)
	}

	parts = append(parts, gridView)

	if rightWidth > 0 {
		rightView := r.rightSidebar.View(r.height - StatusBarHeight)
		parts = append(parts, rightView)
	}

	return lipgloss.JoinHorizontal(lipgloss.Top, parts...)
}

// ShouldRestart reports whether the user requested a full restart.
func (r *Run) ShouldRestart() bool {
	return r.shouldRestart
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

// isRunning returns whether the run is currently active.
func (r *Run) isRunning() bool {
	return r.runState == RunStateRunning
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen.
func (r *Run) renderLoadingScreen() string {
	artStyle := lipgloss.NewStyle().
		Foreground(colorHeading).
		Bold(true)

	logoContent := lipgloss.JoinVertical(
		lipgloss.Center,
		artStyle.Render(wandbArt),
		artStyle.Render(leetArt),
	)

	centeredLogo := lipgloss.Place(
		r.width,
		r.height-StatusBarHeight,
		lipgloss.Center,
		lipgloss.Center,
		logoContent,
	)

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

	// Add selected overview item if sidebar is visible.
	if r.leftSidebar.IsVisible() {
		key, value := r.leftSidebar.SelectedItem()
		if key != "" {
			parts = append(parts, fmt.Sprintf("%s: %s", key, value))
		}
	}

	// Add focused metric name if a chart is focused.
	focusedTitle := r.FocusedTitle()
	if focusedTitle != "" {
		parts = append(parts, focusedTitle)
	}

	if len(parts) == 0 {
		return ""
	}

	return strings.Join(parts, " • ")
}

// buildHelpText builds the help text for the status bar.
func (r *Run) buildHelpText() string {
	if r.metricsGrid.IsFilterMode() || r.leftSidebar.IsFilterMode() {
		return ""
	}
	return "h: help"
}

func (r *Run) IsFiltering() bool {
	return r.metricsGrid.IsFilterMode() || r.leftSidebar.IsFilterMode()
}

// Layout represents the computed layout dimensions for the main UI.
type Layout struct {
	leftSidebarWidth     int
	mainContentAreaWidth int
	rightSidebarWidth    int
	height               int
}

// computeViewports returns (leftW, contentW, rightW, contentH).
func (r *Run) computeViewports() Layout {
	leftW := r.leftSidebar.Width()
	rightW := r.rightSidebar.Width()

	contentW := max(r.width-leftW-rightW-2, 1)
	contentH := max(r.height-StatusBarHeight, 1)

	return Layout{leftW, contentW, rightW, contentH}
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
	if r.reader != nil {
		r.reader.Close()
	}
}

// timeit logs a debug timing line on exit for the given scope.
func timeit(logger *observability.CoreLogger, scope string) func() {
	start := time.Now()
	return func() {
		logger.Debug(fmt.Sprintf("perf: %s took %s", scope, time.Since(start)))
	}
}
