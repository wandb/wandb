package leet

import (
	"fmt"
	"strings"

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
	help         *HelpModel
	allCharts    []*EpochLineChart
	chartsByName map[string]*EpochLineChart
	// charts holds the current page of charts arranged in grid
	charts         [][]*EpochLineChart
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
	watcherStarted bool // Track if watcher has been started
	sidebar        *Sidebar
	rightSidebar   *RightSidebar
	runOverview    RunOverview
	runConfig      *runconfig.RunConfig
	runEnvironment *runenvironment.RunEnvironment
	runSummary     *runsummary.RunSummary

	// msgChan is the channel to receive watcher callbacks.
	msgChan chan tea.Msg

	// logger is the debug logger for the application.
	logger *observability.CoreLogger
}

func NewModel(runPath string, logger *observability.CoreLogger) *Model {
	logger.Info(fmt.Sprintf("model: creating new model for runPath: %s", runPath))

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
		msgChan:        make(chan tea.Msg, 100),
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

// Init implements tea.Model.
func (m *Model) Init() tea.Cmd {
	m.logger.Debug("model: Init called")
	return tea.Batch(
		tea.SetWindowTitle("wandb leet"),
		InitializeReader(m.runPath),
		m.waitForWatcherMsg(), // Start listening for watcher messages
	)
}

// Update implements tea.Model.
//
//gocyclo:ignore
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	m.logger.Debug(fmt.Sprintf("model: Update received message: %T", msg))

	// Handle window resize for help
	if msg, ok := msg.(tea.WindowSizeMsg); ok {
		m.help.SetSize(msg.Width, msg.Height)
	}

	// Check for help toggle key first, before passing to help screen
	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch keyMsg.String() {
		case "h", "?":
			m.help.Toggle()
			return m, nil
		}
	}

	// Handle help screen UI updates if active (only for UI-related messages)
	if m.help.IsActive() {
		switch msg.(type) {
		case tea.KeyMsg, tea.MouseMsg:
			// Only pass UI events to help screen
			updatedHelp, helpCmd := m.help.Update(msg)
			m.help = updatedHelp
			if helpCmd != nil {
				cmds = append(cmds, helpCmd)
			}
			// Return early only for UI events when help is active
			return m, tea.Batch(cmds...)
		}
		// For non-UI messages, continue processing below
	}

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

	switch msg := msg.(type) {
	case InitMsg:
		m.logger.Debug("model: InitMsg received, reader initialized")
		m.reader = msg.Reader
		// Perform the initial read.
		return m, ReadAvailableRecords(m.reader)

	case ReloadMsg:
		// Reset run state
		m.runState = RunStateRunning
		m.fileComplete = false

		// TODO: I think the watch part doesn't work properly, need to fix.
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher")
			m.watcher.Finish()
			m.watcherStarted = false
		}
		return m, tea.Batch(
			InitializeReader(m.runPath),
			m.waitForWatcherMsg(),
		)

	case BatchedRecordsMsg:
		m.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))
		// Process all records from the batch.
		for _, subMsg := range msg.Msgs {
			m.logger.Debug(fmt.Sprintf("model: processing sub-message: %T", subMsg))
			var cmd tea.Cmd
			m, cmd = m.processRecordMsg(subMsg)
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
		}

		// After processing initial messages, start the watcher if needed
		if !m.fileComplete && !m.watcherStarted {
			m.logger.Debug(fmt.Sprintf("model: starting watcher - fileComplete: %v, watcherStarted: %v", m.fileComplete, m.watcherStarted))
			if err := m.startWatcher(); err != nil {
				m.logger.Error(fmt.Sprintf("model: error starting watcher: %v", err))
			} else {
				m.logger.Info("model: watcher started successfully")
			}
		} else {
			m.logger.Info(fmt.Sprintf("model: not starting watcher - fileComplete: %v, watcherStarted: %v", m.fileComplete, m.watcherStarted))
		}

		return m, tea.Batch(cmds...)

	case FileChangedMsg:
		m.logger.Debug("model: fileChangedMsg received - file has changed!")
		// File changed, read new records
		cmds = append(cmds, ReadAvailableRecords(m.reader))
		// Continue waiting for watcher messages
		cmds = append(cmds, m.waitForWatcherMsg())
		return m, tea.Batch(cmds...)

	case tea.KeyMsg:
		newModel, cmd := m.handleKeyMsg(msg)
		return newModel, cmd

	case tea.MouseMsg, tea.WindowSizeMsg, SidebarAnimationMsg, RightSidebarAnimationMsg:
		newModel, cmd := m.handleOther(msg)
		return newModel, cmd

	default:
		// Process individual record messages
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
		return lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
	}

	// Calculate available space for charts (account for header)
	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
	availableHeight := m.height - StatusBarHeight - 1 // -1 for the metrics header
	dims := CalculateChartDimensions(availableWidth, availableHeight)

	// Render main content
	gridView := m.renderGrid(dims)

	// Build the main view based on sidebar visibility
	var mainView string
	leftSidebarView := m.sidebar.View(m.height - StatusBarHeight)
	rightSidebarView := m.rightSidebar.View(m.height - StatusBarHeight)

	// Handle all combinations of sidebar visibility
	switch {
	case m.sidebar.Width() > 0 && m.rightSidebar.Width() > 0:
		// Both sidebars visible
		mainView = lipgloss.JoinHorizontal(
			lipgloss.Top,
			leftSidebarView,
			gridView,
			rightSidebarView,
		)
	case m.sidebar.Width() > 0:
		// Only left sidebar visible
		mainView = lipgloss.JoinHorizontal(
			lipgloss.Top,
			leftSidebarView,
			gridView,
		)
	case m.rightSidebar.Width() > 0:
		// Only right sidebar visible
		mainView = lipgloss.JoinHorizontal(
			lipgloss.Top,
			gridView,
			rightSidebarView,
		)
	default:
		// No sidebars visible
		mainView = gridView
	}

	// Render status bar that spans the full width
	statusBar := m.renderStatusBar()

	// Combine main view and status bar
	return lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen
func (m *Model) renderLoadingScreen() string {
	// Style for the ASCII art
	artStyle := lipgloss.NewStyle().
		Foreground(wandbColor).
		Bold(true)

	// Create the full ASCII art with spacing
	logoContent := lipgloss.JoinVertical(
		lipgloss.Center,
		artStyle.Render(wandbArt),
		artStyle.Render(leetArt),
	)

	// Center the logo on the screen
	centeredLogo := lipgloss.Place(
		m.width,
		m.height-StatusBarHeight,
		lipgloss.Center,
		lipgloss.Center,
		logoContent,
	)

	// Render status bar
	statusBar := m.renderStatusBar()

	// Combine logo and status bar
	return lipgloss.JoinVertical(lipgloss.Left, centeredLogo, statusBar)
}

// renderStatusBar creates the status bar, ensuring it fits on a single line.
func (m *Model) renderStatusBar() string {
	statusText := ""

	if m.isLoading {
		statusText = " Loading data..."
	} else {
		switch m.runState {
		case RunStateRunning:
			statusText = " State: Running"
		case RunStateFinished:
			statusText = " State: Finished"
		case RunStateFailed:
			statusText = " State: Failed"
		}
	}

	rightPart := pageInfoStyle.Render("h: toggle help")
	rightWidth := lipgloss.Width(rightPart)

	// Calculate available width for the left part and render it with truncation
	availableWidth := m.width - rightWidth
	leftPart := lipgloss.NewStyle().
		MaxWidth(availableWidth).
		Render(statusText)
	leftWidth := lipgloss.Width(leftPart)

	// Calculate the spacer width
	spacerWidth := m.width - leftWidth - rightWidth
	if spacerWidth < 0 {
		spacerWidth = 0
	}
	spacer := strings.Repeat(" ", spacerWidth)

	// Join the parts and apply the final bar style
	finalBarContent := lipgloss.JoinHorizontal(lipgloss.Top,
		leftPart,
		spacer,
		rightPart,
	)

	return statusBarStyle.Width(m.width).Render(finalBarContent)
}

// waitForWatcherMsg returns a command that waits for messages from the watcher
func (m *Model) waitForWatcherMsg() tea.Cmd {
	return func() tea.Msg {
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

	// Register the file with the watcher
	err := m.watcher.Watch(m.runPath, func() {
		m.logger.Debug(fmt.Sprintf("model: watcher callback triggered! File changed: %s", m.runPath))
		// This callback is called from the watcher's goroutine
		// Send a message through the channel
		select {
		case m.msgChan <- FileChangedMsg{}:
			m.logger.Debug("model: FileChangedMsg sent to channel")
		default:
			m.logger.Warn("model: msgChan is full, dropping FileChangedMsg")
		}
	})

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: error in watcher.Watch: %v", err))
		return err
	}

	m.logger.Debug("model: watcher registered successfully")
	return nil
}

// reloadCharts resets all charts and step counter.
func (m *Model) reloadCharts() tea.Cmd {
	m.step = 0
	m.isLoading = true // Reset to loading state

	m.allCharts = make([]*EpochLineChart, 0)
	m.chartsByName = make(map[string]*EpochLineChart)
	m.totalPages = 0
	m.currentPage = 0

	// Hide sidebars synchronously (no animation)
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

	// Update chart sizes with sidebars hidden
	m.updateChartSizes()
	m.loadCurrentPage()

	return func() tea.Msg {
		return ReloadMsg{}
	}
}
