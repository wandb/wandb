package leet

import (
	"fmt"
	"slices"
	"sort"
	"strconv"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	// Recover from any panics in message processing
	defer m.logPanic("processRecordMsg")

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
		// Delegate to sidebar
		m.leftSidebar.ProcessRunMsg(msg)
		m.runState = RunStateRunning // Model still tracks overall state
		return m, nil

	case StatsMsg:
		m.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		// Reset heartbeat on successful data read
		if m.runState == RunStateRunning && !m.fileComplete {
			m.resetHeartbeat()
		}
		m.rightSidebar.ProcessStatsMsg(msg)
		return m, nil

	case SystemInfoMsg:
		m.logger.Debug("model: processing SystemInfoMsg")
		// Delegate to sidebar
		m.leftSidebar.ProcessSystemInfoMsg(msg.Record)
		return m, nil

	case SummaryMsg:
		m.logger.Debug("model: processing SummaryMsg")
		// Delegate to sidebar
		m.leftSidebar.ProcessSummaryMsg(msg.Summary)
		return m, nil

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
			m.leftSidebar.SetRunState(m.runState)
			// Stop heartbeat since run is complete
			m.stopHeartbeat()
			if m.watcherStarted {
				m.logger.Debug("model: finishing watcher")
				m.watcher.Finish()
				m.watcherStarted = false
			}
		}
		return m, nil

	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		m.runState = RunStateFailed
		// Update sidebar with new state
		m.leftSidebar.SetRunState(m.runState)
		// Stop heartbeat on error
		m.stopHeartbeat()
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcher.Finish()
			m.watcherStarted = false
		}
		return m, nil
	}

	return m, nil
}

// handleHistoryMsg processes new history data.
//
//gocyclo:ignore
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	gridRows, gridCols := m.config.MetricsGrid()
	chartsPerPage := gridRows * gridCols

	// Track if we need to sort
	needsSort := false

	// Lock for write when modifying charts
	m.metrics.chartMu.Lock()

	// Save the currently focused chart's title if any
	var previouslyFocusedTitle string
	if m.metrics.focusState.Type == FocusMainChart &&
		m.metrics.focusState.Row >= 0 && m.metrics.focusState.Col >= 0 &&
		m.metrics.focusState.Row < len(m.metrics.charts) && m.metrics.focusState.Col < len(m.metrics.charts[m.metrics.focusState.Row]) &&
		m.metrics.charts[m.metrics.focusState.Row][m.metrics.focusState.Col] != nil {
		previouslyFocusedTitle = m.metrics.charts[m.metrics.focusState.Row][m.metrics.focusState.Col].Title()
	}

	// Track new charts for adding to filtered list
	var newCharts []*EpochLineChart

	// Add data points to existing charts or create new ones
	for metricName, value := range msg.Metrics {
		m.logger.Debug(fmt.Sprintf("processing %v, %v", metricName, value))
		chart, exists := m.metrics.chartsByName[metricName]
		m.logger.Debug(fmt.Sprintf("it exists: %v", exists))
		if !exists {
			layout := m.computeViewports()
			dims := m.metrics.CalculateChartDimensions(layout.mainContentAreaWidth, layout.height)

			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, metricName)

			m.metrics.allCharts = append(m.metrics.allCharts, chart)
			m.metrics.chartsByName[metricName] = chart
			newCharts = append(newCharts, chart)
			needsSort = true

			// Log when we're creating many charts
			if len(m.metrics.allCharts)%1000 == 0 {
				m.logger.Debug(fmt.Sprintf("model: created %d charts", len(m.metrics.allCharts)))
			}
		}
		chart.AddPoint(float64(msg.Step), value)
	}

	// Sort if we added new charts (this will also assign/reassign colors)
	if needsSort {
		m.metrics.sortChartsNoLock()

		// If no filter is active, add new charts to filteredCharts
		if m.metrics.activeFilter == "" {
			// Add new charts to filtered list and re-sort
			for _, newChart := range newCharts {
				// Check if it's not already in filteredCharts (shouldn't be, but safe check)
				found := slices.Contains(m.metrics.filteredCharts, newChart)
				if !found {
					m.metrics.filteredCharts = append(m.metrics.filteredCharts, newChart)
				}
			}
			// Re-sort filteredCharts to maintain alphabetical order
			sort.Slice(m.metrics.filteredCharts, func(i, j int) bool {
				return m.metrics.filteredCharts[i].Title() < m.metrics.filteredCharts[j].Title()
			})
		} else {
			// Apply current filter to new charts
			m.metrics.applyFilterNoLock(m.metrics.activeFilter)
		}

		m.metrics.totalPages = (len(m.metrics.filteredCharts) + chartsPerPage - 1) / chartsPerPage
	}

	// Exit loading state only when we have actual charts with data
	if m.isLoading && len(m.metrics.allCharts) > 0 {
		m.isLoading = false
	}

	// Reload page while holding the lock (mutates grid)
	shouldDraw := len(msg.Metrics) > 0
	if shouldDraw {
		m.metrics.loadCurrentPageNoLock()
	}

	// Capture before unlocking
	prevTitle := previouslyFocusedTitle
	m.metrics.chartMu.Unlock()

	// Restore focus and draw OUTSIDE the critical section
	if shouldDraw && !m.suppressDraw {
		if prevTitle != "" && m.metrics.focusState.Type == FocusMainChart {
			// Use a read lock while scanning the grid
			m.metrics.chartMu.RLock()
			foundRow, foundCol := -1, -1
			for row := range gridRows {
				for col := range gridCols {
					if row < len(m.metrics.charts) && col < len(m.metrics.charts[row]) &&
						m.metrics.charts[row][col] != nil &&
						m.metrics.charts[row][col].Title() == prevTitle {
						foundRow, foundCol = row, col
						break
					}
				}
				if foundRow != -1 {
					break
				}
			}
			m.metrics.chartMu.RUnlock()
			if foundRow != -1 {
				m.metrics.setFocus(foundRow, foundCol)
			}
		}
		m.metrics.drawVisible()
	}

	return m, nil
}

