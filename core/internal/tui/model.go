package tui

import (
	"fmt"
	"log"
	"strings"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/watcher"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Model represents the main application state.
type Model struct {
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
	runPath        string
	reader         *WandbReader
	watcher        watcher.Watcher
	watcherStarted bool // Track if watcher has been started
	sidebar        *Sidebar
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
		allCharts:      make([]*EpochLineChart, 0),
		chartsByName:   make(map[string]*EpochLineChart),
		charts:         make([][]*EpochLineChart, GridRows),
		step:           0,
		focusedRow:     -1,
		focusedCol:     -1,
		currentPage:    0,
		totalPages:     0,
		fileComplete:   false,
		runPath:        runPath,
		sidebar:        NewSidebar(),
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
		tea.SetWindowTitle("wandb moni"),
		InitializeReader(m.runPath),
		m.waitForWatcherMsg(), // Start listening for watcher messages
	)
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

// Update implements tea.Model.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	m.logger.Debug(fmt.Sprintf("model: Update received message: %T", msg))

	updatedSidebar, sidebarCmd := m.sidebar.Update(msg)
	m.sidebar = updatedSidebar
	if sidebarCmd != nil {
		cmds = append(cmds, sidebarCmd)
	}

	switch msg := msg.(type) {
	case InitMsg:
		m.logger.Debug("model: InitMsg received, reader initialized")
		m.reader = msg.Reader
		// Perform the initial read.
		return m, ReadAvailableRecords(m.reader)

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

	case tea.MouseMsg, tea.WindowSizeMsg, SidebarAnimationMsg:
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

	// Calculate available space for charts
	availableWidth := m.width - m.sidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	// Render main content
	gridView := m.renderGrid(dims)

	// Render sidebar
	sidebarView := m.sidebar.View(m.height - StatusBarHeight)

	// Combine sidebar and main content (without status bar)
	var mainView string
	if m.sidebar.Width() > 0 {
		mainView = lipgloss.JoinHorizontal(
			lipgloss.Top,
			sidebarView,
			gridView,
		)
	} else {
		mainView = gridView
	}

	// Render status bar that spans the full width
	statusBar := m.renderStatusBar()

	// Combine main view and status bar
	return lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
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

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case HistoryMsg:
		m.logger.Debug(fmt.Sprintf("model: processing HistoryMsg with step %d", msg.Step))
		return m.handleHistoryMsg(msg)
	case ConfigMsg:
		m.logger.Debug("model: processing ConfigMsg")
		onError := func(err error) {
			m.logger.Error(fmt.Sprintf("Error applying config record: %v", err))
		}
		m.runConfig.ApplyChangeRecord(msg.Record, onError)
		m.runOverview.Config = m.runConfig.CloneTree()
		m.sidebar.SetRunOverview(m.runOverview)
	case SystemInfoMsg:
		m.logger.Debug("model: processing SystemInfoMsg")
		if m.runEnvironment == nil {
			m.runEnvironment = runenvironment.New(msg.Record.GetWriterId())
		}
		m.runEnvironment.ProcessRecord(msg.Record)
		m.runOverview.Environment = m.runEnvironment.ToRunConfigData()
		m.sidebar.SetRunOverview(m.runOverview)
	case SummaryMsg:
		m.logger.Debug("model: processing SummaryMsg")
		for _, update := range msg.Summary.Update {
			err := m.runSummary.SetFromRecord(update)
			if err != nil {
				m.logger.Error(
					fmt.Sprintf("model: error processing summary: %v", err))
			}
		}

		for _, remove := range msg.Summary.Remove {
			m.runSummary.RemoveFromRecord(remove)
		}
		m.runOverview.Summary = m.runSummary.ToNestedMaps()
		m.sidebar.SetRunOverview(m.runOverview)
	case FileCompleteMsg:
		m.logger.Debug("model: processing FileCompleteMsg - file is complete!")
		if !m.fileComplete {
			m.fileComplete = true
			// Stop the watcher
			if m.watcherStarted {
				log.Printf("Finishing watcher")
				m.watcher.Finish()
			}
		}
	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		// Stop the watcher
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcher.Finish()
		}
	}
	return m, nil
}

// handleHistoryMsg processes new history data
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	m.step = msg.Step
	m.logger.Debug(fmt.Sprintf("model: handling history message for step %d with %d metrics", msg.Step, len(msg.Metrics)))

	for metricName, value := range msg.Metrics {
		chart, exists := m.chartsByName[metricName]
		if !exists {
			availableWidth := m.width - m.sidebar.Width()
			dims := CalculateChartDimensions(availableWidth, m.height)
			colorIndex := len(m.allCharts)
			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, colorIndex, metricName)

			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart

			m.totalPages = (len(m.allCharts) + ChartsPerPage - 1) / ChartsPerPage
			m.logger.Debug(fmt.Sprintf("model: created new chart for metric: %s", metricName))
		}
		chart.AddDataPoint(value)
		chart.Draw()
	}

	m.loadCurrentPage()
	return m, nil
}

// handleMouseMsg processes mouse events
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	if msg.X < m.sidebar.Width() {
		return m, nil
	}

	adjustedX := msg.X - m.sidebar.Width()
	availableWidth := m.width - m.sidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	row := msg.Y / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols && m.charts[row][col] != nil {
		chart := m.charts[row][col]

		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}

		relativeMouseX := adjustedX - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			m.clearFocus()
			m.focusedRow = row
			m.focusedCol = col
			chart.SetFocused(true)

			switch msg.Button {
			case tea.MouseButtonWheelUp:
				chart.HandleZoom("in", relativeMouseX)
			case tea.MouseButtonWheelDown:
				chart.HandleZoom("out", relativeMouseX)
			}
			chart.Draw()
		}
	}

	return m, nil
}

