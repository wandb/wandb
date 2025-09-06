package leet

import (
	"fmt"
	"sort"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/runenvironment"
)

// FocusState represents what is currently focused in the UI
type FocusState struct {
	Type  FocusType // What type of element is focused
	Row   int       // Row in grid (for chart focus)
	Col   int       // Column in grid (for chart focus)
	Title string    // Title of focused element
}

// FocusType indicates what type of UI element is focused
type FocusType int

const (
	FocusNone FocusType = iota
	FocusMainChart
	FocusSystemChart
)

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	// Recover from any panics in message processing
	defer m.recoverPanic("processRecordMsg")

	switch msg := msg.(type) {
	case HistoryMsg:
		m.logger.Debug(fmt.Sprintf("model: processing HistoryMsg with step %d", msg.Step))
		// Reset heartbeat on successful data read
		if m.runState == RunStateRunning && !m.fileComplete {
			m.resetHeartbeat()
		}
		return m.handleHistoryMsg(msg)

	case RunMsg:
		m.logger.Debug("model: processing RunMsg")
		m.runOverview.ID = msg.ID
		m.runOverview.DisplayName = msg.DisplayName
		m.runOverview.Project = msg.Project
		if msg.Config != nil {
			onError := func(err error) {
				m.logger.Error(fmt.Sprintf("model: error applying config record: %v", err))
			}
			m.runConfig.ApplyChangeRecord(msg.Config, onError)
			m.runOverview.Config = m.runConfig.CloneTree()
		}
		m.sidebar.SetRunOverview(m.runOverview)

	case StatsMsg:
		m.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		// Reset heartbeat on successful data read
		if m.runState == RunStateRunning && !m.fileComplete {
			m.resetHeartbeat()
		}
		m.rightSidebar.ProcessStatsMsg(msg)

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
				m.logger.Error(fmt.Sprintf("model: error processing summary: %v", err))
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
			switch msg.ExitCode {
			case 0:
				m.runState = RunStateFinished
			default:
				m.runState = RunStateFailed
			}
			// Update sidebar with new state
			m.sidebar.SetRunState(m.runState)
			// Stop heartbeat since run is complete
			m.stopHeartbeat()
			if m.watcherStarted {
				m.logger.Debug("model: finishing watcher")
				m.watcher.Finish()
				m.watcherStarted = false
			}
		}

	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		m.runState = RunStateFailed
		// Update sidebar with new state
		m.sidebar.SetRunState(m.runState)
		// Stop heartbeat on error
		m.stopHeartbeat()
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcher.Finish()
			m.watcherStarted = false
		}
	}

	return m, nil
}

