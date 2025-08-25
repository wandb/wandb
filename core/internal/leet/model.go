//go:build !wandb_core

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

// Model represents the main application state.
type Model struct {
	help *HelpModel

	// Chart data protected by mutex
	chartMu      sync.RWMutex
	allCharts    []*EpochLineChart
	chartsByName map[string]*EpochLineChart
	// charts holds the current page of charts arranged in grid
	charts [][]*EpochLineChart

	// Filter state
	filterMode     bool              // Whether we're currently typing a filter
	filterInput    string            // The current filter being typed
	activeFilter   string            // The confirmed filter in use
	filteredCharts []*EpochLineChart // Filtered subset of charts

	// Overview filter state
	overviewFilterMode  bool   // Whether we're typing an overview filter
	overviewFilterInput string // The current overview filter being typed

	// Focus state - centralized focus management
	focusState   FocusState
	focusedTitle string // For backward compatibility and status bar display
	focusedRow   int    // For backward compatibility with existing code
	focusedCol   int    // For backward compatibility with existing code

	width          int
	height         int
	step           int
	currentPage    int
	totalPages     int
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
	// Increased buffer size for large files
	msgChan chan tea.Msg

	// File change debouncing
	lastFileChange time.Time
	debounceTimer  *time.Timer
	debounceMu     sync.Mutex

	// Animation synchronization
	animationMu sync.Mutex
	animating   bool

	// Loading progress
	recordsLoaded int
	loadStartTime time.Time

	// logger is the debug logger for the application.
	logger *observability.CoreLogger

	// Config key handling state
	waitingForConfigKey bool
	configKeyType       string // "c", "r", "C", "R"

	// Heartbeat for live runs
	heartbeatTimer    *time.Timer
	heartbeatInterval time.Duration
	heartbeatMu       sync.Mutex
}

