package leet

import (
	"fmt"
	"runtime/debug"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/watcher"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type RunState int32

const (
	RunStateRunning RunState = iota
	RunStateFinished
	RunStateFailed
	RunStateCrashed
)

// Model describes the application state.
//
// NOTE: Bubble Tea programs are comprised of a model and three methods on it:
//   - Init returns an initial command for the application to run.
//   - Update handles incoming events and updates the model accordingly.
//   - View renders the UI based on the data in the model.
type Model struct {
	// Configuration.
	config *ConfigManager

	// Help screen.
	help *HelpModel

	// Main metrics charts grid.
	*metrics

	// Overview filter state.
	overviewFilterMode  bool   // Whether we're typing an overview filter
	overviewFilterInput string // The current overview filter being typed

	// Main view size.
	width  int
	height int

	fileComplete   bool
	isLoading      bool
	runState       RunState
	runPath        string
	reader         *WandbReader
	watcher        watcher.Watcher
	watcherStarted bool
	sidebar        *Sidebar
	rightSidebar   *RightSidebar
	runOverview    RunOverview
	runConfig      *runconfig.RunConfig
	runEnvironment *runenvironment.RunEnvironment
	runSummary     *runsummary.RunSummary

	// msgChan is the channel to receive watcher callbacks.
	msgChan chan tea.Msg

	// Sidebar animation synchronization.
	animationMu sync.Mutex
	animating   bool

	// Reload state management.
	reloadInProgress bool
	reloadMu         sync.Mutex

	// Loading progress.
	recordsLoaded int
	loadStartTime time.Time

	// logger is the debug logger for the application.
	logger *observability.CoreLogger

	// Config key handling state to set the grid size of the (system) charts section.
	waitingForConfigKey bool
	configKeyType       string // "c", "r", "C", "R"

	// Heartbeat for live runs.
	heartbeatTimer    *time.Timer
	heartbeatInterval time.Duration
	heartbeatMu       sync.Mutex

	// Coalesce expensive redraws during batch processing.
	suppressDraw bool

	// Serialize access to Update / broad model state.
	stateMu sync.RWMutex
}

func NewModel(runPath string, logger *observability.CoreLogger) *Model {
	logger.Info(fmt.Sprintf("model: creating new model for runPath: %s", runPath))

	cfg := GetConfig()
	if err := cfg.Load(); err != nil {
		logger.CaptureError(fmt.Errorf("model: failed to load config: %v", err))
	}

	// Get heartbeat interval from config
	heartbeatInterval := cfg.GetHeartbeatInterval()
	logger.Info(fmt.Sprintf("model: heartbeat interval set to %v", heartbeatInterval))

	m := &Model{
		config:              cfg,
		help:                NewHelp(),
		metrics:             newMetrics(cfg),
		overviewFilterMode:  false,
		overviewFilterInput: "",
		fileComplete:        false,
		isLoading:           true,
		runPath:             runPath,
		sidebar:             NewSidebar(cfg),
		rightSidebar:        NewRightSidebar(cfg, logger),
		watcher:             watcher.New(watcher.Params{Logger: logger}),
		watcherStarted:      false,
		runConfig:           runconfig.New(),
		runSummary:          runsummary.New(),
		msgChan:             make(chan tea.Msg, 4096),
		logger:              logger,
		heartbeatInterval:   heartbeatInterval,
	}

	m.sidebar.SetRunOverview(RunOverview{
		RunPath: runPath,
	})

	return m
}

// Init initializes the app model and returns the initial command for the application to run.
//
// Required to implement tea.Model.
func (m *Model) Init() tea.Cmd {
	m.logger.Debug("model: Init called")
	return tea.Batch(
		windowTitleCmd(), // build-tagged shim (no-op under -race)
		InitializeReader(m.runPath),
		m.waitForWatcherMsg(),
	)
}

// Update handles incoming events and updates the model accordingly.
//
// Required to implement tea.Model.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	// Safety + serialization.
	defer m.recoverPanic("Update")
	m.stateMu.Lock()
	defer m.stateMu.Unlock()

	m.logger.Debug(fmt.Sprintf("model: Update received message: %T", msg))

	// Keep help sized correctly on resize.
	if ws, ok := msg.(tea.WindowSizeMsg); ok {
		m.help.SetSize(ws.Width, ws.Height)
	}

	// Handle help toggle and help-active routing first.
	if newM, cmd, handled := m.handleHelp(msg); handled {
		return newM, cmd
	}

	var cmds []tea.Cmd

	// Route only UI/animation messages to child models.
	if isUIMsg(msg) {
		if updatedSidebar, cmd := m.updateLeftSidebar(msg); cmd != nil {
			m.sidebar = updatedSidebar
			cmds = append(cmds, cmd)
		}
		if updatedRightSidebar, cmd := m.updateRightSidebar(msg); cmd != nil {
			m.rightSidebar = updatedRightSidebar
			cmds = append(cmds, cmd)
		}
	}

	// Dispatch all messages (UI + data/control) through a single, testable router.
	cmds = append(cmds, m.dispatch(msg)...)

	return m, tea.Batch(cmds...)
}

