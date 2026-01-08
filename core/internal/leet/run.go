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
	keyMap map[string]func(*Run, tea.KeyMsg) (*Run, tea.Cmd)

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
	leftSidebar  *LeftSidebar
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
	logger.Info(fmt.Sprintf("model: creating new run model for runPath: %s", runPath))

	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	heartbeatInterval := cfg.HeartbeatInterval()
	logger.Info(fmt.Sprintf("model: heartbeat interval set to %v", heartbeatInterval))

	focus := NewFocus()
	ch := make(chan tea.Msg, 4096)

	return &Run{
		config:       cfg,
		keyMap:       buildKeyMap(),
		focus:        focus,
		isLoading:    true,
		runPath:      runPath,
		metricsGrid:  NewMetricsGrid(cfg, focus, logger),
		leftSidebar:  NewLeftSidebar(cfg),
		rightSidebar: NewRightSidebar(cfg, focus, logger),
		watcherMgr:   NewWatcherManager(ch, logger),
		heartbeatMgr: NewHeartbeatManager(heartbeatInterval, ch, logger),
		logger:       logger,
	}
}

// Init initializes the model and returns the initial command.
//
// Implements tea.Model.Init.
func (m *Run) Init() tea.Cmd {
	m.logger.Debug("model: Init called")
	return tea.Batch(
		windowTitleCmd(),
		InitializeReader(m.runPath, m.logger),
		m.watcherMgr.WaitForMsg,
	)
}

// Update handles incoming events and updates the model accordingly.
//
// Implements tea.Model.Update.
func (m *Run) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	defer m.logPanic("Update")
	defer timeit(m.logger, "Model.Update")()
	m.stateMu.Lock()
	defer m.stateMu.Unlock()

	var cmds []tea.Cmd

	// Forward UI messages to children if not in filter mode.
	if isUIMsg(msg) && !m.metricsGrid.IsFilterMode() && !m.leftSidebar.IsFilterMode() {
		if s, c := m.leftSidebar.Update(msg); c != nil {
			m.leftSidebar = s
			cmds = append(cmds, c)
		}
		if rs, c := m.rightSidebar.Update(msg); c != nil {
			m.rightSidebar = rs
			cmds = append(cmds, c)
		}
	}

	// Route message to appropriate handler.
	switch t := msg.(type) {
	case tea.KeyMsg:
		newM, c := m.handleKeyMsg(t)
		if c != nil {
			cmds = append(cmds, c)
		}
		return newM, tea.Batch(cmds...)

	case tea.MouseMsg:
		newM, c := m.handleMouseMsg(t)
		if c != nil {
			cmds = append(cmds, c)
		}
		return newM, tea.Batch(cmds...)

	case tea.WindowSizeMsg:
		m.handleWindowResize(t)
		return m, tea.Batch(cmds...)

	default:
		cmds = append(cmds, m.dispatch(msg)...)
		return m, tea.Batch(cmds...)
	}
}

// handleWindowResize handles window resize messages.
func (m *Run) handleWindowResize(msg tea.WindowSizeMsg) {
	m.width, m.height = msg.Width, msg.Height

	m.leftSidebar.UpdateDimensions(msg.Width, m.rightSidebar.IsVisible())
	m.rightSidebar.UpdateDimensions(msg.Width, m.leftSidebar.IsVisible())

	layout := m.computeViewports()
	m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)
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
func (m *Run) dispatch(msg tea.Msg) []tea.Cmd {
	switch t := msg.(type) {
	case InitMsg:
		return m.handleInit(t)
	case ChunkedBatchMsg:
		return m.handleChunkedBatch(t)
	case BatchedRecordsMsg:
		return m.handleBatched(t)
	case HeartbeatMsg:
		return m.handleHeartbeat()
	case FileChangedMsg:
		return m.handleFileChange()
	case tea.WindowSizeMsg:
		m.handleWindowResize(t)
	case LeftSidebarAnimationMsg, RightSidebarAnimationMsg:
		return m.handleSidebarAnimation(msg)
	default:
		// History/Run/Summary/Stats/SystemInfo/FileComplete/Error
		if _, cmd := m.handleRecordMsg(msg); cmd != nil {
			return []tea.Cmd{cmd}
		}
	}
	return nil
}