// handleHistoryMsg processes new history data
//
//gocyclo:ignore
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	// Track if we need to sort
	needsSort := false

	// Lock for write when modifying charts
	m.chartMu.Lock()

	// Save the currently focused chart's title if any
	var previouslyFocusedTitle string
	if m.focusState.Type == FocusMainChart &&
		m.focusState.Row >= 0 && m.focusState.Col >= 0 &&
		m.focusState.Row < len(m.charts) && m.focusState.Col < len(m.charts[m.focusState.Row]) &&
		m.charts[m.focusState.Row][m.focusState.Col] != nil {
		previouslyFocusedTitle = m.charts[m.focusState.Row][m.focusState.Col].Title()
	}

	// Track new charts for adding to filtered list
	var newCharts []*EpochLineChart

	// Add data points to existing charts or create new ones
	for metricName, value := range msg.Metrics {
		m.logger.Debug(fmt.Sprintf("processing %v, %v", metricName, value))
		chart, exists := m.chartsByName[metricName]
		m.logger.Debug(fmt.Sprintf("it exists: %v", exists))
		if !exists {
			availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width() - 4
			dims := CalculateChartDimensions(availableWidth, m.height-StatusBarHeight)
			// Create chart without color - it will be assigned during sort
			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, 0, metricName)

			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart
			newCharts = append(newCharts, chart)
			needsSort = true

			// Log when we're creating many charts
			if len(m.allCharts)%1000 == 0 {
				m.logger.Info(fmt.Sprintf("model: created %d charts", len(m.allCharts)))
			}
		}
		chart.AddDataPoint(value)
	}

	// Sort if we added new charts (this will also assign/reassign colors)
	if needsSort {
		m.sortChartsNoLock()

		// If no filter is active, add new charts to filteredCharts
		if m.activeFilter == "" {
			// Add new charts to filtered list and re-sort
			for _, newChart := range newCharts {
				// Check if it's not already in filteredCharts (shouldn't be, but safe check)
				found := false
				for _, fc := range m.filteredCharts {
					if fc == newChart {
						found = true
						break
					}
				}
				if !found {
					m.filteredCharts = append(m.filteredCharts, newChart)
				}
			}
			// Re-sort filteredCharts to maintain alphabetical order
			sort.Slice(m.filteredCharts, func(i, j int) bool {
				return m.filteredCharts[i].Title() < m.filteredCharts[j].Title()
			})
		} else {
			// Apply current filter to new charts
			m.applyFilterNoLock(m.activeFilter)
		}

		m.totalPages = (len(m.filteredCharts) + ChartsPerPage - 1) / ChartsPerPage
	}

	// Exit loading state only when we have actual charts with data
	if m.isLoading && len(m.allCharts) > 0 {
		m.isLoading = false
	}

	// Reload page while holding the lock (mutates grid)
	shouldDraw := len(msg.Metrics) > 0
	if shouldDraw {
		m.loadCurrentPageNoLock()
	}

	// Capture before unlocking
	prevTitle := previouslyFocusedTitle
	m.chartMu.Unlock()

	// Restore focus and draw OUTSIDE the critical section
	if shouldDraw {
		if prevTitle != "" && m.focusState.Type == FocusMainChart {
			// Use a read lock while scanning the grid
			m.chartMu.RLock()
			foundRow, foundCol := -1, -1
			for row := 0; row < GridRows; row++ {
				for col := 0; col < GridCols; col++ {
					if row < len(m.charts) && col < len(m.charts[row]) &&
						m.charts[row][col] != nil &&
						m.charts[row][col].Title() == prevTitle {
						foundRow, foundCol = row, col
						break
					}
				}
				if foundRow != -1 {
					break
				}
			}
			m.chartMu.RUnlock()
			if foundRow != -1 {
				m.setMainChartFocus(foundRow, foundCol)
			}
		}
		m.drawVisibleCharts()
	}

	return m, nil
}

// drawVisibleCharts only draws charts that are currently visible
func (m *Model) drawVisibleCharts() {
	defer func() {
		if r := recover(); r != nil {
			m.logger.Error(fmt.Sprintf("panic in drawVisibleCharts: %v", r))
		}
	}()

	// Force redraw all visible charts
	for row := 0; row < GridRows; row++ {
		for col := 0; col < GridCols; col++ {
			if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
				chart := m.charts[row][col]
				// Always force a redraw when this is called
				chart.dirty = true
				chart.Draw()
				chart.dirty = false
			}
		}
	}
}

// handleChartGridClick handles mouse clicks in the main chart grid
func (m *Model) handleChartGridClick(row, col int) {
	// Check if clicking on the already focused chart (to unfocus)
	if m.focusState.Type == FocusMainChart &&
		row == m.focusState.Row && col == m.focusState.Col {
		m.clearAllFocus()
		return
	}

	// Set new focus
	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols &&
		row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		// Clear system chart focus if any
		if m.rightSidebar.metricsGrid != nil {
			m.rightSidebar.metricsGrid.clearFocus()
		}
		// Clear any existing main chart focus
		m.clearMainChartFocus()
		// Set new focus
		m.setMainChartFocus(row, col)
	}
}