// isUIMsg returns true for messages that should flow to child view models.
func isUIMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case tea.KeyMsg, tea.MouseMsg, tea.WindowSizeMsg, SidebarAnimationMsg, RightSidebarAnimationMsg:
		return true
	default:
		return false
	}
}

// handleHelp centralizes help toggle and routing while active.
// Returns (model, cmd, handled).
func (m *Model) handleHelp(msg tea.Msg) (tea.Model, tea.Cmd, bool) {
	// Toggle help early for h/?
	if km, ok := msg.(tea.KeyMsg); ok {
		switch km.String() {
		case "h", "?":
			m.help.Toggle()
			return m, nil, true
		}
	}

	// When help is active, let it fully handle key/mouse, then short-circuit.
	if m.help.IsActive() {
		switch msg.(type) {
		case tea.KeyMsg, tea.MouseMsg:
			var cmd tea.Cmd
			m.help, cmd = m.help.Update(msg)
			return m, cmd, true
		}
	}

	return m, nil, false
}

// updateLeftSidebar updates the left sidebar only for UI/animation messages.
func (m *Model) updateLeftSidebar(msg tea.Msg) (*Sidebar, tea.Cmd) {
	updated, cmd := m.sidebar.Update(msg)
	return updated, cmd
}

// updateRightSidebar updates the right sidebar only for UI/animation messages.
func (m *Model) updateRightSidebar(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	updated, cmd := m.rightSidebar.Update(msg)
	return updated, cmd
}

// isReloading is a convenience guard for dropping late chunks/batches.
func (m *Model) isReloading() bool {
	m.reloadMu.Lock()
	defer m.reloadMu.Unlock()
	return m.reloadInProgress
}

// dispatch routes all message types after UI children had a chance to update.
func (m *Model) dispatch(msg tea.Msg) []tea.Cmd {
	switch t := msg.(type) {
	case InitMsg:
		return m.onInit(t)

	case ChunkedBatchMsg:
		return m.onChunkedBatch(t)

	case BatchedRecordsMsg:
		return m.onBatched(t)

	case ReloadMsg:
		return m.onReload()

	case HeartbeatMsg:
		return m.onHeartbeat()

	case FileChangedMsg:
		return m.onFileChange()

	case tea.KeyMsg:
		_, cmd := m.handleKeyMsg(t) // model-level key handling (filters, toggles, etc.)
		if cmd != nil {
			return []tea.Cmd{cmd}
		}
		return nil

	case tea.MouseMsg, tea.WindowSizeMsg, SidebarAnimationMsg, RightSidebarAnimationMsg:
		_, cmd := m.handleOther(msg) // window size, animations, mouse -> model-level sizing/redraw
		if cmd != nil {
			return []tea.Cmd{cmd}
		}
		return nil

	default:
		// History/Run/Summary/Stats/SystemInfo/FileComplete/Error -> data handlers.
		var cmd tea.Cmd
		_, cmd = m.processRecordMsg(msg)
		if cmd != nil {
			return []tea.Cmd{cmd}
		}
		return nil
	}
}