func NewModel(runPath string, logger *observability.CoreLogger) *Model {
	logger.Info(fmt.Sprintf("model: creating new model for runPath: %s", runPath))

	// Load config first
	cfg := GetConfig()
	if err := cfg.Load(); err != nil {
		logger.Error(fmt.Sprintf("model: failed to load config: %v", err))
	}

	// Update grid dimensions from config
	UpdateGridDimensions()

	// Get heartbeat interval from config
	heartbeatInterval := cfg.GetHeartbeatInterval()
	logger.Info(fmt.Sprintf("model: heartbeat interval set to %v", heartbeatInterval))

	// Calculate initial buffer size based on expected metrics
	// Start with 1000, will grow dynamically if needed
	initialBufferSize := 1000

	m := &Model{
		help:                NewHelp(),
		allCharts:           make([]*EpochLineChart, 0),
		chartsByName:        make(map[string]*EpochLineChart),
		charts:              make([][]*EpochLineChart, GridRows),
		filteredCharts:      make([]*EpochLineChart, 0),
		filterMode:          false,
		filterInput:         "",
		activeFilter:        "",
		overviewFilterMode:  false,
		overviewFilterInput: "",
		focusState:          FocusState{Type: FocusNone},
		focusedTitle:        "",
		focusedRow:          -1,
		focusedCol:          -1,
		step:                0,
		currentPage:         0,
		totalPages:          0,
		fileComplete:        false,
		isLoading:           true,
		runPath:             runPath,
		sidebar:             NewSidebar(),
		rightSidebar:        NewRightSidebar(logger),
		watcher:             watcher.New(watcher.Params{}),
		watcherStarted:      false,
		runConfig:           runconfig.New(),
		runSummary:          runsummary.New(),
		msgChan:             make(chan tea.Msg, initialBufferSize),
		logger:              logger,
		heartbeatInterval:   heartbeatInterval,
	}

	for row := range GridRows {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	m.sidebar.SetRunOverview(RunOverview{
		RunPath: runPath,
	})

	return m
}

// matchPattern implements simple glob pattern matching that treats / as a regular character
func matchPattern(pattern, str string) bool {
	// Convert both to lowercase for case-insensitive matching
	pattern = strings.ToLower(pattern)
	str = strings.ToLower(str)

	// Handle special cases
	if pattern == "" {
		return true
	}
	if pattern == "*" {
		return true
	}

	// Simple implementation of glob matching
	pi := 0    // pattern index
	si := 0    // string index
	star := -1 // position of last * in pattern
	match := 0 // position in string matched by *

	for si < len(str) {
		switch {
		case pi < len(pattern) && (pattern[pi] == '?' || pattern[pi] == str[si]):
			// Character match or ? wildcard
			pi++
			si++
		case pi < len(pattern) && pattern[pi] == '*':
			// * wildcard - record position and try to match rest
			star = pi
			match = si
			pi++
		case star != -1:
			// Backtrack to last * and try matching one more character
			pi = star + 1
			match++
			si = match
		default:
			// No match
			return false
		}
	}

	// Check for remaining wildcards in pattern
	for pi < len(pattern) && pattern[pi] == '*' {
		pi++
	}

	return pi == len(pattern)
}

// applyFilter applies the current filter pattern to charts
func (m *Model) applyFilter(pattern string) {
	m.chartMu.Lock()
	defer m.chartMu.Unlock()

	if pattern == "" {
		// No filter, use all charts
		m.filteredCharts = m.allCharts
	} else {
		// Apply filter
		m.filteredCharts = make([]*EpochLineChart, 0)

		// If pattern has no wildcards, treat as substring match
		useSubstring := !strings.Contains(pattern, "*") && !strings.Contains(pattern, "?")

		for _, chart := range m.allCharts {
			chartTitle := chart.Title()

			var matched bool
			if useSubstring {
				// Simple substring match (case-insensitive)
				matched = strings.Contains(strings.ToLower(chartTitle), strings.ToLower(pattern))
			} else {
				// Use our custom glob matcher
				matched = matchPattern(pattern, chartTitle)
			}

			if matched {
				m.filteredCharts = append(m.filteredCharts, chart)
			}
		}
	}

	// Recalculate pages based on filtered charts
	m.totalPages = (len(m.filteredCharts) + ChartsPerPage - 1) / ChartsPerPage
	if m.currentPage >= m.totalPages && m.totalPages > 0 {
		m.currentPage = 0
	}

	m.loadCurrentPageNoLock()
}

// enterFilterMode enters filter input mode
func (m *Model) enterFilterMode() {
	m.filterMode = true
	m.filterInput = m.activeFilter // Start with current filter
}

// exitFilterMode exits filter input mode and optionally applies the filter
func (m *Model) exitFilterMode(apply bool) {
	m.filterMode = false
	if apply {
		m.activeFilter = m.filterInput
		m.applyFilter(m.activeFilter)
		m.drawVisibleCharts()
	} else {
		// Restore previous filter
		m.filterInput = m.activeFilter
		m.applyFilter(m.activeFilter)
	}
}

// clearFilter removes the active filter
func (m *Model) clearFilter() {
	m.activeFilter = ""
	m.filterInput = ""
	m.applyFilter("")
	m.drawVisibleCharts()
}

// getFilteredChartCount returns the number of charts matching the current filter
func (m *Model) getFilteredChartCount() int {
	if m.filterMode {
		// Count matches for current input
		count := 0
		pattern := m.filterInput
		if pattern == "" {
			return len(m.allCharts)
		}

		m.chartMu.RLock()
		defer m.chartMu.RUnlock()

		// If pattern has no wildcards, treat as substring match
		useSubstring := !strings.Contains(pattern, "*") && !strings.Contains(pattern, "?")

		for _, chart := range m.allCharts {
			chartTitle := chart.Title()

			var matched bool
			if useSubstring {
				// Simple substring match (case-insensitive)
				matched = strings.Contains(strings.ToLower(chartTitle), strings.ToLower(pattern))
			} else {
				// Use our custom glob matcher
				matched = matchPattern(pattern, chartTitle)
			}

			if matched {
				count++
			}
		}
		return count
	}
	return len(m.filteredCharts)
}

// recoverPanic recovers from panics and logs them
func (m *Model) recoverPanic(context string) {
	if r := recover(); r != nil {
		stackTrace := string(debug.Stack())
		m.logger.Error(fmt.Sprintf("PANIC in %s: %v\nStack trace:\n%s", context, r, stackTrace))

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

// Init implements tea.Model.
func (m *Model) Init() tea.Cmd {
	m.logger.Debug("model: Init called")
	return tea.Batch(
		tea.SetWindowTitle("wandb leet"),
		InitializeReader(m.runPath),
		m.waitForWatcherMsg(),
	)
}

// Update implements tea.Model.
//
//gocyclo:ignore
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	// Recover from any panics in Update
	defer m.recoverPanic("Update")

	var cmds []tea.Cmd

	m.logger.Debug(fmt.Sprintf("model: Update received message: %T", msg))

	// Handle window resize for help
	if msg, ok := msg.(tea.WindowSizeMsg); ok {
		m.help.SetSize(msg.Width, msg.Height)
	}

	// Check for help toggle key first
	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch keyMsg.String() {
		case "h", "?":
			m.help.Toggle()
			return m, nil
		}
	}

	// Handle help screen UI updates if active
	if m.help.IsActive() {
		switch msg.(type) {
		case tea.KeyMsg, tea.MouseMsg:
			updatedHelp, helpCmd := m.help.Update(msg)
			m.help = updatedHelp
			if helpCmd != nil {
				cmds = append(cmds, helpCmd)
			}
			return m, tea.Batch(cmds...)
		}
	}

	// Update sidebars
	updatedSidebar, sidebarCmd := m.sidebar.Update(msg)
	m.sidebar = updatedSidebar
	if sidebarCmd != nil {
		cmds = append(cmds, sidebarCmd)
	}

	updatedRightSidebar, rightSidebarCmd := m.rightSidebar.Update(msg)
	m.rightSidebar = updatedRightSidebar
	if rightSidebarCmd != nil {
		cmds = append(cmds, rightSidebarCmd)
	}

	// Handle specific message types
	switch msg := msg.(type) {
	case InitMsg:
		m.logger.Debug("model: InitMsg received, reader initialized")
		m.reader = msg.Reader
		m.loadStartTime = time.Now()
		// Start chunked reading
		return m, ReadAllRecordsChunked(m.reader)

	case ChunkedBatchMsg:
		m.logger.Debug(fmt.Sprintf("model: ChunkedBatchMsg received with %d messages, hasMore=%v",
			len(msg.Msgs), msg.HasMore))

		// Update progress
		m.recordsLoaded += msg.Progress

		// Process all messages in this chunk
		processedCount := 0
		for _, subMsg := range msg.Msgs {
			var cmd tea.Cmd
			m, cmd = m.processRecordMsg(subMsg)
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
			processedCount++
		}

		m.logger.Debug(fmt.Sprintf("model: processed %d messages from chunk", processedCount))

		// Exit loading state once we have some data to show
		m.chartMu.RLock()
		hasCharts := len(m.allCharts) > 0
		m.chartMu.RUnlock()

		if m.isLoading && hasCharts {
			m.isLoading = false
			m.logger.Info(fmt.Sprintf("model: initial data loaded, showing UI after %v",
				time.Since(m.loadStartTime)))
		}

		// Continue reading if there's more data
		if msg.HasMore {
			m.logger.Debug("model: requesting next chunk")
			cmds = append(cmds, m.reader.ReadAllRecordsChunked())
		} else {
			// All initial data loaded
			m.logger.Info(fmt.Sprintf("model: finished loading %d records in %v",
				m.recordsLoaded, time.Since(m.loadStartTime)))

			// Start watcher and heartbeat if file isn't complete
			if !m.fileComplete && !m.watcherStarted {
				if err := m.startWatcher(); err != nil {
					m.logger.Error(fmt.Sprintf("model: error starting watcher: %v", err))
				} else {
					m.logger.Info("model: watcher started successfully")
					// Start heartbeat for live runs
					m.startHeartbeat()
				}
			}
		}

		return m, tea.Batch(cmds...)

	case BatchedRecordsMsg:
		m.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))

		// Process all messages
		for _, subMsg := range msg.Msgs {
			var cmd tea.Cmd
			m, cmd = m.processRecordMsg(subMsg)
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
		}

		// Only exit loading state if we have actual metric data (charts)
		m.chartMu.RLock()
		hasCharts := len(m.allCharts) > 0
		m.chartMu.RUnlock()

		if m.isLoading && hasCharts {
			m.isLoading = false
		}

		// Start watcher and heartbeat after initial load if file isn't complete
		if !m.fileComplete && !m.watcherStarted {
			if err := m.startWatcher(); err != nil {
				m.logger.Error(fmt.Sprintf("model: error starting watcher: %v", err))
			} else {
				m.logger.Info("model: watcher started successfully")
				// Start heartbeat for live runs
				m.startHeartbeat()
			}
		}
		return m, tea.Batch(cmds...)

	case ReloadMsg:
		m.runState = RunStateRunning
		m.fileComplete = false

		// Stop heartbeat
		m.stopHeartbeat()

		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher for reload")
			m.watcher.Finish()
			m.watcherStarted = false
		}

		// Create a new watcher instance
		m.watcher = watcher.New(watcher.Params{})

		// Clear the message channel
		for len(m.msgChan) > 0 {
			<-m.msgChan
		}

		// Reset loading state
		m.recordsLoaded = 0
		m.loadStartTime = time.Now()

		return m, tea.Batch(
			InitializeReader(m.runPath),
			m.waitForWatcherMsg(),
		)

	case HeartbeatMsg:
		m.logger.Debug("model: processing HeartbeatMsg")
		// Treat heartbeat like a file change event
		// This will trigger a read and reset the heartbeat timer
		cmds = append(cmds, ReadAvailableRecords(m.reader))
		// Reset heartbeat for next interval
		m.resetHeartbeat()
		// Continue waiting for watcher messages
		cmds = append(cmds, m.waitForWatcherMsg())
		return m, tea.Batch(cmds...)

	case FileChangedMsg:
		// Reset heartbeat when we get a real file change
		m.resetHeartbeat()

		// Debounce file changes
		m.debounceMu.Lock()
		now := time.Now()
		timeSinceLastChange := now.Sub(m.lastFileChange)
		m.lastFileChange = now

		// If we have a pending timer, stop it
		if m.debounceTimer != nil {
			m.debounceTimer.Stop()
		}

		// Only process if enough time has passed since last change (100ms debounce)
		if timeSinceLastChange > 100*time.Millisecond {
			m.logger.Debug("model: processing FileChangedMsg after debounce")
			m.debounceMu.Unlock()
			cmds = append(cmds, ReadAvailableRecords(m.reader))
		} else {
			// Set a timer to process after debounce period
			m.debounceTimer = time.AfterFunc(100*time.Millisecond, func() {
				select {
				case m.msgChan <- FileChangedMsg{}:
				default:
					m.logger.Warn("model: msgChan full during debounce timer")
				}
			})
			m.debounceMu.Unlock()
		}
		// Always continue waiting for more changes
		cmds = append(cmds, m.waitForWatcherMsg())
		return m, tea.Batch(cmds...)

	case tea.KeyMsg:
		newModel, cmd := m.handleKeyMsg(msg)
		return newModel, cmd

	case tea.MouseMsg, tea.WindowSizeMsg, SidebarAnimationMsg, RightSidebarAnimationMsg:
		newModel, cmd := m.handleOther(msg)
		return newModel, cmd

	default:
		// Process other record messages
		var cmd tea.Cmd
		m, cmd = m.processRecordMsg(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	return m, tea.Batch(cmds...)
}