// setMainChartFocus sets focus to a main grid chart
func (m *Model) setMainChartFocus(row, col int) {
	// Assumes caller holds chartMu lock if needed
	if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		chart := m.charts[row][col]
		m.focusState = FocusState{
			Type:  FocusMainChart,
			Row:   row,
			Col:   col,
			Title: chart.Title(),
		}
		m.focusedRow = row // Keep backward compatibility
		m.focusedCol = col
		m.focusedTitle = chart.Title()
		chart.SetFocused(true)
	}
}

// clearMainChartFocus clears focus only from main charts
func (m *Model) clearMainChartFocus() {
	// Clear main chart focus only
	if m.focusState.Type == FocusMainChart {
		if m.focusState.Row >= 0 && m.focusState.Col >= 0 &&
			m.focusState.Row < len(m.charts) && m.focusState.Col < len(m.charts[m.focusState.Row]) &&
			m.charts[m.focusState.Row][m.focusState.Col] != nil {
			m.charts[m.focusState.Row][m.focusState.Col].SetFocused(false)
		}
	}

	// Reset focus state only if it was a main chart
	if m.focusState.Type == FocusMainChart {
		m.focusState = FocusState{Type: FocusNone}
		m.focusedRow = -1
		m.focusedCol = -1
		m.focusedTitle = ""
	}
}

// clearAllFocus clears focus from all UI elements
func (m *Model) clearAllFocus() {
	// Clear main chart focus
	if m.focusState.Type == FocusMainChart {
		if m.focusState.Row >= 0 && m.focusState.Col >= 0 &&
			m.focusState.Row < len(m.charts) && m.focusState.Col < len(m.charts[m.focusState.Row]) &&
			m.charts[m.focusState.Row][m.focusState.Col] != nil {
			m.charts[m.focusState.Row][m.focusState.Col].SetFocused(false)
		}
	}

	// Clear system chart focus
	if m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.clearFocus()
	}

	// Reset focus state
	m.focusState = FocusState{Type: FocusNone}
	m.focusedRow = -1
	m.focusedCol = -1
	m.focusedTitle = ""
}

// handleMouseMsg processes mouse events
//
//gocyclo:ignore
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	// Check if mouse is in left sidebar
	if msg.X < m.sidebar.Width() {
		// Mouse is in left sidebar - clear any chart focus
		m.clearAllFocus()
		return m, nil
	}

	// Check if mouse is in right sidebar (for system metrics)
	rightSidebarStart := m.width - m.rightSidebar.Width()
	if msg.X >= rightSidebarStart && m.rightSidebar.Width() > 0 {
		// Adjust coordinates relative to sidebar
		adjustedX := msg.X - rightSidebarStart

		// Handle left click for focus
		if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
			tea.MouseEvent(msg).Action == tea.MouseActionPress {

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: RIGHT SIDEBAR CLICK at adjustedX=%d, Y=%d", adjustedX, msg.Y))
			m.logger.Debug(fmt.Sprintf("handleMouseMsg: BEFORE - focusState.Type=%v, focusedTitle='%s'", m.focusState.Type, m.focusedTitle))

			// Handle the click in system metrics
			focusSet := m.rightSidebar.HandleMouseClick(adjustedX, msg.Y)

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: HandleMouseClick returned focusSet=%v", focusSet))
			m.logger.Debug(fmt.Sprintf("handleMouseMsg: GetFocusedChartTitle='%s'", m.rightSidebar.GetFocusedChartTitle()))

			if focusSet {
				// System chart was focused - only clear main chart focus
				m.clearMainChartFocus()

				// Set focus state for system chart
				title := m.rightSidebar.GetFocusedChartTitle()
				m.focusState = FocusState{
					Type:  FocusSystemChart,
					Title: title,
				}
				m.focusedTitle = title
				m.logger.Debug(fmt.Sprintf("handleMouseMsg: FOCUSED - set focusedTitle='%s'", m.focusedTitle))
			} else {
				// System chart was unfocused (clicked on already-focused chart)
				// The system grid has already cleared its internal focus
				// We just need to clear our tracking
				m.logger.Debug("handleMouseMsg: UNFOCUSED - clearing focus state")
				m.focusState = FocusState{Type: FocusNone}
				m.focusedTitle = ""
			}

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: AFTER - focusState.Type=%v, focusedTitle='%s'", m.focusState.Type, m.focusedTitle))
		}

		// Handle wheel events for zoom (if we want to add zoom to system metrics later)
		// For now, just return
		return m, nil
	}

	// Mouse is in the main chart area - account for padding
	const gridPadding = 1
	adjustedX := msg.X - m.sidebar.Width() - gridPadding
	adjustedY := msg.Y - gridPadding - 1 // -1 for header

	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width() - (gridPadding * 2)
	dims := CalculateChartDimensions(availableWidth, m.height-StatusBarHeight)

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	// Handle left click for focus
	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {
		if row >= 0 && row < GridRows && col >= 0 && col < GridCols {
			m.handleChartGridClick(row, col)
		}
		return m, nil
	}

	// Handle wheel events for zoom
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	// Use RLock for reading charts
	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols &&
		row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		chart := m.charts[row][col]

		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}

		relativeMouseX := adjustedX - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			// Focus the chart when zooming (if not already focused)
			if m.focusState.Type != FocusMainChart ||
				m.focusState.Row != row || m.focusState.Col != col {
				m.clearAllFocus()
				m.setMainChartFocus(row, col)
			}

			switch msg.Button {
			case tea.MouseButtonWheelUp:
				chart.HandleZoom("in", relativeMouseX)
			case tea.MouseButtonWheelDown:
				chart.HandleZoom("out", relativeMouseX)
			}
			chart.DrawIfNeeded()
		}
	}

	return m, nil
}