// View renders the UI based on the data in the model.
//
// Required to implement tea.Model.
func (m *Model) View() string {
	// Attempt to recover from any panics in View.
	defer m.recoverPanic("View")
	m.stateMu.RLock()
	defer m.stateMu.RUnlock()

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	// Show loading screen if still loading
	if m.isLoading {
		return m.renderLoadingScreen()
	}

	// Show help screen if active
	if m.help.IsActive() {
		helpView := m.help.View()
		statusBar := m.renderStatusBar()

		// Ensure we use exact height
		content := lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
		return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, content)
	}

	// Get sidebar widths (ensure they're valid)
	leftWidth := m.sidebar.Width()
	rightWidth := m.rightSidebar.Width()

	// Sanity check widths
	if leftWidth < 0 {
		leftWidth = 0
	}
	if rightWidth < 0 {
		rightWidth = 0
	}

	// Ensure we have enough space for content
	totalSidebarWidth := leftWidth + rightWidth
	if totalSidebarWidth >= m.width-10 { // Leave at least 10 chars for content
		// Sidebars are too wide, force collapse one
		if rightWidth > 0 {
			m.rightSidebar.state = SidebarCollapsed
			m.rightSidebar.currentWidth = 0
			rightWidth = 0
		}
		if leftWidth+10 >= m.width {
			m.sidebar.state = SidebarCollapsed
			m.sidebar.currentWidth = 0
			leftWidth = 0
		}
	}

	// Calculate available space for charts (subtract 2 for margins)
	availableWidth := m.width - leftWidth - rightWidth - 2
	if availableWidth < MinChartWidth {
		availableWidth = MinChartWidth
	}

	availableHeight := m.height - StatusBarHeight
	dims := CalculateChartDimensions(availableWidth, availableHeight)

	// Render main content
	gridView := m.renderGrid(dims)

	// Build the main view based on sidebar visibility
	var mainView string

	if leftWidth > 0 || rightWidth > 0 {
		leftSidebarView := ""
		rightSidebarView := ""

		if leftWidth > 0 {
			leftSidebarView = m.sidebar.View(m.height - StatusBarHeight - 2)
		}
		if rightWidth > 0 {
			rightSidebarView = m.rightSidebar.View(m.height - StatusBarHeight)
		}

		switch {
		case leftWidth > 0 && rightWidth > 0:
			mainView = lipgloss.JoinHorizontal(
				lipgloss.Top,
				leftSidebarView,
				gridView,
				rightSidebarView,
			)
		case leftWidth > 0:
			mainView = lipgloss.JoinHorizontal(
				lipgloss.Top,
				leftSidebarView,
				gridView,
			)
		case rightWidth > 0:
			mainView = lipgloss.JoinHorizontal(
				lipgloss.Top,
				gridView,
				rightSidebarView,
			)
		}
	} else {
		mainView = gridView
	}

	// Render status bar
	statusBar := m.renderStatusBar()

	// Combine main view and status bar, ensuring exact height
	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)

	// Place the view to ensure it fills the terminal exactly
	return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, fullView)
}

// recoverPanic recovers from panics and logs them
func (m *Model) recoverPanic(context string) {
	if r := recover(); r != nil {
		stackTrace := string(debug.Stack())
		m.logger.CaptureError(fmt.Errorf("PANIC in %s: %v\nStack trace:\n%s", context, r, stackTrace))

		// Set the run state to crashed
		m.runState = RunStateCrashed

		// Try to clean up
		if m.watcherStarted {
			m.watcher.Finish()
			m.watcherStarted = false
		}
		if m.reader != nil {
			m.reader.Close()
		}
		// Stop heartbeat
		m.stopHeartbeat()
	}
}

// startHeartbeat starts the heartbeat timer for live runs
func (m *Model) startHeartbeat() {
	m.heartbeatMu.Lock()
	defer m.heartbeatMu.Unlock()

	// Stop any existing timer
	if m.heartbeatTimer != nil {
		m.heartbeatTimer.Stop()
	}

	// Only start heartbeat for live runs
	if m.runState != RunStateRunning || m.fileComplete {
		m.logger.Debug("model: not starting heartbeat - run not active")
		return
	}

	m.logger.Debug(fmt.Sprintf("model: starting heartbeat with interval %v", m.heartbeatInterval))

	// Create a new timer
	m.heartbeatTimer = time.AfterFunc(m.heartbeatInterval, func() {
		// This runs in a separate goroutine
		defer m.recoverPanic("heartbeat callback")

		// Only send heartbeat if run is still active
		if m.runState == RunStateRunning && !m.fileComplete {
			select {
			case m.msgChan <- HeartbeatMsg{}:
				m.logger.Debug("model: heartbeat triggered")
			default:
				m.logger.Warn("model: msgChan full, dropping heartbeat")
			}
		}
	})
}

// resetHeartbeat resets the heartbeat timer
func (m *Model) resetHeartbeat() {
	m.heartbeatMu.Lock()
	defer m.heartbeatMu.Unlock()

	// Stop existing timer
	if m.heartbeatTimer != nil {
		m.heartbeatTimer.Stop()
	}

	// Only restart if run is still active
	if m.runState != RunStateRunning || m.fileComplete {
		return
	}

	m.logger.Debug("model: resetting heartbeat timer")

	// Start a new timer
	m.heartbeatTimer = time.AfterFunc(m.heartbeatInterval, func() {
		defer m.recoverPanic("heartbeat callback")

		if m.runState == RunStateRunning && !m.fileComplete {
			select {
			case m.msgChan <- HeartbeatMsg{}:
				m.logger.Debug("model: heartbeat triggered after reset")
			default:
				m.logger.Warn("model: msgChan full, dropping heartbeat after reset")
			}
		}
	})
}