// handleMouseMsg processes mouse events, routing by region.
//
//gocyclo:ignore
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	layout := m.computeViewports()

	// --- Left sidebar region ---
	if msg.X < layout.leftSidebarWidth {
		// Clicking on overview: clear chart focus on both sides
		m.metrics.clearFocus()
		m.rightSidebar.ClearFocus()
		return m, nil
	}

	// --- Right sidebar region ---
	rightStart := m.width - layout.rightSidebarWidth
	if msg.X >= rightStart && layout.rightSidebarWidth > 0 {
		// Adjust coordinates relative to sidebar
		adjustedX := msg.X - rightStart

		// Handle left click for focus
		if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
			tea.MouseEvent(msg).Action == tea.MouseActionPress {

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: RIGHT SIDEBAR CLICK at adjustedX=%d, Y=%d", adjustedX, msg.Y))
			m.logger.Debug(fmt.Sprintf("handleMouseMsg: BEFORE - focusState.Type=%v, focusedTitle='%s'", m.metrics.focusState.Type, m.focusState.Title))

			// Apply focus in system metrics
			focusSet := m.rightSidebar.HandleMouseClick(adjustedX, msg.Y)

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: HandleMouseClick returned focusSet=%v", focusSet))
			m.logger.Debug(fmt.Sprintf("handleMouseMsg: GetFocusedChartTitle='%s'", m.rightSidebar.GetFocusedChartTitle()))

			if focusSet {
				// System chart was focused, clear main chart focus.
				m.metrics.clearFocus()
				m.logger.Debug(fmt.Sprintf("handleMouseMsg: FOCUSED - set focusedTitle='%s'", m.focusState.Title))
			} else {
				// System chart was unfocused
				m.logger.Debug("handleMouseMsg: UNFOCUSED - clearing focus state")
			}

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: AFTER - focusState.Type=%v, focusedTitle='%s'", m.metrics.focusState.Type, m.focusState.Title))
		}
		// TODO: add wheel handling for system metrics.
		return m, nil
	}

	// --- Main content region (metrics grid) ---
	const gridPadding = 1
	adjustedX := msg.X - layout.leftSidebarWidth - gridPadding
	adjustedY := msg.Y - gridPadding - 1 // -1 for header

	dims := m.metrics.CalculateChartDimensions(layout.mainContentAreaWidth, layout.height)

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	gridRows, gridCols := m.config.MetricsGrid()

	// Handle left click for focus
	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {
		if row >= 0 && row < gridRows && col >= 0 && col < gridCols {
			// When focusing main grid, clear system focus
			m.rightSidebar.ClearFocus()
			m.metrics.handleClick(row, col)
		}
		return m, nil
	}

	// Handle wheel events for zoom
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	// Delegate wheel zoom to main metrics area.
	m.metrics.HandleWheel(
		adjustedX,
		row,
		col,
		dims,
		msg.Button == tea.MouseButtonWheelUp,
	)

	return m, nil
}