// handleOverviewFilter handles overview filter input.
func (m *Model) handleOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if !m.overviewFilterMode {
		return m, nil
	}

	switch msg.Type {
	case tea.KeyEsc:
		// Cancel filter input - restore to last applied state
		m.overviewFilterMode = false
		m.overviewFilterInput = ""
		// Restore the applied filter if any
		if m.sidebar.filterApplied && m.sidebar.appliedQuery != "" {
			m.sidebar.filterQuery = m.sidebar.appliedQuery
			m.sidebar.applyFilter()
			m.sidebar.calculateSectionHeights()
		} else {
			// No applied filter, clear everything
			m.sidebar.filterActive = false
			m.sidebar.filterQuery = ""
			m.sidebar.applyFilter()
			m.sidebar.calculateSectionHeights()
		}
		return m, nil

	case tea.KeyEnter:
		// Apply filter
		m.overviewFilterMode = false
		m.sidebar.filterQuery = m.overviewFilterInput // Ensure query is set
		m.sidebar.ConfirmFilter()
		return m, nil

	case tea.KeyBackspace:
		// Remove last character
		if len(m.overviewFilterInput) > 0 {
			m.overviewFilterInput = m.overviewFilterInput[:len(m.overviewFilterInput)-1]
			m.sidebar.UpdateFilter(m.overviewFilterInput)
		}
		return m, nil

	case tea.KeyRunes:
		// Add typed characters
		m.overviewFilterInput += string(msg.Runes)
		m.sidebar.UpdateFilter(m.overviewFilterInput)
		return m, nil

	case tea.KeySpace:
		// Add space
		m.overviewFilterInput += " "
		m.sidebar.UpdateFilter(m.overviewFilterInput)
		return m, nil
	}

	return m, nil
}