// FocusedTitle returns the title of the currently focused chart.
func (m *Run) FocusedTitle() string {
	if m.focus.Type != FocusNone {
		return m.focus.Title
	}
	return ""
}

// View renders the UI based on the data in the model.
//
// Implements tea.Model.View.
func (m *Run) View() string {
	defer m.logPanic("View")

	m.stateMu.RLock()
	defer m.stateMu.RUnlock()

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	if m.isLoading {
		return m.renderLoadingScreen()
	}

	return m.renderMainView()
}

// renderMainView renders the main application view.
func (m *Run) renderMainView() string {
	layout := m.computeViewports()
	dims := m.metricsGrid.CalculateChartDimensions(layout.mainContentAreaWidth, layout.height)
	gridView := m.metricsGrid.View(dims)

	leftWidth := m.leftSidebar.Width()
	rightWidth := m.rightSidebar.Width()

	const minMainContentWidth = 10

	// Ensure sidebars don't take up too much space.
	totalSidebarWidth := leftWidth + rightWidth
	if totalSidebarWidth >= m.width-minMainContentWidth {
		if rightWidth > 0 {
			m.rightSidebar.animState.currentWidth = 0
			rightWidth = 0
		}
		if leftWidth+minMainContentWidth >= m.width {
			m.leftSidebar.animState.currentWidth = 0
			leftWidth = 0
		}
	}

	mainView := m.buildMainViewWithSidebars(gridView, leftWidth, rightWidth)
	statusBar := m.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, fullView)
}

// buildMainViewWithSidebars builds the main view with sidebars.
func (m *Run) buildMainViewWithSidebars(gridView string, leftWidth, rightWidth int) string {
	if leftWidth == 0 && rightWidth == 0 {
		return gridView
	}

	var parts []string

	if leftWidth > 0 {
		leftView := m.leftSidebar.View(m.height - StatusBarHeight - 2)
		parts = append(parts, leftView)
	}

	parts = append(parts, gridView)

	if rightWidth > 0 {
		rightView := m.rightSidebar.View(m.height - StatusBarHeight)
		parts = append(parts, rightView)
	}

	return lipgloss.JoinHorizontal(lipgloss.Top, parts...)
}