// handleKeyMsg processes keyboard events using the centralized key bindings.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.leftSidebar.IsFilterMode() {
		return m.handleOverviewFilter(msg)
	}

	if m.metrics.filterMode {
		return m.handleMetricsFilter(msg)
	}

	if m.pendingGridConfig != gridConfigNone {
		return m.handleConfigNumberKey(msg)
	}

	if handler, ok := m.keyMap[msg.String()]; ok && handler != nil {
		return handler(m, msg)
	}

	return m, nil
}

func (m *Model) handleToggleHelp(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.help.Toggle()
	return m, nil
}

func (m *Model) handleQuit(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.logger.Debug("model: quit requested")
	if m.reader != nil {
		m.reader.Close()
	}
	m.stopHeartbeat()
	if m.watcherStarted {
		m.logger.Debug("model: finishing watcher on quit")
		m.watcher.Finish()
		m.watcherStarted = false
	}
	close(m.wcChan)
	return m, tea.Quit
}

func (m *Model) handleRestart(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.shouldRestart = true
	m.logger.Debug("model: restart requested")
	if m.reader != nil {
		m.reader.Close()
	}
	m.stopHeartbeat()
	if m.watcherStarted {
		m.logger.Debug("model: finishing watcher on restart")
		m.watcher.Finish()
		m.watcherStarted = false
	}
	close(m.wcChan)
	return m, tea.Quit
}

func (m *Model) handleToggleLeftSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Prevent concurrent animations
	m.animationMu.Lock()
	if m.animating {
		m.animationMu.Unlock()
		return m, nil
	}
	m.animating = true
	m.animationMu.Unlock()

	leftWillBeVisible := !m.leftSidebar.IsVisible()

	if err := m.config.SetLeftSidebarVisible(leftWillBeVisible); err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to save left sidebar state: %v", err))
	}

	m.leftSidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
	m.rightSidebar.UpdateDimensions(m.width, leftWillBeVisible)
	m.leftSidebar.Toggle()

	layout := m.computeViewports()
	m.metrics.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return m, m.leftSidebar.animationCmd()
}

func (m *Model) handleToggleRightSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Prevent concurrent animations
	m.animationMu.Lock()
	if m.animating {
		m.animationMu.Unlock()
		return m, nil
	}
	m.animating = true
	m.animationMu.Unlock()

	rightWillBeVisible := !m.rightSidebar.IsVisible()

	if err := m.config.SetRightSidebarVisible(rightWillBeVisible); err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to save right sidebar state: %v", err))
	}

	m.rightSidebar.UpdateDimensions(m.width, m.leftSidebar.IsVisible())
	m.leftSidebar.UpdateDimensions(m.width, rightWillBeVisible)
	m.rightSidebar.Toggle()

	layout := m.computeViewports()
	m.metrics.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return m, m.rightSidebar.animationCmd()
}

func (m *Model) handlePrevPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.metrics.navigatePage(-1)
	return m, nil
}

func (m *Model) handleNextPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.metrics.navigatePage(1)
	return m, nil
}

func (m *Model) handlePrevSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.rightSidebar.IsVisible() && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.Navigate(-1)
	}
	return m, nil
}

func (m *Model) handleNextSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.rightSidebar.IsVisible() && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.Navigate(1)
	}
	return m, nil
}

func (m *Model) handleEnterMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.metrics.enterFilterMode()
	return m, nil
}

func (m *Model) handleClearMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.metrics.activeFilter != "" {
		m.metrics.clearFilter()
	}
	return m, nil
}