// handleKeyMsg processes keyboard events
//
//gocyclo:ignore
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Handle overview filter mode FIRST
	if m.overviewFilterMode {
		return m.handleOverviewFilter(msg)
	}

	// Handle filter mode input
	if m.filterMode {
		switch msg.Type {
		case tea.KeyEsc:
			// Cancel filter input
			m.exitFilterMode(false)
			return m, nil
		case tea.KeyEnter:
			// Apply filter
			m.exitFilterMode(true)
			return m, nil
		case tea.KeyBackspace:
			// Remove last character
			if len(m.filterInput) > 0 {
				m.filterInput = m.filterInput[:len(m.filterInput)-1]
				// Live preview
				m.applyFilter(m.filterInput)
				m.drawVisibleCharts()
			}
			return m, nil
		case tea.KeyRunes:
			// Add typed characters
			m.filterInput += string(msg.Runes)
			// Live preview
			m.applyFilter(m.filterInput)
			m.drawVisibleCharts()
			return m, nil
		case tea.KeySpace:
			// Add space
			m.filterInput += " "
			// Live preview
			m.applyFilter(m.filterInput)
			m.drawVisibleCharts()
			return m, nil
		default:
			// Ignore other keys in filter mode
			return m, nil
		}
	}

	// If we're waiting for a config key, handle that next
	if m.waitingForConfigKey {
		return m.handleConfigNumberKey(msg)
	}

	switch msg.Type {
	case tea.KeyCtrlB:
		// Prevent concurrent animations
		m.animationMu.Lock()
		if m.animating {
			m.animationMu.Unlock()
			return m, nil
		}
		m.animating = true
		m.animationMu.Unlock()

		// Determine what the left sidebar state will be after toggle
		leftWillBeVisible := !m.sidebar.IsVisible()

		// Save the new state to config
		cfg := GetConfig()
		if err := cfg.SetLeftSidebarVisible(leftWillBeVisible); err != nil {
			m.logger.Error(fmt.Sprintf("model: failed to save left sidebar state: %v", err))
		}

		// Update dimensions BEFORE toggling
		// Pass the ACTUAL future state of the left sidebar
		m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(m.width, leftWillBeVisible)

		// Toggle the sidebar
		m.sidebar.Toggle()

		// Update chart sizes - this will be safe now
		m.updateChartSizes()

		return m, m.sidebar.animationCmd()

	case tea.KeyCtrlN:
		// Prevent concurrent animations
		m.animationMu.Lock()
		if m.animating {
			m.animationMu.Unlock()
			return m, nil
		}
		m.animating = true
		m.animationMu.Unlock()

		// Determine what the right sidebar state will be after toggle
		rightWillBeVisible := !m.rightSidebar.IsVisible()

		// Save the new state to config
		cfg := GetConfig()
		if err := cfg.SetRightSidebarVisible(rightWillBeVisible); err != nil {
			m.logger.Error(fmt.Sprintf("model: failed to save right sidebar state: %v", err))
		}

		// Update dimensions BEFORE toggling
		// Pass the ACTUAL future state of the right sidebar
		m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())
		m.sidebar.UpdateDimensions(m.width, rightWillBeVisible)

		// Toggle the sidebar
		m.rightSidebar.Toggle()

		// Update chart sizes - this will be safe now
		m.updateChartSizes()

		return m, m.rightSidebar.animationCmd()

	case tea.KeyCtrlL:
		// Clear filter with Ctrl+L for charts
		if m.activeFilter != "" {
			m.clearFilter()
			return m, nil
		}

	case tea.KeyCtrlK:
		// Clear overview filter with Ctrl+K
		if m.sidebar.IsFiltering() {
			m.sidebar.clearFilter()
			return m, nil
		}

	case tea.KeyPgUp, tea.KeyShiftUp:
		m.navigatePage(-1)

	case tea.KeyPgDown, tea.KeyShiftDown:
		m.navigatePage(1)
	}

	switch msg.String() {
	case "h", "?":
		m.help.Toggle()
		return m, nil

	case "q", "ctrl+c":
		m.logger.Debug("model: quit requested")
		if m.reader != nil {
			m.reader.Close()
		}
		// Stop heartbeat
		m.stopHeartbeat()
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher on quit")
			m.watcher.Finish()
			m.watcherStarted = false
		}
		close(m.msgChan)
		return m, tea.Quit

	case "/":
		// Enter filter mode for charts
		m.enterFilterMode()
		return m, nil

	case "[":
		// Enter filter mode for overview - using [ as it's simple
		m.overviewFilterMode = true
		// Start with existing filter if any
		if m.sidebar.filterApplied && m.sidebar.appliedQuery != "" {
			m.overviewFilterInput = m.sidebar.appliedQuery
		} else {
			m.overviewFilterInput = ""
		}
		m.sidebar.StartFilter()
		return m, nil

	case "r":
		// Lowercase r for metrics rows
		m.waitingForConfigKey = true
		m.configKeyType = "r"
		return m, nil

	case "R":
		// Uppercase R - system grid rows
		m.waitingForConfigKey = true
		m.configKeyType = "R"
		return m, nil

	case "c":
		// Lowercase c - metrics grid columns
		m.waitingForConfigKey = true
		m.configKeyType = "c"
		return m, nil

	case "C":
		// Uppercase C - system grid columns
		m.waitingForConfigKey = true
		m.configKeyType = "C"
		return m, nil

	case "alt+r":
		// Alt+r for reload
		return m, m.reloadCharts()

	}

	return m, nil
}