// ShouldRestart reports whether the user requested a full restart.
func (m *Run) ShouldRestart() bool {
	return m.shouldRestart
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
func (m *Run) isRunning() bool {
	return m.runState == RunStateRunning
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen.
func (m *Run) renderLoadingScreen() string {
	artStyle := lipgloss.NewStyle().
		Foreground(colorHeading).
		Bold(true)

	logoContent := lipgloss.JoinVertical(
		lipgloss.Center,
		artStyle.Render(wandbArt),
		artStyle.Render(leetArt),
	)

	centeredLogo := lipgloss.Place(
		m.width,
		m.height-StatusBarHeight,
		lipgloss.Center,
		lipgloss.Center,
		logoContent,
	)

	statusBar := m.renderStatusBar()
	return lipgloss.JoinVertical(lipgloss.Left, centeredLogo, statusBar)
}

// renderStatusBar creates the status bar.
func (m *Run) renderStatusBar() string {
	statusText := m.buildStatusText()
	helpText := m.buildHelpText()

	innerWidth := max(m.width-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(fullStatus)
}

// buildStatusText builds the main status text.
func (m *Run) buildStatusText() string {
	if m.leftSidebar.IsFilterMode() {
		return m.buildOverviewFilterStatus()
	}
	if m.metricsGrid.IsFilterMode() {
		return m.buildMetricsFilterStatus()
	}
	if m.config.IsAwaitingGridConfig() {
		return m.config.GridConfigStatus()
	}
	if m.isLoading {
		return m.buildLoadingStatus()
	}
	return m.buildActiveStatus()
}

// buildOverviewFilterStatus builds status for overview filter mode.
func (m *Run) buildOverviewFilterStatus() string {
	filterInfo := m.leftSidebar.FilterInfo()
	if filterInfo == "" {
		filterInfo = "no matches"
	}
	return fmt.Sprintf(
		"Overview filter (%s): %s%s [%s] (Enter to apply • Tab to toggle mode)",
		m.leftSidebar.FilterMode().String(),
		m.leftSidebar.FilterQuery(),
		string(mediumShadeBlock),
		filterInfo,
	)
}

// buildMetricsFilterStatus builds status for metrics filter mode.
//
// Should be guarded by the caller's check that filter input is active.
func (m *Run) buildMetricsFilterStatus() string {
	return fmt.Sprintf(
		"Filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		m.metricsGrid.FilterMode().String(),
		m.metricsGrid.FilterQuery(),
		string(mediumShadeBlock),
		m.metricsGrid.FilteredChartCount(), m.metricsGrid.ChartCount())
}

// buildLoadingStatus builds status for loading mode.
func (m *Run) buildLoadingStatus() string {
	if m.recordsLoaded > 0 {
		return fmt.Sprintf("Loading data... [%d records, %d metrics]",
			m.recordsLoaded, m.metricsGrid.ChartCount())
	}
	return "Loading data..."
}

// buildActiveStatus builds status for active (non-loading, non-filter) mode.
func (m *Run) buildActiveStatus() string {
	var parts []string

	// Add filter info if active.
	if m.metricsGrid.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"Filter (%s): \"%s\" [%d/%d] (/ to change, Ctrl+L to clear)",
			m.metricsGrid.FilterMode().String(),
			m.metricsGrid.FilterQuery(),
			m.metricsGrid.FilteredChartCount(), m.metricsGrid.ChartCount()))
	}

	// Add overview filter info if active.
	if m.leftSidebar.IsFiltering() {
		parts = append(parts, fmt.Sprintf("Overview: \"%s\" [%s] (o to change, Ctrl+K to clear)",
			m.leftSidebar.FilterQuery(),
			m.leftSidebar.FilterInfo(),
		))
	}

	// Add selected overview item if sidebar is visible.
	if m.leftSidebar.IsVisible() {
		key, value := m.leftSidebar.SelectedItem()
		if key != "" {
			parts = append(parts, fmt.Sprintf("%s: %s", key, value))
		}
	}

	// Add focused metric name if a chart is focused.
	focusedTitle := m.FocusedTitle()
	if focusedTitle != "" {
		parts = append(parts, focusedTitle)
	}

	if len(parts) == 0 {
		return ""
	}

	return strings.Join(parts, " • ")
}

// buildHelpText builds the help text for the status bar.
func (m *Run) buildHelpText() string {
	if m.metricsGrid.IsFilterMode() || m.leftSidebar.IsFilterMode() {
		return ""
	}
	return "h: help"
}

func (m *Run) IsFiltering() bool {
	return m.metricsGrid.IsFilterMode() || m.leftSidebar.IsFilterMode()
}

// Layout represents the computed layout dimensions for the main UI.
type Layout struct {
	leftSidebarWidth     int
	mainContentAreaWidth int
	rightSidebarWidth    int
	height               int
}

// computeViewports returns (leftW, contentW, rightW, contentH).
func (m *Run) computeViewports() Layout {
	leftW := m.leftSidebar.Width()
	rightW := m.rightSidebar.Width()

	contentW := max(m.width-leftW-rightW-2, 1)
	contentH := max(m.height-StatusBarHeight, 1)

	return Layout{leftW, contentW, rightW, contentH}
}

// Cleanup releases resources held by the RunModel.
//
// Called when switching to workspace view.
func (m *Run) Cleanup() {
	m.stateMu.Lock()
	defer m.stateMu.Unlock()

	if m.heartbeatMgr != nil {
		m.heartbeatMgr.Stop()
	}
	if m.watcherMgr != nil {
		m.watcherMgr.Finish()
	}
	if m.reader != nil {
		m.reader.Close()
	}
}

// timeit logs a debug timing line on exit for the given scope.
func timeit(logger *observability.CoreLogger, scope string) func() {
	start := time.Now()
	return func() {
		logger.Debug(fmt.Sprintf("perf: %s took %s", scope, time.Since(start)))
	}
}
