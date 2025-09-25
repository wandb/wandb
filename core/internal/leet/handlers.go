package leet

import (
	"fmt"
	"sort"
	"strconv"
	"time"

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
	gridRows, gridCols := m.config.GetMetricsGrid()
	chartsPerPage := gridRows * gridCols

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
			// Compute content viewport once
			_, contentW, _, contentH := m.computeViewports()
			dims := CalculateChartDimensions(contentW, contentH)

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
		chart.AddPoint(float64(msg.Step), value)
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

		m.totalPages = (len(m.filteredCharts) + chartsPerPage - 1) / chartsPerPage
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
	if shouldDraw && !m.suppressDraw {
		if prevTitle != "" && m.focusState.Type == FocusMainChart {
			// Use a read lock while scanning the grid
			m.chartMu.RLock()
			foundRow, foundCol := -1, -1
			for row := 0; row < gridRows; row++ {
				for col := 0; col < gridCols; col++ {
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

	gridRows, gridCols := m.config.GetMetricsGrid()

	// Force redraw all visible charts
	for row := 0; row < gridRows; row++ {
		for col := 0; col < gridCols; col++ {
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
	gridRows, gridCols := m.config.GetMetricsGrid()

	// Set new focus
	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row >= 0 && row < gridRows && col >= 0 && col < gridCols &&
		row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		// Clear system chart focus if any (through public API)
		m.rightSidebar.ClearFocus()
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

	// Clear system chart focus via right sidebar API
	m.rightSidebar.ClearFocus()

	// Reset focus state
	m.focusState = FocusState{Type: FocusNone}
	m.focusedRow = -1
	m.focusedCol = -1
	m.focusedTitle = ""
}

// handleMouseMsg processes mouse events, routing by region
//
//gocyclo:ignore
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	// Compute regions once; children do not read each other's widths.
	leftW, contentW, rightW, contentH := m.computeViewports()

	// --- Left sidebar region ---
	if msg.X < leftW {
		// Clicking on overview: clear chart focus on both sides
		m.clearMainChartFocus()
		m.rightSidebar.ClearFocus()
		return m, nil
	}

	// --- Right sidebar region ---
	rightStart := m.width - rightW
	if msg.X >= rightStart && rightW > 0 {
		// Adjust coordinates relative to sidebar
		adjustedX := msg.X - rightStart

		// Handle left click for focus
		if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
			tea.MouseEvent(msg).Action == tea.MouseActionPress {

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: RIGHT SIDEBAR CLICK at adjustedX=%d, Y=%d", adjustedX, msg.Y))
			m.logger.Debug(fmt.Sprintf("handleMouseMsg: BEFORE - focusState.Type=%v, focusedTitle='%s'", m.focusState.Type, m.focusedTitle))

			// Apply focus in system metrics
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
				// System chart was unfocused
				m.logger.Debug("handleMouseMsg: UNFOCUSED - clearing focus state")
				m.focusState = FocusState{Type: FocusNone}
				m.focusedTitle = ""
			}

			m.logger.Debug(fmt.Sprintf("handleMouseMsg: AFTER - focusState.Type=%v, focusedTitle='%s'", m.focusState.Type, m.focusedTitle))
		}
		// TODO: add wheel handling for system metrics.
		return m, nil
	}

	// --- Main content region (metrics grid) ---
	const gridPadding = 1
	adjustedX := msg.X - leftW - gridPadding
	adjustedY := msg.Y - gridPadding - 1 // -1 for header

	dims := CalculateChartDimensions(contentW, contentH)

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	gridRows, gridCols := m.config.GetMetricsGrid()

	// Handle left click for focus
	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {
		if row >= 0 && row < gridRows && col >= 0 && col < gridCols {
			// When focusing main grid, clear system focus
			m.rightSidebar.ClearFocus()
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

	if row >= 0 && row < gridRows && col >= 0 && col < gridCols &&
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

// handleKeyMsg processes keyboard events using the centralized key bindings.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
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
	return m, tea.Quit
}

func (m *Model) handleRestart(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.shouldRestart = true
	m.logger.Debug("model: restart requested")
	return m, tea.Quit
}

func (m *Model) handleToggleLeftSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleToggleRightSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handlePrevPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleNextPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handlePrevSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleNextSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleEnterMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleClearMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleEnterOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleClearOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
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
	m.rebuildGrids()
	m.updateChartSizes()

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
		m.drawVisibleCharts()
	}

	// Exit loading state once we have some charts
	m.chartMu.RLock()
	hasCharts := len(m.allCharts) > 0
	m.chartMu.RUnlock()
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