func (m *Model) handleEnterOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.leftSidebar.StartFilter()
	return m, nil
}

func (m *Model) handleClearOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.leftSidebar.IsFiltering() {
		m.leftSidebar.clearFilter()
	}
	return m, nil
}

func (m *Model) handleConfigMetricsCols(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigMetricsCols
	return m, nil
}

func (m *Model) handleConfigMetricsRows(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigMetricsRows
	return m, nil
}

func (m *Model) handleConfigSystemCols(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigSystemCols
	return m, nil
}

func (m *Model) handleConfigSystemRows(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigSystemRows
	return m, nil
}

// handleMetricsFilter handles filter mode input for metrics
func (m *Model) handleMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	switch msg.Type {
	case tea.KeyEsc:
		m.metrics.exitFilterMode(false)
		return m, nil
	case tea.KeyEnter:
		m.metrics.exitFilterMode(true)
		return m, nil
	case tea.KeyBackspace:
		if len(m.metrics.filterInput) > 0 {
			m.metrics.filterInput = m.metrics.filterInput[:len(m.metrics.filterInput)-1]
			m.metrics.applyFilter(m.metrics.filterInput)
			m.metrics.drawVisible()
		}
		return m, nil
	case tea.KeyRunes:
		m.metrics.filterInput += string(msg.Runes)
		m.metrics.applyFilter(m.metrics.filterInput)
		m.metrics.drawVisible()
		return m, nil
	case tea.KeySpace:
		m.metrics.filterInput += " "
		m.metrics.applyFilter(m.metrics.filterInput)
		m.metrics.drawVisible()
		return m, nil
	default:
		return m, nil
	}
}

// handleOverviewFilter handles overview filter keyboard input.
func (m *Model) handleOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Sidebar now handles its own filter state
	if !m.leftSidebar.IsFilterMode() {
		return m, nil
	}

	switch msg.Type {
	case tea.KeyEsc:
		// Cancel filter input
		m.leftSidebar.CancelFilter()
		return m, nil

	case tea.KeyEnter:
		// Apply filter
		m.leftSidebar.ConfirmFilter()
		return m, nil

	case tea.KeyBackspace:
		// Remove last character
		input := m.leftSidebar.GetFilterInput()
		if len(input) > 0 {
			m.leftSidebar.UpdateFilter(input[:len(input)-1])
		}
		return m, nil

	case tea.KeyRunes:
		// Add typed characters
		input := m.leftSidebar.GetFilterInput()
		m.leftSidebar.UpdateFilter(input + string(msg.Runes))
		return m, nil

	case tea.KeySpace:
		// Add space
		input := m.leftSidebar.GetFilterInput()
		m.leftSidebar.UpdateFilter(input + " ")
		return m, nil
	}

	return m, nil
}

// handleConfigNumberKey handles number input for configuration.
func (m *Model) handleConfigNumberKey(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Cancel on escape.
	if msg.String() == "esc" {
		m.pendingGridConfig = gridConfigNone
		return m, nil
	}

	// Check if it's a number 1-9.
	num, err := strconv.Atoi(msg.String())
	if err != nil || num < 1 || num > 9 {
		// Invalid input, cancel.
		m.pendingGridConfig = gridConfigNone
		return m, nil
	}

	// Apply the configuration change.
	var statusMsg string
	switch m.pendingGridConfig {
	case gridConfigMetricsCols:
		err = m.config.SetMetricsCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid columns set to %d", num)
		}
	case gridConfigMetricsRows:
		err = m.config.SetMetricsRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid rows set to %d", num)
		}
	case gridConfigSystemCols:
		err = m.config.SetSystemCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid columns set to %d", num)
		}
	case gridConfigSystemRows:
		err = m.config.SetSystemRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid rows set to %d", num)
		}
	}

	// Reset state.
	m.pendingGridConfig = gridConfigNone

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to update config: %v", err))
		return m, nil
	}

	// Update grid dimensions and rebuild the UI
	m.metrics.rebuildGrids()
	// Update metrics using new content viewport
	layout := m.computeViewports()
	m.metrics.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	// TODO: show in status bar.
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
		m.leftSidebar.UpdateDimensions(msg.Width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(msg.Width, m.leftSidebar.IsVisible())

		// Update metrics using new content viewport
		layout := m.computeViewports()
		m.metrics.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	case SidebarAnimationMsg:
		if m.leftSidebar.IsAnimating() {
			// Don't update chart sizes during every animation frame
			// Just continue the animation
			return m, m.leftSidebar.animationCmd()
		} else {
			// Animation complete - now update everything
			m.animationMu.Lock()
			m.animating = false
			m.animationMu.Unlock()

			// Final update after animation completes
			m.rightSidebar.UpdateDimensions(m.width, m.leftSidebar.IsVisible())
			// Update metrics using new content viewport
			layout := m.computeViewports()
			m.metrics.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

			// Force redraw all visible charts now that animation is complete
			m.metrics.drawVisible()
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
			m.leftSidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
			// Update metrics using new content viewport
			layout := m.computeViewports()
			m.metrics.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

			// Force redraw all visible charts now that animation is complete
			m.metrics.drawVisible()
		}
	}

	return m, nil
}

