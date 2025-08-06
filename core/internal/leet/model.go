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

	width          int
	height         int
	step           int
	focusedRow     int
	focusedCol     int
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

	// Calculate initial buffer size based on expected metrics
	// Start with 1000, will grow dynamically if needed
	initialBufferSize := 1000

	m := &Model{
		help:           NewHelp(),
		allCharts:      make([]*EpochLineChart, 0),
		chartsByName:   make(map[string]*EpochLineChart),
		charts:         make([][]*EpochLineChart, GridRows),
		step:           0,
		focusedRow:     -1,
		focusedCol:     -1,
		currentPage:    0,
		totalPages:     0,
		fileComplete:   false,
		isLoading:      true,
		runPath:        runPath,
		sidebar:        NewSidebar(),
		rightSidebar:   NewRightSidebar(),
		watcher:        watcher.New(watcher.Params{}),
		watcherStarted: false,
		runConfig:      runconfig.New(),
		runSummary:     runsummary.New(),
		msgChan:        make(chan tea.Msg, initialBufferSize),
		logger:         logger,
	}

	for row := range GridRows {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	m.sidebar.SetRunOverview(RunOverview{
		RunPath: runPath,
	})

	return m
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

			// Start watcher if file isn't complete
			if !m.fileComplete && !m.watcherStarted {
				if err := m.startWatcher(); err != nil {
					m.logger.Error(fmt.Sprintf("model: error starting watcher: %v", err))
				} else {
					m.logger.Info("model: watcher started successfully")
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

		// Start watcher after initial load if file isn't complete
		if !m.fileComplete && !m.watcherStarted {
			if err := m.startWatcher(); err != nil {
				m.logger.Error(fmt.Sprintf("model: error starting watcher: %v", err))
			} else {
				m.logger.Info("model: watcher started successfully")
			}
		}
		return m, tea.Batch(cmds...)

	case ReloadMsg:
		m.runState = RunStateRunning
		m.fileComplete = false

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

	case FileChangedMsg:
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
			leftSidebarView = m.sidebar.View(m.height - StatusBarHeight)
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
func (m *Model) renderStatusBar() string {
	// Left side content
	statusText := ""
	switch {
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
		switch m.runState {
		case RunStateRunning:
			statusText = " State: Running"
		case RunStateFinished:
			statusText = " State: Finished"
		case RunStateFailed:
			statusText = " State: Failed"
		case RunStateCrashed:
			statusText = " State: Error (recovered)"
		}
	}

	// Add buffer status if channel is getting full
	bufferUsage := len(m.msgChan)
	bufferCapacity := cap(m.msgChan)
	if bufferUsage > bufferCapacity*3/4 {
		statusText += fmt.Sprintf(" [Buffer: %d/%d]", bufferUsage, bufferCapacity)
	}

	// Right side content
	helpText := "h: toggle help "

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
	m.step = 0
	m.isLoading = true
	m.runState = RunStateRunning // Reset from crashed state if applicable

	m.chartMu.Lock()
	m.allCharts = make([]*EpochLineChart, 0)
	m.chartsByName = make(map[string]*EpochLineChart)
	m.chartMu.Unlock()

	m.totalPages = 0
	m.currentPage = 0

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

	// Update chart sizes
	m.updateChartSizes()
	m.loadCurrentPage()

	return func() tea.Msg {
		return ReloadMsg{}
	}
}

// clearFocus removes focus from all charts
func (m *Model) clearFocus() {
	if m.focusedRow >= 0 && m.focusedCol >= 0 &&
		m.focusedRow < len(m.charts) && m.focusedCol < len(m.charts[m.focusedRow]) &&
		m.charts[m.focusedRow][m.focusedCol] != nil {
		m.charts[m.focusedRow][m.focusedCol].SetFocused(false)
	}
}

// navigatePage changes the current page
func (m *Model) navigatePage(direction int) {
	if m.totalPages <= 1 {
		return
	}
	m.clearFocus()
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

	// Clear focus as grid layout has changed
	m.clearFocus()
	m.focusedRow = -1
	m.focusedCol = -1
}