// stopHeartbeat stops the heartbeat timer
func (m *Model) stopHeartbeat() {
	m.heartbeatMu.Lock()
	defer m.heartbeatMu.Unlock()

	if m.heartbeatTimer != nil {
		m.heartbeatTimer.Stop()
		m.heartbeatTimer = nil
		m.logger.Debug("model: heartbeat stopped")
	}
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen
func (m *Model) renderLoadingScreen() string {
	artStyle := lipgloss.NewStyle().
		Foreground(wandbColor).
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

// renderStatusBar creates the status bar
//
//gocyclo:ignore
func (m *Model) renderStatusBar() string {
	// Left side content
	statusText := ""
	switch {
	case m.overviewFilterMode:
		// Show overview filter input
		filterInfo := m.sidebar.GetFilterInfo()
		if filterInfo == "" {
			filterInfo = "no matches"
		}
		statusText = fmt.Sprintf(" Overview filter: [%s_ [%s] (@e/@c/@s for sections • Enter to apply)",
			m.overviewFilterInput, filterInfo)
	case m.filterMode:
		// Show chart filter input with cursor
		matchCount := m.getFilteredChartCount()
		m.chartMu.RLock()
		totalCount := len(m.allCharts)
		m.chartMu.RUnlock()
		statusText = fmt.Sprintf(" Filter: /%s_ [%d/%d matches] (Enter to apply)",
			m.filterInput, matchCount, totalCount)
	case m.waitingForConfigKey:
		// Show config hint
		switch m.configKeyType {
		case "c":
			statusText = " Press 1-9 to set metrics columns (ESC to cancel)"
		case "r":
			statusText = " Press 1-9 to set metrics rows (ESC to cancel)"
		case "C":
			statusText = " Press 1-9 to set system columns (ESC to cancel)"
		case "R":
			statusText = " Press 1-9 to set system rows (ESC to cancel)"
		}
	case m.isLoading:
		// Show loading progress
		m.chartMu.RLock()
		chartCount := len(m.allCharts)
		m.chartMu.RUnlock()

		if m.recordsLoaded > 0 {
			statusText = fmt.Sprintf(" Loading data... [%d records, %d metrics]",
				m.recordsLoaded, chartCount)
		} else {
			statusText = " Loading data..."
		}
	default:
		// Add filter info if active (separated with a bullet point)
		if m.activeFilter != "" {
			m.chartMu.RLock()
			filteredCount := len(m.filteredCharts)
			totalCount := len(m.allCharts)
			m.chartMu.RUnlock()
			statusText = fmt.Sprintf(" Filter: \"%s\" [%d/%d] (/ to change, Ctrl+L to clear)",
				m.activeFilter, filteredCount, totalCount)
		}

		// Add overview filter info if active
		if m.sidebar.IsFiltering() {
			filterInfo := m.sidebar.GetFilterInfo()
			if statusText != "" {
				statusText += " •"
			}
			statusText += fmt.Sprintf(" Overview: \"%s\" [%s] ([ to change, Ctrl+K to clear)",
				m.sidebar.GetFilterQuery(), filterInfo)
		}

		// Add selected overview item if sidebar is visible (no truncation)
		if m.sidebar.IsVisible() {
			key, value := m.sidebar.GetSelectedItem()
			if key != "" {
				if statusText != "" {
					statusText += " •"
				}
				statusText += fmt.Sprintf(" %s: %s", key, value)
			}
		}

		// Add focused metric name if a chart is focused
		if m.focusedTitle != "" {
			if statusText != "" {
				statusText += " •"
			}
			statusText += fmt.Sprintf(" %s", m.focusedTitle)
		}

		// If nothing else to show, add a space to prevent empty status
		if statusText == "" {
			statusText = " "
		}
	}

	// Add buffer status if channel is getting full
	bufferUsage := len(m.msgChan)
	bufferCapacity := cap(m.msgChan)
	if bufferUsage > bufferCapacity*3/4 {
		statusText += fmt.Sprintf(" [Buffer: %d/%d]", bufferUsage, bufferCapacity)
	}

	// Right side content - simplified
	helpText := ""
	if !m.filterMode && !m.overviewFilterMode {
		helpText = "h: help "
	}

	// Calculate padding to fill the entire width
	statusLen := lipgloss.Width(statusText)
	helpLen := lipgloss.Width(helpText)
	paddingLen := m.width - statusLen - helpLen
	if paddingLen < 1 {
		paddingLen = 1
	}
	padding := strings.Repeat(" ", paddingLen)

	// Combine all parts
	fullStatus := statusText + padding + helpText

	// Apply the status bar style to the full width
	return statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(fullStatus)
}

// waitForWatcherMsg returns a command that waits for messages from the watcher
func (m *Model) waitForWatcherMsg() tea.Cmd {
	return func() tea.Msg {
		// Recover from panics in the watcher goroutine
		defer m.recoverPanic("waitForWatcherMsg")

		m.logger.Debug("model: waiting for watcher message...")
		msg := <-m.msgChan
		if msg != nil {
			m.logger.Debug(fmt.Sprintf("model: received watcher message: %T", msg))
		}
		return msg
	}
}

// startWatcher starts watching the file for changes
func (m *Model) startWatcher() error {
	m.logger.Debug(fmt.Sprintf("model: startWatcher called for path: %s", m.runPath))
	m.watcherStarted = true

	err := m.watcher.Watch(m.runPath, func() {
		// This callback runs in a separate goroutine
		defer m.recoverPanic("watcher callback")

		m.logger.Debug(fmt.Sprintf("model: watcher callback triggered! File changed: %s", m.runPath))

		// Try to send the message, but don't block.
		select {
		case m.msgChan <- FileChangedMsg{}:
			m.logger.Debug("model: FileChangedMsg sent to channel")
		default:
			m.logger.CaptureWarn("model: msgChan is full, dropping FileChangedMsg")
		}
	})

	if err != nil {
		m.logger.CaptureError(fmt.Errorf("model: error in watcher.Watch: %v", err))
		m.watcherStarted = false
		return err
	}

	m.logger.Debug("model: watcher registered successfully")
	return nil
}

// reloadCharts resets all charts and reloads data
func (m *Model) reloadCharts() tea.Cmd {
	// Check and mark reload as in progress immediately.
	m.reloadMu.Lock()
	if m.reloadInProgress {
		m.reloadMu.Unlock()
		m.logger.Debug("model: reload already in progress, ignoring")
		return nil
	}
	m.reloadInProgress = true
	m.reloadMu.Unlock()

	// Save current filter
	savedFilter := m.activeFilter

	m.isLoading = true
	m.runState = RunStateRunning // Reset from crashed state if applicable

	m.chartMu.Lock()
	m.allCharts = make([]*EpochLineChart, 0)
	m.chartsByName = make(map[string]*EpochLineChart)
	m.filteredCharts = make([]*EpochLineChart, 0)
	m.chartMu.Unlock()

	m.totalPages = 0
	m.currentPage = 0

	// Clear focus state
	m.clearFocus()

	// Reset system metrics
	m.rightSidebar.Reset()

	// Restore filter after reset
	m.activeFilter = savedFilter

	// Update chart sizes
	m.updateChartSizes()
	m.loadCurrentPage()

	return func() tea.Msg {
		return ReloadMsg{}
	}
}

// clearFocus removes focus from all charts (backward compatibility wrapper)
func (m *Model) clearFocus() {
	m.clearAllFocus()
}

// navigatePage changes the current page
func (m *Model) navigatePage(direction int) {
	if m.totalPages <= 1 {
		return
	}
	m.clearAllFocus() // Clear focus when changing pages
	m.currentPage += direction
	if m.currentPage < 0 {
		m.currentPage = m.totalPages - 1
	} else if m.currentPage >= m.totalPages {
		m.currentPage = 0
	}
	m.loadCurrentPage()
	m.drawVisibleCharts()
}

// rebuildGrids rebuilds the chart grids with new dimensions.
func (m *Model) rebuildGrids() {
	gridRows, gridCols := m.config.GetMetricsGrid()

	m.charts = make([][]*EpochLineChart, gridRows)
	for row := 0; row < gridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, gridCols)
	}

	// Recalculate total pages
	chartsPerPage := gridRows * gridCols

	m.chartMu.RLock()
	chartCount := len(m.allCharts)
	m.chartMu.RUnlock()

	m.totalPages = (chartCount + chartsPerPage - 1) / chartsPerPage

	// Ensure current page is valid
	if m.currentPage >= m.totalPages && m.totalPages > 0 {
		m.currentPage = m.totalPages - 1
	}

	// Rebuild system metrics grid if sidebar is initialized
	if m.rightSidebar != nil && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.RebuildGrid()
	}

	// Clear focus state when resizing
	m.clearAllFocus()
}