// handleRecordsBatch processes a batch of sub-messages and manages redraw + loading flags.
func (m *Model) handleRecordsBatch(subMsgs []tea.Msg, suppressRedraw bool) []tea.Cmd {
	var cmds []tea.Cmd

	// Coalesce redraws if desired
	prev := m.suppressDraw
	m.suppressDraw = suppressRedraw
	for _, subMsg := range subMsgs {
		var cmd tea.Cmd
		m, cmd = m.processRecordMsg(subMsg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	m.suppressDraw = prev
	if !m.suppressDraw {
		m.metrics.drawVisible()
	}

	// Exit loading state once we have some charts
	m.metrics.chartMu.RLock()
	hasCharts := len(m.metrics.allCharts) > 0
	m.metrics.chartMu.RUnlock()
	if m.isLoading && hasCharts {
		m.isLoading = false
	}
	return cmds
}

// onInit handles InitMsg (reader ready).
func (m *Model) onInit(msg InitMsg) []tea.Cmd {
	m.logger.Debug("model: InitMsg received, reader initialized")
	m.reader = msg.Reader
	m.loadStartTime = time.Now()

	return []tea.Cmd{ReadAllRecordsChunked(m.reader)}
}

// onChunkedBatch handles boot-load chunked batches.
func (m *Model) onChunkedBatch(msg ChunkedBatchMsg) []tea.Cmd {
	m.logger.Debug(fmt.Sprintf("model: ChunkedBatchMsg received with %d messages, hasMore=%v",
		len(msg.Msgs), msg.HasMore))
	m.recordsLoaded += msg.Progress

	cmds := m.handleRecordsBatch(msg.Msgs, false)

	if msg.HasMore {
		cmds = append(cmds, ReadAllRecordsChunked(m.reader))
		return cmds
	}

	// Boot load complete -> begin live mode once.
	if !m.fileComplete && !m.watcherStarted {
		if err := m.startWatcher(); err != nil {
			m.logger.CaptureError(fmt.Errorf("model: error starting watcher: %v", err))
		} else {
			m.logger.Info("model: watcher started successfully")
			m.startHeartbeat()
		}
	}
	return cmds
}

// onBatched handles live drain batches.
func (m *Model) onBatched(msg BatchedRecordsMsg) []tea.Cmd {
	m.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))
	cmds := m.handleRecordsBatch(msg.Msgs, true)
	cmds = append(cmds, ReadAvailableRecords(m.reader))
	return cmds
}

// onHeartbeat triggers a live read and re-arms the heartbeat.
func (m *Model) onHeartbeat() []tea.Cmd {
	m.logger.Debug("model: processing HeartbeatMsg")
	m.resetHeartbeat()
	return []tea.Cmd{
		ReadAvailableRecords(m.reader),
		m.waitForWatcherMsg(),
	}
}

// onFileChange coalesces change notifications into a read.
func (m *Model) onFileChange() []tea.Cmd {
	m.resetHeartbeat()
	return []tea.Cmd{
		ReadAvailableRecords(m.reader),
		m.waitForWatcherMsg(),
	}
}