// handleConfigNumberKey handles number input for configuration.
func (m *Model) handleConfigNumberKey(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Cancel on escape
	if msg.String() == "esc" {
		m.waitingForConfigKey = false
		m.configKeyType = ""
		return m, nil
	}

	// Check if it's a number 1-9
	var num int
	switch msg.String() {
	case "1":
		num = 1
	case "2":
		num = 2
	case "3":
		num = 3
	case "4":
		num = 4
	case "5":
		num = 5
	case "6":
		num = 6
	case "7":
		num = 7
	case "8":
		num = 8
	case "9":
		num = 9
	default:
		// Not a valid number, cancel
		m.waitingForConfigKey = false
		m.configKeyType = ""
		return m, nil
	}

	// Apply the configuration change
	cfg := GetConfig()
	var err error
	var statusMsg string

	switch m.configKeyType {
	case "c": // Metrics columns
		err = cfg.SetMetricsCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid columns set to %d", num)
		}
	case "r": // Metrics rows
		err = cfg.SetMetricsRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid rows set to %d", num)
		}
	case "C": // System columns
		err = cfg.SetSystemCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid columns set to %d", num)
		}
	case "R": // System rows
		err = cfg.SetSystemRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid rows set to %d", num)
		}
	}

	// Reset state
	m.waitingForConfigKey = false
	m.configKeyType = ""

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to update config: %v", err))
		return m, nil
	}

	// Update grid dimensions and rebuild the UI
	UpdateGridDimensions()
	m.rebuildGrids()
	m.updateChartSizes()

	// Log the status message for now (could show in status bar later)
	m.logger.Info(statusMsg)

	return m, nil
}

// handleOther handles remaining message types
func (m *Model) handleOther(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.help.SetSize(msg.Width, msg.Height)

		// Update sidebar dimensions based on new window size
		m.sidebar.UpdateDimensions(msg.Width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(msg.Width, m.sidebar.IsVisible())

		// Then update chart sizes
		m.updateChartSizes()

	case SidebarAnimationMsg:
		if m.sidebar.IsAnimating() {
			// Don't update chart sizes during every animation frame
			// Just continue the animation
			return m, m.sidebar.animationCmd()
		} else {
			// Animation complete - now update everything
			m.animationMu.Lock()
			m.animating = false
			m.animationMu.Unlock()

			// Final update after animation completes
			m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())
			m.updateChartSizes()

			// Force redraw all visible charts now that animation is complete
			m.drawVisibleCharts()
		}

	case RightSidebarAnimationMsg:
		if m.rightSidebar.IsAnimating() {
			// Don't update chart sizes during every animation frame
			// Just continue the animation
			return m, m.rightSidebar.animationCmd()
		} else {
			// Animation complete - now update everything
			m.animationMu.Lock()
			m.animating = false
			m.animationMu.Unlock()

			// Final update after animation completes
			m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
			m.updateChartSizes()

			// Force redraw all visible charts now that animation is complete
			m.drawVisibleCharts()
		}
	}

	return m, nil
}
