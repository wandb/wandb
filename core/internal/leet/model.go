package leet

import (
	"fmt"
	"runtime/debug"
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
// Implements tea.Model.
//
// NOTE: Bubble Tea programs are comprised of a model and three methods on it:
//   - Init returns an initial command for the application to run.
//   - Update handles incoming events and updates the model accordingly.
//   - View renders the UI based on the data in the model.
type Model struct {
	// Serialize access to Update / broad model state.
	stateMu sync.RWMutex

	// Configuration.
	config *ConfigManager

	// Keyboard bindings.
	keyMap map[string]func(*Model, tea.KeyMsg) (*Model, tea.Cmd)

	// Main view size.
	width, height int

	// runPath is the path to the .wandb file.
	runPath string

	// Main metrics charts grid.
	*metrics

	fileComplete   bool
	isLoading      bool
	runState       RunState
	reader         *WandbReader
	watcher        watcher.Watcher
	watcherStarted bool
	sidebar        *Sidebar
	rightSidebar   *RightSidebar
	runOverview    RunOverview
	runConfig      *runconfig.RunConfig
	runEnvironment *runenvironment.RunEnvironment
	runSummary     *runsummary.RunSummary

	// wcChan is the channel to receive watcher callbacks.
	wcChan chan tea.Msg

	// Sidebar animation synchronization.
	animationMu sync.Mutex
	animating   bool

	// Loading progress.
	recordsLoaded int
	loadStartTime time.Time

	// shouldRestart is set when the user requests a full restart (Alt+R).
	shouldRestart bool

	// Heartbeat for live runs.
	heartbeatTimer    *time.Timer
	heartbeatInterval time.Duration
	heartbeatMu       sync.Mutex

	// Coalesce expensive redraws during batch processing.
	suppressDraw bool

	// pendingGridConfig indicates which metrics/system grid dimension is awaiting user input.
	//
	// When gridConfigNone, no input is pending.
	pendingGridConfig gridConfigTarget

	// Overview filter state.
	overviewFilterMode  bool   // Whether we're typing an overview filter
	overviewFilterInput string // The current overview filter being typed

	// Help screen.
	help *HelpModel

	// logger is the debug logger for the application.
	logger *observability.CoreLogger
}

func NewModel(runPath string, cfg *ConfigManager, logger *observability.CoreLogger) *Model {
	logger.Info(fmt.Sprintf("model: creating new model for runPath: %s", runPath))

	// Get heartbeat interval from config
	heartbeatInterval := cfg.HeartbeatInterval()
	logger.Info(fmt.Sprintf("model: heartbeat interval set to %v", heartbeatInterval))

	m := &Model{
		config:              cfg,
		keyMap:              buildKeyMap(),
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
		wcChan:              make(chan tea.Msg, 4096),
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
// Implements tea.Model.Init.
func (m *Model) Init() tea.Cmd {
	m.logger.Debug("model: Init called")
	return tea.Batch(
		windowTitleCmd(),
		InitializeReader(m.runPath, m.logger),
		m.waitForWatcherMsg(),
	)
}

// Update handles incoming events and updates the model accordingly.
//
// Implements tea.Model.Update.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	defer m.logPanic("Update")
	m.stateMu.Lock()
	defer m.stateMu.Unlock()

	// 1) Help short-circuit (only thing allowed to consume the message)
	if handled, cmd := m.handleHelp(msg); handled {
		return m, cmd
	}

	var cmds []tea.Cmd

	// 2) Forward *UI/animation only* to children (never data/control)
	if isUIMsg(msg) {
		if s, c := m.sidebar.Update(msg); c != nil {
			m.sidebar = s
			cmds = append(cmds, c)
		}
		if rs, c := m.rightSidebar.Update(msg); c != nil {
			m.rightSidebar = rs
			cmds = append(cmds, c)
		}
	}

	// 3) Typed routing still runs for the same message
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
		m.width, m.height = t.Width, t.Height
		m.help.SetSize(t.Width, t.Height)

		m.sidebar.UpdateDimensions(t.Width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(t.Width, m.sidebar.IsVisible())

		m.updateChartSizes()
		return m, tea.Batch(cmds...)

	default:
		// Includes InitMsg/ChunkedBatchMsg/BatchedRecordsMsg/Heartbeat/FileChanged
		cmds = append(cmds, m.dispatch(msg)...)
		return m, tea.Batch(cmds...)
	}
}

// isUIMsg returns true for messages that should flow to child view models.
func isUIMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case tea.KeyMsg, tea.MouseMsg, tea.WindowSizeMsg,
		SidebarAnimationMsg, RightSidebarAnimationMsg:
		return true
	default:
		return false
	}
}