// View implements tea.Model
func (m *Model) View() string {
	// Recover from any panics in View
	defer m.recoverPanic("View")

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	// Check if we're in a crashed state
	if m.runState == RunStateCrashed {
		return m.renderCrashedScreen()
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

// renderCrashedScreen shows an error screen when the app has crashed
func (m *Model) renderCrashedScreen() string {
	errorStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color("196")).
		Bold(true)

	errorContent := lipgloss.JoinVertical(
		lipgloss.Center,
		errorStyle.Render("Application Error"),
		"",
		"The application encountered an error and recovered.",
		"Please check the debug log for details.",
		"",
		"Press 'q' to quit or 'alt+r' to reload.",
	)

	centered := lipgloss.Place(
		m.width,
		m.height-StatusBarHeight,
		lipgloss.Center,
		lipgloss.Center,
		errorContent,
	)

	statusBar := m.renderStatusBar()
	return lipgloss.JoinVertical(lipgloss.Left, centered, statusBar)
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
				statusText += " • "
			}
			statusText += fmt.Sprintf("Overview: \"%s\" [%s] ([ to change, Ctrl+K to clear)",
				m.sidebar.GetFilterQuery(), filterInfo)
		}

		// Add selected overview item if sidebar is visible (no truncation)
		if m.sidebar.IsVisible() {
			key, value := m.sidebar.GetSelectedItem()
			if key != "" {
				if statusText != "" {
					statusText += " • "
				}
				statusText += fmt.Sprintf("%s: %s", key, value)
			}
		}

		// Add focused metric name if a chart is focused
		if m.focusedTitle != "" {
			if statusText != "" {
				statusText += " • "
			}
			statusText += m.focusedTitle
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

		// Try to send the message, but don't block
		select {
		case m.msgChan <- FileChangedMsg{}:
			m.logger.Debug("model: FileChangedMsg sent to channel")
		default:
			// Channel is full, check if we need to grow it
			currentCap := cap(m.msgChan)
			if currentCap < 10000 { // Max buffer size
				m.logger.Warn(fmt.Sprintf("model: msgChan full (cap=%d), growing buffer", currentCap))
				// Create a new larger channel
				newCap := currentCap * 2
				if newCap > 10000 {
					newCap = 10000
				}
				newChan := make(chan tea.Msg, newCap)
				// Transfer existing messages
				close(m.msgChan)
				for msg := range m.msgChan {
					select {
					case newChan <- msg:
					default:
						m.logger.Error("model: failed to transfer message to new channel")
					}
				}
				m.msgChan = newChan
				// Try to send the current message
				select {
				case m.msgChan <- FileChangedMsg{}:
					m.logger.Debug("model: FileChangedMsg sent to new channel")
				default:
					m.logger.Error("model: still cannot send FileChangedMsg after growing buffer")
				}
			} else {
				m.logger.Warn("model: msgChan is at max capacity, dropping FileChangedMsg")
			}
		}
	})

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: error in watcher.Watch: %v", err))
		m.watcherStarted = false
		return err
	}

	m.logger.Debug("model: watcher registered successfully")
	return nil
}

// reloadCharts resets all charts and reloads data
func (m *Model) reloadCharts() tea.Cmd {
	// Save current filter
	savedFilter := m.activeFilter

	m.step = 0
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

	// Hide sidebars
	if m.sidebar.IsVisible() {
		m.sidebar.state = SidebarCollapsed
		m.sidebar.currentWidth = 0
		m.sidebar.targetWidth = 0
	}
	if m.rightSidebar.IsVisible() {
		m.rightSidebar.state = SidebarCollapsed
		m.rightSidebar.currentWidth = 0
		m.rightSidebar.targetWidth = 0
	}

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

// rebuildGrids rebuilds the chart grids with new dimensions
func (m *Model) rebuildGrids() {
	// Rebuild metrics grid
	m.charts = make([][]*EpochLineChart, GridRows)
	for row := 0; row < GridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	// Recalculate total pages
	ChartsPerPage = GridRows * GridCols

	m.chartMu.RLock()
	chartCount := len(m.allCharts)
	m.chartMu.RUnlock()

	m.totalPages = (chartCount + ChartsPerPage - 1) / ChartsPerPage

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