// handleKeyMsg processes keyboard events
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if msg.Type == tea.KeyCtrlB {
		m.sidebar.Toggle()
		m.updateChartSizes()
		return m, m.sidebar.animationCmd()
	}
	switch msg.String() {
	case "q", "ctrl+c":
		m.logger.Debug("model: quit requested")
		if m.reader != nil {
			m.reader.Close()
		}
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher on quit")
			m.watcher.Finish()
		}
		close(m.msgChan) // Clean up the channel
		return m, tea.Quit
	case "r":
		// TODO: convert this into a file reload.
		m.resetCharts()
	case "pgup":
		m.navigatePage(-1)
	case "pgdown":
		m.navigatePage(1)
	}
	return m, nil
}

// handleOther handles remaining message types.
func (m *Model) handleOther(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		newModel, cmd := m.handleMouseMsg(msg)
		if cmd != nil {
			return newModel, cmd
		}
		return m, nil
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.sidebar.UpdateDimensions(msg.Width)
		m.updateChartSizes()
	case SidebarAnimationMsg:
		if m.sidebar.IsAnimating() {
			m.updateChartSizes()
			return m, m.sidebar.animationCmd()
		}
	}
	return m, nil
}

// clearFocus removes focus from all charts.
func (m *Model) clearFocus() {
	if m.focusedRow >= 0 && m.focusedCol >= 0 && m.charts[m.focusedRow][m.focusedCol] != nil {
		m.charts[m.focusedRow][m.focusedCol].SetFocused(false)
	}
}

// resetCharts resets all charts and step counter.
func (m *Model) resetCharts() {
	m.step = 0
	for _, chart := range m.allCharts {
		chart.Reset()
	}
	m.loadCurrentPage()
}

// navigatePage changes the current page.
func (m *Model) navigatePage(direction int) {
	if m.totalPages <= 1 {
		return
	}
	m.clearFocus()
	if direction < 0 {
		m.currentPage--
		if m.currentPage < 0 {
			m.currentPage = m.totalPages - 1
		}
	} else {
		m.currentPage++
		if m.currentPage >= m.totalPages {
			m.currentPage = 0
		}
	}
	m.loadCurrentPage()
}

// renderGrid creates the chart grid view.
func (m *Model) renderGrid(dims ChartDimensions) string {
	var rows []string
	for row := range GridRows {
		var cols []string
		for col := range GridCols {
			cellContent := m.renderGridCell(row, col, dims)
			cols = append(cols, cellContent)
		}
		rowView := lipgloss.JoinHorizontal(lipgloss.Left, cols...)
		rows = append(rows, rowView)
	}
	return lipgloss.JoinVertical(lipgloss.Left, rows...)
}

// renderGridCell renders a single grid cell
func (m *Model) renderGridCell(row, col int, dims ChartDimensions) string {
	if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		chart := m.charts[row][col]
		chartView := chart.View()

		boxStyle := borderStyle
		if row == m.focusedRow && col == m.focusedCol {
			boxStyle = focusedBorderStyle
		}

		boxContent := lipgloss.JoinVertical(
			lipgloss.Left,
			titleStyle.Render(chart.Title()),
			chartView,
		)

		box := boxStyle.Render(boxContent)

		return lipgloss.Place(
			dims.ChartWidthWithPadding,
			dims.ChartHeightWithPadding,
			lipgloss.Left,
			lipgloss.Top,
			box,
		)
	}

	return lipgloss.NewStyle().
		Width(dims.ChartWidthWithPadding).
		Height(dims.ChartHeightWithPadding).
		Render("")
}

// renderStatusBar creates the status bar, ensuring it fits on a single line.
func (m *Model) renderStatusBar() string {
	// Define the left-side content
	statusText := fmt.Sprintf("Step: %d • ctrl+b: sidebar • r: reset • q: quit • PgUp/PgDn: navigate", m.step)
	if !m.fileComplete {
		statusText += " • [Watching file...]"
	} else {
		statusText += " • [Run complete]"
	}

	// Define and style the right-side content
	pageInfo := ""
	if m.totalPages > 0 {
		pageInfo = fmt.Sprintf("Page %d/%d", m.currentPage+1, m.totalPages)
	}
	rightPart := pageInfoStyle.Render(pageInfo)
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

// loadCurrentPage loads the charts for the current page into the grid.
func (m *Model) loadCurrentPage() {
	m.charts = make([][]*EpochLineChart, GridRows)
	for row := 0; row < GridRows; row++ {
		m.charts[row] = make([]*EpochLineChart, GridCols)
	}

	startIdx := m.currentPage * ChartsPerPage
	endIdx := startIdx + ChartsPerPage
	if endIdx > len(m.allCharts) {
		endIdx = len(m.allCharts)
	}

	idx := startIdx
	for row := 0; row < GridRows && idx < endIdx; row++ {
		for col := 0; col < GridCols && idx < endIdx; col++ {
			m.charts[row][col] = m.allCharts[idx]
			if m.charts[row][col] != nil {
				m.charts[row][col].Draw()
			}
			idx++
		}
	}
}

// updateChartSizes updates all chart sizes when window is resized or sidebar toggled.
func (m *Model) updateChartSizes() {
	availableWidth := m.width - m.sidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	for _, chart := range m.allCharts {
		chart.Resize(dims.ChartWidth, dims.ChartHeight)
		chart.Draw()
	}

	m.loadCurrentPage()
}