// handleHelp centralizes help toggle and routing while active.
func (m *Model) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	// Toggle on 'h' / '?'
	if km, ok := msg.(tea.KeyMsg); ok {
		switch km.String() {
		case "h", "?":
			m.help.Toggle()
			return true, nil
		}
	}

	// When help is visible, it owns key/mouse
	if m.help.IsActive() {
		switch msg.(type) {
		case tea.KeyMsg, tea.MouseMsg:
			updated, cmd := m.help.Update(msg)
			m.help = updated
			return true, cmd
		}
	}
	return false, nil
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
// Implements tea.Model.View.
func (m *Model) View() string {
	// Attempt to recover from any panics in View.
	defer m.logPanic("View")
	m.stateMu.RLock()
	defer m.stateMu.RUnlock()

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

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

	statusBar := m.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)

	return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, fullView)
}

// ShouldRestart reports whether the user requested a full restart.
func (m *Model) ShouldRestart() bool {
	return m.shouldRestart
}

// computeViewports returns (leftW, contentW, rightW, contentH).
// The main content area never looks at sidebars directly; it receives a viewport.
func (m *Model) computeViewports() (int, int, int, int) {
	leftW := m.sidebar.Width()
	rightW := m.rightSidebar.Width()
	if leftW < 0 {
		leftW = 0
	}
	if rightW < 0 {
		rightW = 0
	}

	contentW := m.width - leftW - rightW - 2 // margins
	_, gridCols := m.config.MetricsGrid()
	minContentW := MinChartWidth * gridCols
	if contentW < minContentW {
		contentW = minContentW
	}

	contentH := m.height - StatusBarHeight
	return leftW, contentW, rightW, contentH
}

// logPanic logs panics to Sentry before re-panicing.
func (m *Model) logPanic(context string) {
	if r := recover(); r != nil {
		stackTrace := string(debug.Stack())
		m.logger.CaptureError(fmt.Errorf("PANIC in %s: %v\nStack trace:\n%s", context, r, stackTrace))

		panic(r)
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
		defer m.logPanic("heartbeat callback")

		// Only send heartbeat if run is still active
		if m.runState == RunStateRunning && !m.fileComplete {
			select {
			case m.wcChan <- HeartbeatMsg{}:
				m.logger.Debug("model: heartbeat triggered")
			default:
				m.logger.Warn("model: wcChan full, dropping heartbeat")
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
		defer m.logPanic("heartbeat callback")

		if m.runState == RunStateRunning && !m.fileComplete {
			select {
			case m.wcChan <- HeartbeatMsg{}:
				m.logger.Debug("model: heartbeat triggered after reset")
			default:
				m.logger.Warn("model: wcChan full, dropping heartbeat after reset")
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

// renderStatusBar creates the status bar.
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
		statusText = fmt.Sprintf(" Overview filter: %s_ [%s] (@e/@c/@s for sections • Enter to apply)",
			m.overviewFilterInput, filterInfo)
	case m.filterMode:
		// Show chart filter input with cursor
		matchCount := m.getFilteredChartCount()
		m.chartMu.RLock()
		totalCount := len(m.allCharts)
		m.chartMu.RUnlock()
		statusText = fmt.Sprintf(" Filter: %s_ [%d/%d matches] (Enter to apply)",
			m.filterInput, matchCount, totalCount)
	case m.pendingGridConfig != gridConfigNone:
		// Show config hint.
		switch m.pendingGridConfig {
		case gridConfigMetricsCols:
			statusText = " Press 1-9 to set metrics grid columns (ESC to cancel)"
		case gridConfigMetricsRows:
			statusText = " Press 1-9 to set metrics grid rows (ESC to cancel)"
		case gridConfigSystemCols:
			statusText = " Press 1-9 to set system grid columns (ESC to cancel)"
		case gridConfigSystemRows:
			statusText = " Press 1-9 to set system grid rows (ESC to cancel)"
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
			statusText += fmt.Sprintf(" Overview: \"%s\" [%s] (o to change, Ctrl+K to clear)",
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
	bufferUsage := len(m.wcChan)
	bufferCapacity := cap(m.wcChan)
	if bufferUsage > bufferCapacity*3/4 {
		statusText += fmt.Sprintf(" [Buffer: %d/%d]", bufferUsage, bufferCapacity)
	}

	// Right side content
	helpText := ""
	if !m.filterMode && !m.overviewFilterMode {
		helpText = "h: help "
	}

	rightAligned := lipgloss.PlaceHorizontal(
		m.width-lipgloss.Width(statusText),
		lipgloss.Right,
		helpText,
	)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(fullStatus)
}

// waitForWatcherMsg returns a command that waits for messages from the watcher
func (m *Model) waitForWatcherMsg() tea.Cmd {
	return func() tea.Msg {
		// Recover from panics in the watcher goroutine
		defer m.logPanic("waitForWatcherMsg")

		m.logger.Debug("model: waiting for watcher message...")
		msg := <-m.wcChan
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
		defer m.logPanic("watcher callback")

		m.logger.Debug(fmt.Sprintf("model: watcher callback triggered! File changed: %s", m.runPath))

		// Try to send the message, but don't block.
		select {
		case m.wcChan <- FileChangedMsg{}:
			m.logger.Debug("model: FileChangedMsg sent to channel")
		default:
			m.logger.CaptureWarn("model: wcChan is full, dropping FileChangedMsg")
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
